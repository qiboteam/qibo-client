"""The module implementing the TIIProvider class."""


import qibo

from . import constants
from .config_logging import logger
from .exceptions import JobPostServerError
from .qibo_job import QiboJob, QiboJobResult
from .utils import QiboApiRequest


class Client:
    """Class to manage the interaction with the remote server."""

    def __init__(self, token: str, url: str = constants.BASE_URL):
        """
        :param token: the authentication token associated to the webapp user
        :type token: str
        :param url: the server address
        :type url: str
        """
        self.token = token
        self.base_url = url

        self.pid = None
        self.results_folder = None
        self.results_path = None

    def check_client_server_qibo_versions(self):
        """Check that client and server qibo package installed versions match.

        Raise assertion error if the two versions are not the same.
        """
        qibo_local_version = qibo.__version__
        msg = (
            "The qibo-client package requires an installed qibo package version"
            f">={constants.MINIMUM_QIBO_VERSION_ALLOWED}, the local qibo "
            f"version is {qibo_local_version}"
        )
        assert qibo_local_version >= constants.MINIMUM_QIBO_VERSION_ALLOWED, msg

        url = self.base_url + "/qibo_version/"
        response = QiboApiRequest.get(
            url, timeout=constants.TIMEOUT, keys_to_check=["qibo_version"]
        )
        qibo_server_version = response.json()["qibo_version"]

        if qibo_local_version < qibo_server_version:
            logger.warning(
                "Local Qibo package version does not match the server one, please "
                "upgrade: %s -> %s",
                qibo_local_version,
                qibo_server_version,
            )

    def run_circuit(
        self,
        circuit: qibo.Circuit,
        nshots: int = 1000,
        lab_location: str = "tii",
        device: str = "sim",
    ) -> QiboJobResult:
        """Run circuit on the cluster.

        :param circuit: the QASM representation of the circuit to run
        :type circuit: Circuit
        :param nshots: number of shots
        :type nshots: int
        :param device: the device to run the circuit on. Default device is `sim`
        :type device: str
        :param wait_for_results: wheter to let the client hang until server results are ready or not. Defaults to True.
        :type wait_for_results: bool

        :return:
            the numpy array with the results of the computation. None if the job
            raised an error.
        :rtype: Optional[QiboJobResult]
        """
        self.check_client_server_qibo_versions()

        logger.info("Post new circuit on the server")
        job = self._post_circuit(circuit, nshots, lab_location, device)

        logger.info("Job posted on server with pid %s", self.pid)
        logger.info(
            "Check results availability for %s job in your reserved page at %s",
            self.pid,
            constants.BASE_URL,
        )
        return job

    def _post_circuit(
        self,
        circuit: qibo.Circuit,
        nshots: int = 100,
        lab_location: str = "tii",
        device: str = "sim",
    ) -> QiboJob:
        url = self.base_url + "/run_circuit/"

        payload = {
            "token": self.token,
            "circuit": circuit.raw,
            "nshots": nshots,
            "device": device,
            "lab_location": lab_location,
        }
        response = QiboApiRequest.post(
            url,
            json=payload,
            timeout=constants.TIMEOUT,
        )
        breakpoint()
        result = response.json()

        self.pid = result["pid"]

        if self.pid is None:
            raise JobPostServerError(result["detail"])

        return QiboJob(
            base_url=self.base_url,
            pid=self.pid,
            circuit=circuit.raw,
            nshots=nshots,
            lab_location=lab_location,
            device=device,
        )
