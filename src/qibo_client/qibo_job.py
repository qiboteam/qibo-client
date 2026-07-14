"""Core QiboJob class and related helpers.

This module implements the main job class for interacting with Qibo quantum computing
framework services, including job submission, monitoring, and result retrieval.
"""

import importlib.metadata as im
import time
import typing as T
from enum import Enum, auto

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
        frequencies: Measurement frequencies histogram returned by the server
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

        # Frequencies dict returned by the server (populated on refresh()).
        self.frequencies: T.Optional[dict] = None

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
        self.frequencies = info.get("frequencies", self.frequencies)

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
    ) -> T.Optional[qibo.result.MeasurementOutcomes]:
        """Poll until completion, then rebuild the result from frequencies.

        As of v0.3.0 the server transfers only the measurement frequencies
        (a JSON histogram), not the full numpy array. The result object is
        reconstructed locally via ``MeasurementOutcomes.from_frequencies``.

        Args:
            wait: Seconds between status checks
            verbose: Whether to display status updates

        Returns:
            qibo.result.MeasurementOutcomes if successful, else None
        """
        job_status = self._wait_for_completion(wait, verbose)

        if job_status == QiboJobStatus.ERROR:
            logger.error("Job %s exited with error.", self.pid)
            return None

        if not self.frequencies:
            logger.error(
                "Job %s returned no frequencies; nothing to reconstruct.", self.pid
            )
            return None

        circuit = qibo.Circuit.from_dict(self.circuit)
        nqubits = sum(len(m.qubits) for m in circuit.measurements)
        return qibo.result.MeasurementOutcomes.from_frequencies(
            self.frequencies, nqubits=nqubits
        )

    def _wait_for_completion(
        self,
        seconds_between_checks: T.Optional[float] = None,
        verbose: bool = True,
    ) -> QiboJobStatus:
        """Wait for job to complete by polling status.

        This method chooses the appropriate waiting strategy based on
        whether Rich UI is available and whether verbose output is enabled.

        Args:
            seconds_between_checks: Interval between status checks
            verbose: Whether to show status updates

        Returns:
            The final QiboJobStatus enum value
        """
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        use_live = verbose and USE_RICH_UI
        self.refresh()

        if use_live:
            return self._wait_live(seconds_between_checks)

        return self._wait_non_live(seconds_between_checks, verbose)

    def _wait_live(self, interval: float) -> QiboJobStatus:
        """Wait for job completion with live Rich UI updates.

        Args:
            interval: Seconds between status checks

        Returns:
            The final QiboJobStatus enum value
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
                    return status

                live.refresh()
                time.sleep(interval)

    def _wait_non_live(self, interval: float, verbose: bool) -> QiboJobStatus:
        """Wait for job completion with non-live, non-verbose output.

        Args:
            interval: Seconds between status checks
            verbose: Whether to show status updates

        Returns:
            The final QiboJobStatus enum value
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
                return self._status

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
