import json
from pathlib import Path
import tarfile
import tempfile
import time
from typing import Dict, Iterable
import os

import numpy as np
import qibo
import requests


QRCCLUSTER_IP = "login.qrccluster.com"
QRCCLUSTER_PORT = "8010"

BASE_URL = f"http://{QRCCLUSTER_IP}:{QRCCLUSTER_PORT}/"

RESULTS_BASE_FOLDER = Path("./results")
RESULTS_BASE_FOLDER.mkdir(exist_ok=True)


def __write_stream_response_to_folder(stream: Iterable, results_folder: Path):
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
    results_folder = Path(".")
    with tarfile.open(archive_path, "r") as archive:
        archive.extractall(results_folder)

    os.remove(archive_path)


class TiiQProvider:
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
        self, circuit: qibo.Circuit, nshots: int = 100, device: str = "sim"
    ) -> Dict:
        """Run circuit on the cluster.

        List of available devices:

        - sim
        - iqm5q
        - qw25q
        - tii1qs
        - tii_others
        - tii1q_b1
        - tii1q_b4
        - tii1q_b11
        - qw5q_gold

        :param circuit: the QASM representation of the circuit to run
        :type circuit: Circuit
        :param nshots:
        :type nshots: int
        :param device: the device to run the circuit on. Default device is `tiiq`
        :type device: str
        """
        # post circuit to server
        self.__post_circuit(circuit, nshots, device)

        # retrieve results
        self.__get_result()

    def __post_circuit(
        self, circuit: qibo.Circuit, nshots: int = 100, device: str = "sim"
    ):
        payload = {
            "token": self.token,
            "circuit": circuit.raw(),
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

    def __get_result(self) -> np.ndarray:
        """Send requests to server checking whether the job is completed."""
        url = BASE_URL + f"get_result/{self.pid}"
        while True:
            print("Job not finished, waiting 60s more...")
            time.sleep(60)
            response = requests.get(url)

            try:
                if response.content["message"] == "Job not finished yet":
                    continue
            except AttributeError as e:
                print("This exceptions should be correctly handled", e)
                pass

            # create the job results folder
            self.result_folder = RESULTS_BASE_FOLDER / self.pid
            self.result_folder.mkdir(exist_ok=True)

            # Save the stream to disk
            __write_stream_response_to_folder(
                response.stream_content(), self.result_folder
            )

            print("Result successfully retrieved")
            break
