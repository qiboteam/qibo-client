import tarfile
import tempfile
import time
import typing as T
from enum import Enum
from pathlib import Path

import qibo
import requests

from . import constants
from .config_logging import logger
from .utils import QiboApiRequest


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
    """Write chunk of bytes to temporary file.

    The tmp_path should be closed manually.

    :param stream: the stream of bytes chunks to be saved on disk
    :type stream: Iterable

    :return: the name of the tempo

    """
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
    """Save the stream to a given folder.

    Internally, save the stream to a temporary archive and extract its contents
    to the target folder.

    :param stream: the iterator containing the response content
    :type stream: Iterable
    :param results_folder: the local path to the results folder
    :type results_folder: Path
    """
    archive_path = _write_stream_to_tmp_file(stream)

    _extract_archive_to_folder(archive_path, results_folder)

    # clean up temporary file
    archive_path.unlink()


class QiboJob:
    def __init__(
        self,
        pid: str,
        base_url: str = constants.BASE_URL,
        headers: T.Dict[str, str] = None,
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

        self._status = None

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
        # keep working even if BE omits nested project info
        pq = info.get("projectquota") or {}
        part = pq.get("partition") or {}
        self.device = part.get("name", self.device)
        self._status = convert_str_to_job_status(info["status"])

        # Expose live queue info on the object for convenience
        self.queue_position = info.get("queue_position")
        self.seconds_to_job_start = info.get("etd_seconds")
        self.queue_last_update = info.get("queue_last_update")

    def status(self) -> QiboJobStatus:
        info = self._snapshot()
        self._status = convert_str_to_job_status(info["status"])
        # keep queue fields in sync when caller asks status()
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

    def result(
        self, wait: int = 5, verbose: bool = False
    ) -> T.Optional[qibo.result.QuantumState]:
        """Send requests to server checking whether the job is completed.

        This function populates the `Client.results_folder` and
        `Client.results_path` attributes.

        :return: the numpy array with the results of the computation.
                 None if the job raised an error.
        :rtype: T.Optional[np.ndarray]
        """
        # @TODO: here we can use custom logger levels instead of if statement
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
                "The received file is not a valid gzip "
                "archive, the result might have to be inspected manually. Find "
                "the file at `%s`",
                self.results_folder.as_posix(),
            )
            return None

        if job_status == QiboJobStatus.ERROR:
            out_log_path = self.results_folder / "stdout.log"
            stdout = out_log_path.read_text() if out_log_path.is_file() else "-"

            err_log_path = self.results_folder / "stderr.log"
            stderr = err_log_path.read_text() if err_log_path.is_file() else "-"

            logger.error(
                "Job exited with error\n\nStdout:\n%s\n\nStderr:\n%s",
                stdout,
                stderr,
            )

            return None

        self.results_path = self.results_folder / "results.npy"
        return qibo.result.load_result(self.results_path)

    def _wait_for_response_to_get_request(
        self, seconds_between_checks: T.Optional[int] = None, verbose: bool = False
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        """Wait until the server completes the computation and return the response."""

        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        # Initial notice if not verbose
        is_job_unfinished = self.status() not in [QiboJobStatus.SUCCESS, QiboJobStatus.ERROR]
        if not verbose and is_job_unfinished:
            logger.info("Please wait until your job is completed...")

        url = self.base_url + f"/api/jobs/{self.pid}/"

        # Track the last thing we logged so we don’t spam duplicates
        last_status: T.Optional[QiboJobStatus] = None
        last_qpos: T.Optional[int] = None
        last_etd: T.Optional[int] = None  # seconds

        while True:
            response = QiboApiRequest.get(
                url, headers=self.headers, timeout=constants.TIMEOUT
            )
            payload = response.json()
            job_status = convert_str_to_job_status(payload["status"])

            # Pull live queue info (new fields first, fallback to legacy)
            qpos = payload.get("queue_position", payload.get("job_queue_position"))
            etd = payload.get("etd_seconds", payload.get("seconds_to_job_start"))

            # ——— Logging logic (only on change) ———
            if verbose:
                if job_status != last_status:
                    # entering a new status: log once
                    if job_status == QiboJobStatus.QUEUEING:
                        logger.info("Job QUEUEING")
                    elif job_status == QiboJobStatus.PENDING:
                        if qpos is not None:
                            logger.info(
                                "Job PENDING -> position in queue: %d, max ETD: %s",
                                qpos, format_hms(etd),
                            )
                        else:
                            logger.info("Job PENDING")
                    elif job_status == QiboJobStatus.RUNNING:
                        logger.info("Job RUNNING")
                    elif job_status == QiboJobStatus.POSTPROCESSING:
                        logger.info("Job POSTPROCESSING")
                    # update trackers on status change
                    last_status = job_status
                    last_qpos = qpos
                    last_etd = etd
                else:
                    # same status as before — only log if the meaningful info changed
                    if job_status == QiboJobStatus.PENDING:
                        if qpos != last_qpos or (etd != last_etd):
                            if qpos is not None:
                                logger.info(
                                    "Job PENDING -> position in queue: %d, max ETD: %s",
                                    qpos, format_hms(etd),
                                )
                            else:
                                logger.info("Job PENDING")
                            last_qpos = qpos
                            last_etd = etd
                    # For RUNNING/QUEUEING/POSTPROCESSING we intentionally stay quiet
                    # until the status changes, to avoid duplicate lines.

            # ——— Completion ———
            if job_status in [QiboJobStatus.SUCCESS, QiboJobStatus.ERROR]:
                if verbose:
                    logger.info("Job COMPLETED")
                response = QiboApiRequest.get(
                    self.base_url + f"/api/jobs/{self.pid}/download/",
                    headers=self.headers,
                    timeout=constants.TIMEOUT,
                )
                return response, job_status

            time.sleep(seconds_between_checks)