import importlib.metadata as im
import tarfile
import tempfile
import time
import typing as T
from enum import Enum
from pathlib import Path

import qibo
import requests
from rich.live import Live

version = im.version(__package__)

from . import constants
from .config_logging import logger
from .ui.job_frontend import (
    LiveOuter,
    UISlots,
    build_final_banner,
    build_status_panel,
    log_status_non_tty,
)
from .ui.settings import USE_RICH_UI, new_console, reset_console_live_state
from .utils import QiboApiRequest


# -----------------------------
# Helpers
# -----------------------------
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


def _animate_live_sleep(
    live: Live,
    duration: float,
    *,
    refresh_interval: float = 0.2,
) -> None:
    """Sleep for `duration` seconds while manually refreshing the Live view."""
    if duration <= 0:
        return

    end_ts = time.perf_counter() + duration
    while True:
        remaining = end_ts - time.perf_counter()
        if remaining <= 0:
            break

        try:
            live.refresh()
        except Exception:
            break

        time.sleep(min(refresh_interval, remaining))


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

        self._preamble: T.Optional[object] = None

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
        self, wait: float = 0.5, verbose: bool = True
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
        self, seconds_between_checks: T.Optional[int] = None, verbose: bool = True
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        """Poll the job until completion; return (download_response, final_status)."""
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS
        seconds_between_checks = float(seconds_between_checks)

        # Gentle hint when not verbose
        is_job_unfinished = self.status() not in (
            QiboJobStatus.SUCCESS,
            QiboJobStatus.ERROR,
        )
        if not verbose and is_job_unfinished:
            logger.info("Please wait until your job is completed...")

        url = self.base_url + f"/api/jobs/{self.pid}/"
        # Only show Rich Live in an interactive TTY or Jupyter with ipywidgets.
        use_live = verbose and USE_RICH_UI

        # Render policy: don't update during POSTPROCESSING so previous panel stays visible
        def _render(status: QiboJobStatus, qpos, etd):
            if status == QiboJobStatus.POSTPROCESSING:
                return None
            return build_status_panel(status.name, qpos, etd)

        # Small wrapper to fetch status + live fields
        def _fetch_snapshot() -> (
            tuple[QiboJobStatus, T.Optional[int], T.Optional[int | float]]
        ):
            payload = QiboApiRequest.get(
                url, headers=self.headers, timeout=constants.TIMEOUT
            ).json()
            status = convert_str_to_job_status(payload["status"])
            qpos = payload.get("queue_position", payload.get("job_queue_position"))
            etd = payload.get("etd_seconds", payload.get("seconds_to_job_start"))
            return status, qpos, etd

        # --- Live (TTY) branch ---
        if use_live:
            status0, qpos0, etd0 = _fetch_snapshot()

            # Compose a single renderable from named slots.
            # You can add more slots later (e.g., "header", "footer") without changing Live plumbing.
            ui = UISlots(order=("header", "status", "footer"))
            title = f"Qibo client version {version}"
            ui.set("header", self._preamble)
            ui.set("status", build_status_panel(status0.name, qpos0, etd0))

            outer = LiveOuter(title, ui)
            live_console = new_console()
            reset_console_live_state(live_console)

            with Live(
                outer,
                refresh_per_second=12,
                console=live_console,
                transient=False,
                vertical_overflow="visible",
            ) as live:
                start_ts = time.perf_counter()
                while True:
                    job_status, qpos, etd = _fetch_snapshot()

                    renderable = _render(job_status, qpos, etd)
                    if renderable is not None:
                        # Swap the status slot in place
                        ui.set("status", renderable)
                        live.refresh()

                    if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                        elapsed = time.perf_counter() - start_ts

                        # Download first so that the final banner is the *last* thing shown
                        response = QiboApiRequest.get(
                            self.base_url + f"/api/jobs/{self.pid}/download/",
                            headers=self.headers,
                            timeout=constants.TIMEOUT,
                        )

                        # Replace the status slot with a compact final banner
                        ui.set(
                            "status",
                            build_final_banner(
                                job_status.name,
                                pid=self.pid,
                                device=self.device,
                                elapsed_seconds=elapsed,
                            ),
                        )
                        live.refresh()
                        return response, job_status

                    _animate_live_sleep(live, float(seconds_between_checks))

        last_status: T.Optional[str] = None
        printed_pending_with_info = False

        if verbose and is_job_unfinished:
            logger.info("🚀 Starting qibo client...")
            logger.info("📬 Job posted on %s with pid, %s", self.device, self.pid)

        while True:
            job_status, qpos, etd = _fetch_snapshot()

            # controlled, non-spam logging (prints each status once; PENDING upgraded once)
            last_status, printed_pending_with_info = log_status_non_tty(
                verbose=verbose,
                last_status=last_status,
                printed_pending_with_info=printed_pending_with_info,
                job_status=job_status.name,
                qpos=qpos,
                etd=etd,
            )

            if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                if verbose:
                    logger.info("Job COMPLETED")
                response = QiboApiRequest.get(
                    self.base_url + f"/api/jobs/{self.pid}/download/",
                    headers=self.headers,
                    timeout=constants.TIMEOUT,
                )
                return response, job_status

            time.sleep(seconds_between_checks)

    def delete(self) -> str:
        url = self.base_url + f"/api/jobs/{self.pid}/"
        response = QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        )
        return response
