import importlib.metadata as im
import tarfile
import tempfile
import time
import typing as T
from enum import Enum, auto
from pathlib import Path

import qibo
import requests
from rich.live import Live

from . import constants
from .config_logging import logger
from .ui.job_frontend import (
    ElapsedTimer,
    LiveOuter,
    UISlots,
    build_final_banner,
    build_status_panel,
    log_status_non_tty,
)
from .ui.settings import USE_RICH_UI, console
from .utils import QiboApiRequest

version = im.version(__package__)


class QiboJobStatus(Enum):
    QUEUEING = auto()
    PENDING = auto()
    RUNNING = auto()
    POSTPROCESSING = auto()
    SUCCESS = auto()
    ERROR = auto()


def convert_str_to_job_status(status: str) -> T.Optional[QiboJobStatus]:
    try:
        return QiboJobStatus[status.upper()]
    except (KeyError, AttributeError):
        return None


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
        try:
            archive.extractall(destination_folder, filter="data")
        except TypeError:
            archive.extractall(destination_folder)


def _save_and_unpack_stream_response_to_folder(
    stream: T.Iterable, results_folder: Path
):
    """Save the stream to a given folder, then unpack."""
    archive_path = _write_stream_to_tmp_file(stream)
    _extract_archive_to_folder(archive_path, results_folder)
    archive_path.unlink()


class QiboJob:
    def __init__(
        self,
        pid: str,
        base_url: str,
        headers: T.Dict[str, str] | None = None,
        circuit: T.Optional[dict] = None,
        nshots: T.Optional[int] = None,
        device: T.Optional[str] = None,
        project: T.Optional[str] = None,
    ):
        self.base_url = base_url
        self.headers = headers
        self.pid = pid
        self.circuit = circuit
        self.nshots = nshots
        self.device = device
        self.project = project

        self._status: T.Optional[QiboJobStatus] = None
        self.queue_position: T.Optional[int] = None
        self.seconds_to_job_start: T.Optional[int | float] = None
        self.queue_last_update: T.Optional[str] = None

    def refresh(self) -> QiboJobStatus:
        """Refreshes job information from server."""
        url = self.base_url + f"/api/jobs/{self.pid}/"
        info = QiboApiRequest.get(
            url, headers=self.headers, timeout=constants.TIMEOUT
        ).json()

        self.circuit = info.get("circuit", self.circuit)
        self.nshots = info.get("nshots", self.nshots)
        pq = info.get("projectquota") or {}
        part = pq.get("partition") or {}
        self.device = part.get("name", self.device)
        self._status = convert_str_to_job_status(info["status"])

        self.queue_position = info.get("queue_position", info.get("job_queue_position"))
        self.seconds_to_job_start = info.get(
            "etd_seconds", info.get("seconds_to_job_start")
        )
        self.queue_last_update = info.get("queue_last_update")
        return self._status

    def status(self) -> QiboJobStatus:
        return self.refresh()

    def running(self) -> bool:
        return self.status() is QiboJobStatus.RUNNING

    def success(self) -> bool:
        return self.status() is QiboJobStatus.SUCCESS

    def result(
        self, wait: float = 0.5, verbose: bool = True, show_circuit: bool = False
    ) -> T.Optional[qibo.result.QuantumState]:
        """Poll server until completion, then download and return result."""
        response, job_status = self._wait_for_response_to_get_request(
            wait, verbose, show_circuit=show_circuit
        )

        self.results_folder = constants.RESULTS_BASE_FOLDER / self.pid
        self.results_folder.mkdir(parents=True, exist_ok=True)

        try:
            _save_and_unpack_stream_response_to_folder(
                response.iter_content(), self.results_folder
            )
        except tarfile.ReadError as err:
            logger.error("Tarfile ReadError: %s", err)
            return None

        if job_status == QiboJobStatus.ERROR:
            logger.error(
                "Job exited with error. Results folder: %s", self.results_folder
            )
            return None

        self.results_path = self.results_folder / "results.npy"
        return qibo.result.load_result(self.results_path)

    def _wait_for_response_to_get_request(
        self,
        seconds_between_checks: T.Optional[float] = None,
        verbose: bool = True,
        *,
        show_circuit: bool = False,
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        use_live = verbose and USE_RICH_UI
        status = self.refresh()

        if not verbose and status not in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
            logger.info("Please wait until your job is completed...")

        if use_live:
            return self._wait_live(seconds_between_checks, show_circuit)

        return self._wait_non_live(seconds_between_checks, verbose)

    def _wait_live(self, interval: float, show_circuit: bool):
        elapsed_timer = ElapsedTimer()
        ui = UISlots(order=("header", "status", "footer"))

        outer = LiveOuter(
            f"job status @ {self.base_url}",
            version,
            ui,
            elapsed_timer=elapsed_timer,
        )

        with Live(outer, console=console, vertical_overflow="visible") as live:
            while True:
                status = self.refresh()
                if status != QiboJobStatus.POSTPROCESSING:
                    ui.set(
                        "status",
                        build_status_panel(
                            status.name,
                            self.queue_position,
                            self.seconds_to_job_start,
                            pid=self.pid,
                            device=self.device,
                            project=self.project,
                        ),
                    )

                if status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                    resp = QiboApiRequest.get(
                        self.base_url + f"/api/jobs/{self.pid}/download/",
                        headers=self.headers,
                        timeout=constants.TIMEOUT,
                    )
                    ui.set(
                        "status",
                        build_final_banner(
                            status.name,
                            pid=self.pid,
                            device=self.device,
                            project=self.project,
                        ),
                    )
                    live.refresh()
                    return resp, status

                live.refresh()
                time.sleep(interval)

    def _wait_non_live(self, interval: float, verbose: bool):
        last_status, printed_pending = None, False
        if verbose:
            logger.info("> Job posted on %s with pid, %s", self.device, self.pid)

        while True:
            last_status, printed_pending = log_status_non_tty(
                verbose=verbose,
                last_status=last_status,
                printed_pending_with_info=printed_pending,
                job_status=self._status.name,
                qpos=self.queue_position,
                etd=self.seconds_to_job_start,
            )

            if self._status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                if verbose:
                    logger.info("Job COMPLETED")
                resp = QiboApiRequest.get(
                    self.base_url + f"/api/jobs/{self.pid}/download/",
                    headers=self.headers,
                    timeout=constants.TIMEOUT,
                )
                return resp, self._status

            time.sleep(interval)
            self.refresh()

    def delete(self) -> requests.Response:
        url = self.base_url + f"/api/jobs/{self.pid}/"
        return QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        )
