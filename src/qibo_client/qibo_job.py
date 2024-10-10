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


def convert_str_to_job_status(status: str):
    return next((s for s in QiboJobStatus if s.value == status), None)


class QiboJobStatus(Enum):
    QUEUED = "to_do"
    RUNNING = "in_progress"
    DONE = "success"
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
        circuit: T.Optional[qibo.Circuit] = None,
        nshots: T.Optional[int] = None,
        device: T.Optional[str] = None,
    ):
        self.base_url = base_url
        self.pid = pid
        self.circuit = circuit
        self.nshots = nshots
        self.device = device

        self._status = None

    def refresh(self):
        """Refreshes job information from server.

        This method does not query the results from server.
        """
        url = self.base_url + f"/job/info/{self.pid}/"
        response = response = QiboApiRequest.get(
            url,
            timeout=constants.TIMEOUT,
            keys_to_check=["circuit", "nshots", "device", "status"],
        )

        info = response.json()
        if info is not None:
            self._update_job_info(info)

    def _update_job_info(self, info: T.Dict):
        self.circuit = info.get("circuit")
        self.nshots = info.get("nshots")
        self.device = info["device"].get("name")
        self._status = convert_str_to_job_status(info["status"])

    def status(self) -> QiboJobStatus:
        url = self.base_url + f"/job/info/{self.pid}/"
        response = QiboApiRequest.get(
            url, timeout=constants.TIMEOUT, keys_to_check=["status"]
        )
        status = response.json()["status"]
        self._status = convert_str_to_job_status(status)
        return self._status

    def running(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.RUNNING

    def done(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.DONE

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
            logger.info(
                "Job exited with error, check logs in %s folder",
                self.results_folder.as_posix(),
            )
            return None

        self.results_path = self.results_folder / "results.npy"
        return qibo.result.load_result(self.results_path)

    def _wait_for_response_to_get_request(
        self, seconds_between_checks: T.Optional[int] = None, verbose: bool = False
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        """Wait until the server completes the computation and return the response.

        :param url: the endpoint to make the request
        :type url: str

        :return: the response of the get request
        :rtype: requests.Response
        :return: the completed job response status
        :rtype: QiboJobStatus
        """
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        is_job_finished = self.status() not in [QiboJobStatus.DONE, QiboJobStatus.ERROR]
        if not verbose and is_job_finished:
            logger.info("Please wait until your job is completed...")

        url = self.base_url + f"/job/result/{self.pid}/"

        while True:
            response = QiboApiRequest.get(url, timeout=constants.TIMEOUT)
            job_status = convert_str_to_job_status(response.headers["Job-Status"])
            if verbose and job_status == QiboJobStatus.QUEUED:
                logger.info("Job QUEUING")
            if verbose and job_status == QiboJobStatus.RUNNING:
                logger.info("Job RUNNING")
            if job_status in [QiboJobStatus.DONE, QiboJobStatus.ERROR]:
                if verbose:
                    logger.info("Job COMPLETED")
                return response, job_status
            time.sleep(seconds_between_checks)
