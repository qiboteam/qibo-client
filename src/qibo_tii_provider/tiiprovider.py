import json
from pathlib import Path
import tarfile
import tempfile
import time
from typing import Iterable, Optional
import os

import numpy as np
import qibo
import requests


QRCCLUSTER_IP=os.environ.get("QRCCLUSTER_IP", "login.qrccluster.com")
QRCCLUSTER_PORT=os.environ.get("QRCCLUSTER_PORT", "8010")
RESULTS_BASE_FOLDER=os.environ.get("RESULTS_BASE_FOLDER", "/tmp/qibo_tii_provider")
SECONDS_BETWEEN_CHECKS=os.environ.get("SECONDS_BETWEEN_CHECKS", 2)

BASE_URL = f"http://{QRCCLUSTER_IP}:{QRCCLUSTER_PORT}/"

RESULTS_BASE_FOLDER = Path(RESULTS_BASE_FOLDER)
RESULTS_BASE_FOLDER.mkdir(exist_ok=True)

SECONDS_BETWEEN_CHECKS = SECONDS_BETWEEN_CHECKS


def _write_stream_response_to_folder(stream: Iterable, results_folder: Path):
    """Save the stream to a given folder.

    Internally, save the stream to a temporary archive and extract its contents
    to the target folder.

    :param stream: the iterator containing the response content
    :type stream: Iterable
    :param results_folder: the local path to the results folder
    :type results_folder: Path
    """
    # save archive to tempfile
    with tempfile.NamedTemporaryFile(delete=False) as archive:
        for chunk in stream:
            if chunk:
                archive.write(chunk)
        archive_path = archive.name

    # extract archive content to target directory
    with tarfile.open(archive_path, "r") as archive:
        archive.extractall(results_folder)

    os.remove(archive_path)


class TIIProvider:
    """Class to manage the interaction with the QRC cluster."""

    def __init__(self, token: str):
        """
        :param token: the authentication token associated to the webapp user
        :type: str
        """
        self.token = token

        self.check_client_server_qibo_versions()

    def check_client_server_qibo_versions(self):
        """Check that client and server qibo package installed versions match.

        Raise assertion error if the two versions are not the same.
        """
        url = BASE_URL + "qibo_version/"
        response = requests.get(url)
        assert (
            response.status_code == 200
        ), f"Failed to send the request to the server, response {response.status_code}"
        qibo_server_version = json.loads(response.content)["qibo_version"]
        qibo_local_version = qibo.__version__

        assert (
            qibo_local_version == qibo_server_version
        ), f"Local Qibo package version does not match the server one, please upgrade: {qibo_local_version} -> {qibo_server_version}"

    def run_circuit(
        self, circuit: qibo.Circuit, nshots: int = 1000, device: str = "sim"
    ) -> Optional[np.ndarray]:
        """Run circuit on the cluster.

        List of available devices:

        - sim
        - iqm5q
        - spinq10q
        - tii1q_b1
        - qw25q_gold
        - tiidc
        - tii2q
        - tii2q1
        - tii2q2
        - tii2q3
        - tii2q4

        :param circuit: the QASM representation of the circuit to run
        :type circuit: Circuit
        :param nshots:
        :type nshots: int
        :param device: the device to run the circuit on. Default device is `sim`
        :type device: str

        :return: the numpy array with the results of the computation. None if
        the job raised an error.
        :rtype: np.ndarray
        """
        # post circuit to server
        print("Post new circuit on the server")
        self.__post_circuit(circuit, nshots, device)

        # retrieve results
        print(f"Job posted on server with pid {self.pid}")
        print(f"Check results every {SECONDS_BETWEEN_CHECKS} seconds ...")
        result =  self.__get_result()

        return result

    def __post_circuit(
        self, circuit: qibo.Circuit, nshots: int = 100, device: str = "sim"
    ):
        payload = {
            "token": self.token,
            "circuit": circuit.raw,
            "nshots": nshots,
            "device": device,
        }
        url = BASE_URL + "run_circuit/"

        # post circuit
        try:
            # Send an HTTP request to the server
            response = requests.post(url, json=payload)

            # the response should contain the PID to be checked (in the db, store
            # an hashed version of the pid, not the actual value)

            # Check the response
            if response.status_code == 200:
                response_content = json.loads(response.content)
                self.pid = response_content["pid"]
                return response_content["message"]
            else:
                return "Error. Failed to send the request to the server"

        except Exception as e:
            return f"Error. An error occurred: {str(e)}"

    def __get_result(self) -> Optional[np.ndarray]:
        """Send requests to server checking whether the job is completed.

        This function populates the `TIIProvider.result_folder` and
        `TIIProvider.result_path` attributes.

        :return: the numpy array with the results of the computation. None if
        the job raised an error.
        :rtype: Optional[np.ndarray]
        """
        url = BASE_URL + f"get_result/{self.pid}"
        while True:
            time.sleep(SECONDS_BETWEEN_CHECKS)
            response = requests.get(url)

            if response.content == b"Job still in progress":
                continue

            # create the job results folder
            self.result_folder = RESULTS_BASE_FOLDER / self.pid
            self.result_folder.mkdir(exist_ok=True)

            # Save the stream to disk
            _write_stream_response_to_folder(
                response.iter_content(), self.result_folder
            )

            if response.headers["Job-Status"].lower() == "error":
                print(f"Job exited with error, check logs in {self.result_folder.as_posix()} folder")
                return None

            self.result_path = self.result_folder / "results.npy"
            return qibo.result.load_result(self.result_path)
