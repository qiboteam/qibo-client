"""Core QiboJob class and related helpers.

This module implements the main job class for interacting with Qibo quantum computing
framework services, including job submission, monitoring, and result retrieval.
"""

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
    """Enumeration of possible job statuses.

    These represent the lifecycle stages a job can go through
    from submission to completion.
    """

    QUEUEING = auto()
    """Job is in the queue waiting for resources"""
    PENDING = auto()
    """Job is pending execution"""
    RUNNING = auto()
    """Job is actively running"""
    POSTPROCESSING = auto()
    """Job is being post-processed (results being generated)"""
    SUCCESS = auto()
    """Job completed successfully"""
    ERROR = auto()
    """Job failed with an error"""


def convert_str_to_job_status(status: str) -> T.Optional[QiboJobStatus]:
    """Convert a string to the corresponding QiboJobStatus enum.

    Args:
        status: String representation of job status

    Returns:
        QiboJobStatus enum value if successful, None if not recognized
    """
    try:
        return QiboJobStatus[status.upper()]
    except (KeyError, AttributeError):
        return None


def _write_stream_to_tmp_file(stream: T.Iterable) -> Path:
    """Write chunk of bytes to a temporary file.

    This function streams data to a temporary file for safe handling
    and subsequent archive processing.

    Args:
        stream: Iterator yielding byte chunks

    Returns:
        Path to the created temporary file
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        for chunk in stream:
            if chunk:
                tmp_file.write(chunk)
        archive_path = tmp_file.name
    return Path(archive_path)


def _extract_archive_to_folder(source_archive: Path, destination_folder: Path):
    """Extract a tar.gz archive to a destination folder.

    Handles both modern and legacy tarfile.extractall API versions.

    Args:
        source_archive: Path to the archive file to extract
        destination_folder: Path to destination directory
    """
    with tarfile.open(source_archive, "r:gz") as archive:
        try:
            archive.extractall(destination_folder, filter="data")
        except TypeError:
            # Fall back to extractall without filter parameter for older Python versions
            archive.extractall(destination_folder)


def _save_and_unpack_stream_response_to_folder(
    stream: T.Iterable,
    results_folder: Path,
):
    """Save a stream response to a folder and extract its contents.

    Args:
        stream: The stream response containing archive data
        results_folder: The folder to save and extract results into
    """
    archive_path = _write_stream_to_tmp_file(stream)
    _extract_archive_to_folder(archive_path, results_folder)
    archive_path.unlink()


class QiboJob:
    """Job object representing a Qibo quantum computing job.

    This class manages the lifecycle of a quantum computing job,
    including status polling, result retrieval, and cleanup.

    Attributes:
        base_url: The API base URL for the server
        headers: Headers to include in API requests
        pid: Process ID identifying this job
        circuit: Circuit JSON representation
        nshots: Number of measurements/shots
        device: Device being used for execution
        project: Project name for this job
        _status: Current job status (queued to completion)
        queue_position: Current position in execution queue
        seconds_to_job_start: Estimated seconds until job starts
        queue_last_update: Last time queue status was updated
        results_folder: Folder where results are stored
        results_path: Path to the results file
    """

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
        """Initialize a QiboJob instance.

        Args:
            pid: Process ID of the job
            base_url: API base URL for the server
            headers: Optional headers including authentication token
            circuit: Optional circuit JSON representation
            nshots: Optional number of shots for quantum measurements
            device: Optional device identifier for execution
            project: Optional project name
        """
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

        # Results storage
        self.results_folder: T.Optional[Path] = None
        self.results_path: T.Optional[Path] = None

    def refresh(self) -> QiboJobStatus:
        """Refresh job information from the server.

        Retrieves current job details including status, queue position,
        and estimated time-to-start. Updates the job object in place.

        Returns:
            The current QiboJobStatus enum value
        """
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
        """Get the current job status.

        This is a convenience method that delegates to refresh().

        Returns:
            The current QiboJobStatus enum value
        """
        return self.refresh()

    def running(self) -> bool:
        """Check if the job is currently running.

        Returns:
            True if job status is RUNNING, False otherwise
        """
        return self.status() is QiboJobStatus.RUNNING

    def success(self) -> bool:
        """Check if the job completed successfully.

        Returns:
            True if job status is SUCCESS, False otherwise
        """
        return self.status() is QiboJobStatus.SUCCESS

    def result(
        self, wait: float = 0.5, verbose: bool = True
    ) -> T.Optional[qibo.result.QuantumState]:
        """Poll server until completion, then download and return result.

        This method continuously polls the job status until completion
        and then downloads and extracts the results archive.

        Args:
            wait: Seconds between status checks
            verbose: Whether to display status updates

        Returns:
            qibo.result.QuantumState if successful, None if job failed or download failed
        """
        response, job_status = self._wait_for_response_to_get_request(wait, verbose)

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
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        """Wait for job to complete by polling status.

        This method chooses the appropriate waiting strategy based on
        whether Rich UI is available and whether verbose output is enabled.

        Args:
            seconds_between_checks: Interval between status checks
            verbose: Whether to show status updates

        Returns:
            Tuple of (download_response, final_status)
        """
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        use_live = verbose and USE_RICH_UI
        self.refresh()

        if use_live:
            return self._wait_live(seconds_between_checks)

        return self._wait_non_live(seconds_between_checks, verbose)

    def _wait_live(self, interval: float):
        """Wait for job completion with live Rich UI updates.

        Args:
            interval: Seconds between status checks
        """
        elapsed_timer = ElapsedTimer()
        ui = UISlots(order=("header", "status", "footer"))
        ui.set(
            "status",
            build_status_panel(
                "LOADING",
                self.queue_position,
                self.seconds_to_job_start,
                provider=self.base_url,
                version=version,
                pid=self.pid,
                device=self.device,
                project=self.project,
            ),
        )

        outer = LiveOuter("job status", version, ui, elapsed_timer=elapsed_timer)

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
                            provider=self.base_url,
                            version=version,
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
                            provider=self.base_url,
                            version=version,
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
        """Wait for job completion with non-live, non-verbose output.

        Args:
            interval: Seconds between status checks
            verbose: Whether to show status updates
        """
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
        """Delete a job from the server.

        Returns:
            The server response after deletion attempt
        """
        url = self.base_url + f"/api/jobs/{self.pid}/"
        return QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        )
