import time
from typing import Dict

import numpy as np
from qibo import Circuit
import requests


QRCCLUSTER_IP = "localhost"
QRCCLUSTER_PORT = "8010"

BASE_URL = f"http://{QRCCLUSTER_IP}:{QRCCLUSTER_PORT}/"


class QiboTiiProvider:
    """Class to manage the interaction with the QRC cluster."""

    def __init__(self, token: str):
        """
        :param token: the authentication token associated to the webapp user
        :type: str
        """
        self.token = token

    def run_circuit(
        self, circuit: Circuit, nshots: int = 100, device: str = "tiiq"
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
        payload = {
            "token": self.token,
            "circuit": circuit.to_qasm(),
            "nshots": nshots,
            "device": device,
        }
        url = BASE_URL + "run_circuit/"

        try:
            # Send an HTTP request to the server
            response = requests.post(url, json=payload)

            # the response should contain the PID to be checked (in the db, store
            # an hashed version of the pid, not the actual value)

            # Check the response
            if response.status_code == 200:
                self.pid = response.content["pid"]
                return response.content
            else:
                return {"error": "Failed to send the request to the server"}

        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}

    def get_result(self, pid: str) -> np.ndarray:
        """Send requests to server checking whether the job is completed."""
        url = BASE_URL + f"get_result/{pid}"
        while True:
            print("Job not finished, waiting 60s more...")
            time.sleep(60)
            response = requests.get(url)

            if response.content["message"] == "Job not finished yet":
                continue

            print(response.content["message"])
            self.result_path = response.content["result_path"]
            break
