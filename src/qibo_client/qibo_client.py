"""The module implementing the Client class."""

import typing as T

import dateutil
import qibo
import tabulate
from packaging.version import Version

from . import constants
from .config_logging import logger
from .exceptions import JobPostServerError
from .qibo_job import QiboJob
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
        url = self.base_url + "/client/qibo_version/"
        response = QiboApiRequest.get(
            url,
            timeout=constants.TIMEOUT,
            keys_to_check=["server_qibo_version", "minimum_client_qibo_version"],
        )

        qibo_server_version = Version(response.json()["server_qibo_version"])
        qibo_minimum_client_version = Version(
            response.json()["minimum_client_qibo_version"]
        )

        qibo_client_version = Version(qibo.__version__)
        msg = (
            "The qibo-client package requires an installed qibo package version"
            f">={qibo_minimum_client_version}, the local qibo "
            f"version is {qibo_client_version}"
        )
        assert qibo_client_version >= qibo_minimum_client_version, msg

        if qibo_client_version < qibo_server_version:
            logger.warning(
                "Local Qibo package version does not match the server one, please "
                "upgrade: %s -> %s",
                qibo_client_version,
                qibo_server_version,
            )

    def run_circuit(
        self,
        circuit: qibo.Circuit,
        nshots: int = 1000,
        device: str = "k2",
    ) -> T.Optional[qibo.result.QuantumState]:
        """Run circuit on the cluster.

        :param circuit: the QASM representation of the circuit to run
        :type circuit: Circuit
        :param nshots: number of shots
        :type nshots: int
        :param device: the device to run the circuit on. Default device is `k2`
        :type device: str
        :param wait_for_results: whether to let the client hang until server results are ready or not. Defaults to True.
        :type wait_for_results: bool

        :return:
            the numpy array with the results of the computation. None if the job
            raised an error.
        :rtype: Optional[QiboJobResult]
        """
        self.check_client_server_qibo_versions()

        logger.info("Post new circuit on the server")
        job = self._post_circuit(circuit, nshots, device)

        logger.info("Job posted on server with pid %s", self.pid)
        logger.info(
            "Check results availability for %s job in your reserved page at %s",
            self.pid,
            self.base_url,
        )
        return job

    def _post_circuit(
        self,
        circuit: qibo.Circuit,
        nshots: int = 100,
        device: str = "k2",
    ) -> QiboJob:
        url = self.base_url + "/client/run_circuit/"

        payload = {
            "token": self.token,
            "circuit": circuit.raw,
            "nshots": nshots,
            "device": device,
        }
        response = QiboApiRequest.post(
            url,
            json=payload,
            timeout=constants.TIMEOUT,
        )
        result = response.json()

        self.pid = result.get("pid")

        if self.pid is None:
            raise JobPostServerError(result["detail"])

        return QiboJob(
            base_url=self.base_url,
            pid=self.pid,
            circuit=circuit.raw,
            nshots=nshots,
            device=device,
        )

    def print_quota_info(self):
        """Logs the formatted user quota info table."""
        url = self.base_url + "/client/info/quotas/"

        payload = {
            "token": self.token,
        }
        response = QiboApiRequest.post(
            url,
            json=payload,
            timeout=constants.TIMEOUT,
            keys_to_check=["disk_quota", "time_quotas"],
        )

        disk_quota = response.json()["disk_quota"]
        time_quotas = response.json()["time_quotas"]

        message = (
            f"User: {disk_quota['user']['email']}\n"
            f"Disk quota left [KBs]: {disk_quota['kbs_left']:.2f} / {disk_quota['kbs_max']:.2f}\n"
        )

        rows = [
            (
                t["partition"]["name"],
                t["partition"]["max_num_qubits"],
                t["partition"]["hardware_type"],
                t["partition"]["description"],
                t["partition"]["status"],
                t["seconds_left"],
            )
            for t in time_quotas
        ]
        message += tabulate.tabulate(
            rows,
            headers=[
                "Device Name",
                "Qubits",
                "Type",
                "Description",
                "Status",
                "Time Left [s]",
            ],
        )
        logger.info(message)

    def print_job_info(self):
        """Logs the formatted user quota info table."""
        url = self.base_url + "/client/info/jobs/"

        payload = {
            "token": self.token,
        }
        response = QiboApiRequest.post(
            url,
            json=payload,
            timeout=constants.TIMEOUT,
        )

        def format_date(dt: str) -> str:
            dt = dateutil.parser.isoparse(dt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        jobs = response.json()
        if not len(jobs):
            logger.info("No jobs found in database for user")
            return None

        user_set = {job["user"]["email"] for job in jobs}
        if len(user_set) > 1:
            raise ValueError(
                "The `/client/info/jobs/` endpoint returned info about "
                "multiple accounts."
            )
        user = list(user_set)[0]

        rows = [
            (
                job["pid"],
                format_date(job["created_at"]),
                format_date(job["updated_at"]),
                job["status"],
                job["result_path"],
            )
            for job in response.json()
        ]
        message = f"User: {user}\n" + tabulate.tabulate(
            rows, headers=["Pid", "Created At", "Updated At", "Status", "Results"]
        )
        logger.info(message)

    def get_job(self, pid: str) -> QiboJob:
        """Retrieves the job from the unique process id.

        :param pid: the job's process identifier
        :type pid: str

        :return: the requested QiboJob object
        :rtype: QiboJob
        """
        job = QiboJob(
            base_url=self.base_url,
            pid=pid,
        )
        job.refresh()
        return job
