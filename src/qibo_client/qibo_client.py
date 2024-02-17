"""The module implementing the TIIProvider class."""

import logging
import os
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np
import qibo
import requests

from .config import JobPostServerError, MalformedResponseError

RESULTS_BASE_FOLDER = os.environ.get("RESULTS_BASE_FOLDER", "/tmp/qibo_client")
SECONDS_BETWEEN_CHECKS = os.environ.get("SECONDS_BETWEEN_CHECKS", 2)

RESULTS_BASE_FOLDER = Path(RESULTS_BASE_FOLDER)
RESULTS_BASE_FOLDER.mkdir(exist_ok=True)

TIMEOUT = 10


# configure logger
logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
LOGGING_LEVEL = logging.INFO
logger.setLevel(LOGGING_LEVEL)


def wait_for_response_to_get_request(url: str) -> requests.models.Response:
    """Wait until the server completes the computation and return the response.

    :param url: the endpoint to make the request
    :type url: str

    :return: the response of the get request
    :rtype: requests.models.Response
    """
    while True:
        response = requests.get(url, timeout=TIMEOUT)
        if response.content == b"Job still in progress":
            time.sleep(SECONDS_BETWEEN_CHECKS)
            continue
        return response


def _write_stream_to_tmp_file(stream: Iterable) -> Path:
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


def _save_and_unpack_stream_response_to_folder(stream: Iterable, results_folder: Path):
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


def check_response_has_keys(response: requests.models.Response, keys: List[str]):
    """Check that the response body contains certain keys.

    :param response: the server response
    :type response: requests.models.Response
    :param keys: the keys to be checked in the response body
    :type keys: List[str]

    :raises MalformedResponseError:
        if the server response does not contain all the expected keys.
    """
    response_keys = set(response.json().keys())
    expected_keys = set(keys)
    missing_keys = expected_keys.difference(response_keys)

    if len(missing_keys):
        raise MalformedResponseError(
            f"The server response is missing the following keys: {' '.join(missing_keys)}"
        )


class Client:
    """Class to manage the interaction with the QRC cluster."""

    def __init__(self, url: str, token: str):
        """
        :param url: the server address
        :type url: str
        :param token: the authentication token associated to the webapp user
        :type token: str
        """
        self.url = url
        self.token = token

        self.pid = None
        self.results_folder = None
        self.results_path = None

        self.check_client_server_qibo_versions()

    def check_client_server_qibo_versions(self):
        """Check that client and server qibo package installed versions match.

        Raise assertion error if the two versions are not the same.
        """
        url = self.url + "qibo_version/"
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        check_response_has_keys(response, ["qibo_version"])
        qibo_server_version = response.json()["qibo_version"]
        qibo_local_version = qibo.__version__

        msg = (
            "Local Qibo package version does not match the server one, please "
            f"upgrade: {qibo_local_version} -> {qibo_server_version}"
        )
        assert qibo_local_version == qibo_server_version, msg

    def run_circuit(
        self, circuit: qibo.Circuit, nshots: int = 1000, device: str = "sim"
    ) -> Optional[np.ndarray]:
        """Run circuit on the cluster.

        :param circuit: the QASM representation of the circuit to run
        :type circuit: Circuit
        :param nshots: number of shots
        :type nshots: int
        :param device: the device to run the circuit on. Default device is `sim`
        :type device: str

        :return:
            the numpy array with the results of the computation. None if the job
            raised an error.
        :rtype: np.ndarray
        """
        # post circuit to server
        logger.info("Post new circuit on the server")

        try:
            self._post_circuit(circuit, nshots, device)
        except JobPostServerError as err:
            logger.error(err.message)
            return None

        # retrieve results
        logger.info("Job posted on server with pid %s", self.pid)
        logger.info("Check results every %d seconds ...", SECONDS_BETWEEN_CHECKS)
        result = self._get_result()

        return result

    def _post_circuit(
        self, circuit: qibo.Circuit, nshots: int = 100, device: str = "sim"
    ):
        # HTTP request
        url = self.url + "run_circuit/"
        payload = {
            "token": self.token,
            "circuit": circuit.raw,
            "nshots": nshots,
            "device": device,
        }
        response = requests.post(url, json=payload, timeout=TIMEOUT)

        # checks
        response.raise_for_status()
        check_response_has_keys(response, ["pid", "message"])

        # save the response
        response_content = response.json()
        self.pid = response_content["pid"]

        if self.pid is None:
            raise JobPostServerError(response_content["message"])

    def _get_result(self) -> Optional[np.ndarray]:
        """Send requests to server checking whether the job is completed.

        This function populates the `TIIProvider.results_folder` and
        `TIIProvider.results_path` attributes.

        :return: the numpy array with the results of the computation. None if
        the job raised an error.
        :rtype: Optional[np.ndarray]
        """
        url = self.url + f"get_result/{self.pid}/"
        response = wait_for_response_to_get_request(url)

        # create the job results folder
        self.results_folder = RESULTS_BASE_FOLDER / self.pid
        self.results_folder.mkdir(exist_ok=True)

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

        if response.headers["Job-Status"].lower() == "error":
            logger.info(
                "Job exited with error, check logs in %s folder",
                self.results_folder.as_posix(),
            )
            return None

        self.results_path = self.results_folder / "results.npy"
        return qibo.result.load_result(self.results_path)
