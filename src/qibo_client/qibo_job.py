import sys
import tarfile
import tempfile
import time
import typing as T
from enum import Enum
from pathlib import Path

import qibo
import requests
from rich import box

# ---- Rich UI ----
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import constants
from .config_logging import logger
from .utils import QiboApiRequest

console = Console(log_path=False, log_time=True)


# -----------------------------
# Helpers
# -----------------------------
def format_hms(seconds: int | float | None) -> str:
    if seconds is None:
        return "-"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def convert_str_to_job_status(status: str):
    return next((s for s in QiboJobStatus if s.value == status), None)


class QiboJobStatus(Enum):
    QUEUEING = "queueing"
    PENDING = "pending"
    RUNNING = "running"
    POSTPROCESSING = "postprocessing"
    SUCCESS = "success"
    ERROR = "error"


def _write_stream_to_tmp_file(stream: T.Iterable) -> Path:
    """Write chunk of bytes to temporary file."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        for chunk in stream:
            if chunk:
                tmp_file.write(chunk)
        archive_path = tmp_file.name
    return Path(archive_path)


def _extract_archive_to_folder(source_archive: Path, destination_folder: Path):
    with tarfile.open(source_archive, "r:gz") as archive:
        archive.extractall(destination_folder)


def _save_and_unpack_stream_response_to_folder(
    stream: T.Iterable, results_folder: Path
):
    """Save the stream to a given folder, then unpack."""
    archive_path = _write_stream_to_tmp_file(stream)
    _extract_archive_to_folder(archive_path, results_folder)
    archive_path.unlink()


# -----------------------------
# Rich renderers
# -----------------------------
def _status_panel(status: QiboJobStatus) -> Panel:
    title_map = {
        # QiboJobStatus.QUEUEING: "[bold yellow]Job QUEUEING[/]",
        QiboJobStatus.PENDING: "[bold cyan]Job PENDING[/]",
        QiboJobStatus.RUNNING: "[bold green]Job RUNNING[/]",
        # QiboJobStatus.POSTPROCESSING: "[bold blue]Job POSTPROCESSING[/]",
    }
    body = Text.from_markup(title_map.get(status, f"[bold]{status.name}[/]"))
    return Panel(body, border_style="dim", box=box.ROUNDED)


def _pending_panel(
    queue_position: int | None, etd_seconds: int | float | None
) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row("[bold cyan]Job PENDING[/]", "")
    if queue_position is not None:
        table.add_row("Position in queue:", f"[bold]{queue_position}[/]")
    if etd_seconds is not None:
        table.add_row("Max ETD:", f"[bold]{format_hms(etd_seconds)}[/]")
    if queue_position is None and etd_seconds is None:
        table.add_row("", "[dim]waiting for queue info…[/]")
    return Panel(table, border_style="cyan", box=box.ROUNDED)


# -----------------------------
# QiboJob
# -----------------------------
class QiboJob:
    def __init__(
        self,
        pid: str,
        base_url: str = constants.BASE_URL,
        headers: T.Dict[str, str] | None = None,
        circuit: T.Optional[qibo.Circuit] = None,
        nshots: T.Optional[int] = None,
        device: T.Optional[str] = None,
    ):
        self.base_url = base_url
        self.headers = headers
        self.pid = pid
        self.circuit = circuit
        self.nshots = nshots
        self.device = device

        self._status: T.Optional[QiboJobStatus] = None
        # convenience fields (populated on refresh/status)
        self.queue_position: T.Optional[int] = None
        self.seconds_to_job_start: T.Optional[int | float] = None
        self.queue_last_update: T.Optional[str] = None

    # ---- server I/O ----
    def _snapshot(self) -> T.Dict:
        """Fetch current job snapshot from the webapp."""
        url = self.base_url + f"/api/jobs/{self.pid}/"
        resp = QiboApiRequest.get(
            url,
            headers=self.headers,
            timeout=constants.TIMEOUT,
            keys_to_check=["status"],
        )
        return resp.json()

    def refresh(self):
        """Refreshes job information from server (no results download)."""
        info = self._snapshot()
        if info:
            self._update_job_info(info)

    def _update_job_info(self, info: T.Dict):
        self.circuit = info.get("circuit")
        self.nshots = info.get("nshots")
        pq = info.get("projectquota") or {}
        part = pq.get("partition") or {}
        self.device = part.get("name", self.device)
        self._status = convert_str_to_job_status(info["status"])

        # live queue info
        self.queue_position = info.get("queue_position")
        self.seconds_to_job_start = info.get("etd_seconds")
        self.queue_last_update = info.get("queue_last_update")

    # ---- convenience ----
    def status(self) -> QiboJobStatus:
        info = self._snapshot()
        self._status = convert_str_to_job_status(info["status"])
        self.queue_position = info.get("queue_position", info.get("job_queue_position"))
        self.seconds_to_job_start = info.get(
            "etd_seconds", info.get("seconds_to_job_start")
        )
        self.queue_last_update = info.get("queue_last_update")
        return self._status

    def running(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.RUNNING

    def success(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.SUCCESS

    # ---- main wait loop ----
    def result(
        self, wait: int = 5, verbose: bool = False
    ) -> T.Optional[qibo.result.QuantumState]:
        """Poll server until completion, then download and return result."""
        response, job_status = self._wait_for_response_to_get_request(wait, verbose)

        # create the job results folder
        self.results_folder = constants.RESULTS_BASE_FOLDER / self.pid
        self.results_folder.mkdir(parents=True, exist_ok=True)

        # Save the stream to disk
        try:
            _save_and_unpack_stream_response_to_folder(
                response.iter_content(), self.results_folder
            )
        except tarfile.ReadError as err:
            logger.error("Catched tarfile ReadError: %s", err)
            logger.error(
                "The received file is not a valid gzip archive, the result might "
                "have to be inspected manually. Find the file at `%s`",
                self.results_folder.as_posix(),
            )
            return None

        if job_status == QiboJobStatus.ERROR:
            out_log_path = self.results_folder / "stdout.log"
            stdout = out_log_path.read_text() if out_log_path.is_file() else "-"
            err_log_path = self.results_folder / "stderr.log"
            stderr = err_log_path.read_text() if err_log_path.is_file() else "-"
            logger.error(
                "Job exited with error\n\nStdout:\n%s\n\nStderr:\n%s", stdout, stderr
            )
            return None

        self.results_path = self.results_folder / "results.npy"
        return qibo.result.load_result(self.results_path)

    def _wait_for_response_to_get_request(
        self, seconds_between_checks: T.Optional[int] = None, verbose: bool = False
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        is_job_unfinished = self.status() not in [
            QiboJobStatus.SUCCESS,
            QiboJobStatus.ERROR,
        ]
        if not verbose and is_job_unfinished:
            logger.info("Please wait until your job is completed...")

        url = self.base_url + f"/api/jobs/{self.pid}/"

        use_live = verbose and console.is_terminal

        def _render(status: QiboJobStatus, qpos, etd):
            if status == QiboJobStatus.PENDING:
                return _pending_panel(qpos, etd)
            elif status in (QiboJobStatus.QUEUEING, QiboJobStatus.RUNNING):
                return _status_panel(status)
            # do not render POSTPROCESSING
            elif status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                return Panel(
                    f"[bold]{status.name}[/]",
                    border_style="green" if status == QiboJobStatus.SUCCESS else "red",
                )
            return None

        if use_live:
            snap = QiboApiRequest.get(
                url, headers=self.headers, timeout=constants.TIMEOUT
            ).json()
            status0 = convert_str_to_job_status(snap["status"])
            qpos0 = snap.get("queue_position", snap.get("job_queue_position"))
            etd0 = snap.get("etd_seconds", snap.get("seconds_to_job_start"))

            with Live(_render(status0, qpos0, etd0), refresh_per_second=6, console=console, transient=False) as live:
                last_renderable = _render(status0, qpos0, etd0)
                if last_renderable is not None:
                    live.update(last_renderable)

                while True:
                    response = QiboApiRequest.get(url, headers=self.headers, timeout=constants.TIMEOUT)
                    payload = response.json()
                    job_status = convert_str_to_job_status(payload["status"])
                    qpos = payload.get("queue_position", payload.get("job_queue_position"))
                    etd = payload.get("etd_seconds", payload.get("seconds_to_job_start"))

                    renderable = _render(job_status, qpos, etd)
                    if renderable is not None:
                        live.update(renderable)
                        last_renderable = renderable  # keep for reference
                    # else: POSTPROCESSING — do nothing, leaving previous panel visible

                    if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                        console.print("[bold]Job COMPLETED[/]")  # no filename/line
                        response = QiboApiRequest.get(
                            self.base_url + f"/api/jobs/{self.pid}/download/",
                            headers=self.headers,
                            timeout=constants.TIMEOUT,
                        )
                        return response, job_status

                    time.sleep(seconds_between_checks)
