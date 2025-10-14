"""The module implementing the Client class."""

import importlib.metadata as im
import typing as T

import dateutil
import qibo
import tabulate
from packaging.version import Version

from . import constants
from .config_logging import logger
from .exceptions import JobPostServerError
from .qibo_job import QiboJob, build_event_job_posted_panel
from .utils import QiboApiRequest

version = im.version(__package__)


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
        self.headers = {"x-api-token": token, "x-qibo-client-version": version}
        self.base_url = url

        self.pid = None
        self.results_folder = None
        self.results_path = None

    def check_client_server_qibo_versions(self):
        """Check that client and server qibo package installed versions match.

        Raise assertion error if the two versions are not the same.
        """
        url = self.base_url + "/api/qibo_version/"
        response = QiboApiRequest.get(
            url,
            headers=self.headers,
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
        device: str,
        project: str = "personal",
        nshots: T.Optional[int] = None,
        verbatim: bool = False,
    ) -> T.Optional[QiboJob]:
        """Run circuit on the cluster.

        :param circuit: the QASM representation of the circuit to run
        :type circuit: Circuit
        :param device: the device to run the circuit on.
        :type device: str
        :type project: the project to run the circuit on.
        :type project: str
        :param nshots: number of shots, mandatory for non-simulation devices, defaults to `nshots=100` for simulation partitions
        :type nshots: int
        :param verbatim: If True, attempts to run the circuit without any transpilation. Defaults to False.
        :type verbatim: bool
        :param wait_for_results: whether to let the client hang until server results are ready or not. Defaults to True.
        :type wait_for_results: bool

        :return:
            the result of the computation. None if the job
            raised an error.
        :rtype: Optional[QiboJob]
        """
        self.check_client_server_qibo_versions()

        job = self._post_circuit(circuit, device, project, nshots, verbatim)

        job._preamble = build_event_job_posted_panel(device, job.pid)

        return job

    def _post_circuit(
        self,
        circuit: qibo.Circuit,
        device: str,
        project: str,
        nshots: T.Optional[int] = None,
        verbatim: bool = False,
    ) -> QiboJob:
        url = self.base_url + "/api/jobs/"

        payload = {
            "circuit": circuit.raw,
            "nshots": nshots,
            "device": device,
            "project": project,
            "verbatim": verbatim,
        }
        response = QiboApiRequest.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=constants.TIMEOUT,
        )
        result = response.json()

        self.pid = result.get("pid")

        if self.pid is None:
            raise JobPostServerError(result["detail"])

        return QiboJob(
            base_url=self.base_url,
            headers=self.headers,
            pid=self.pid,
            circuit=circuit.raw,
            nshots=nshots,
            device=device,
        )

    def print_quota_info(self):
        """Logs the formatted user quota info table."""
        url = self.base_url + "/api/disk_quota/"

        response = QiboApiRequest.get(
            url,
            headers=self.headers,
            timeout=constants.TIMEOUT,
        )

        disk_quota = response.json()[0]

        url = self.base_url + "/api/projectquotas/"

        response = QiboApiRequest.get(
            url,
            headers=self.headers,
            timeout=constants.TIMEOUT,
        )

        projectquotas = response.json()

        message = (
            f"User: {disk_quota['user']['email']}\n"
            f"Disk quota left [KBs]: {disk_quota['kbs_left']:.2f} / {disk_quota['kbs_max']:.2f}\n"
        )

        rows = [
            (
                t["project"],
                t["partition"]["name"],
                t["partition"]["max_num_qubits"],
                t["partition"]["hardware_type"],
                t["partition"]["description"],
                t["partition"]["status"],
                t["seconds_left"],
                t["shots_left"],
                t["jobs_left"],
            )
            for t in projectquotas
        ]
        message += tabulate.tabulate(
            rows,
            headers=[
                "Project Name",
                "Device Name",
                "Qubits",
                "Type",
                "Description",
                "Status",
                "Time Left [s]",
                "Shots Left",
                "Jobs Left",
            ],
        )
        logger.info(message)

    def print_job_info(self):
        """Logs the formatted user quota info table."""
        url = self.base_url + "/api/jobs/"

        response = QiboApiRequest.get(
            url,
            headers=self.headers,
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
                "The `/api/jobs/` endpoint returned info about " "multiple accounts."
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
        job = QiboJob(base_url=self.base_url, headers=self.headers, pid=pid)
        job.refresh()
        return job

    def delete_job(self, pid: str):
        """Removes the given job from the web server.

        :param pid: the job's process identifier
        :type pid: str
        """
        job = QiboJob(base_url=self.base_url, headers=self.headers, pid=pid)
        job.delete()
        logger.info("Deleted job %s", pid)

    def delete_all_jobs(self) -> list[str]:
        """Removes all jobs from the web server."""
        url = self.base_url + "/api/jobs/bulk_delete/"
        response = QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        )
        deleted_jobs = response.json()["deleted"]
        logger.info("Deleted %s jobs", len(deleted_jobs))
        return deleted_jobs
