"""The module implementing the Client class."""

import importlib.metadata as im
import typing as T

import dateutil.parser
import qibo
from packaging.version import Version

from . import constants
from .config_logging import logger
from .exceptions import JobPostServerError
from .qibo_job import QiboJob
from .ui import client_ui as ui
from .utils import QiboApiRequest

version = im.version(__package__)


class Client:
    """Class to manage the interaction with the remote server."""

    def __init__(self, token: str, url: str):
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
        ).json()

        qibo_server_version = Version(response["server_qibo_version"])
        qibo_min_client_version = Version(response["minimum_client_qibo_version"])
        qibo_client_version = Version(qibo.__version__)

        if qibo_client_version < qibo_min_client_version:
            raise RuntimeError(
                f"The qibo-client requires qibo>={qibo_min_client_version}, "
                f"but local version is {qibo_client_version}"
            )

        if qibo_client_version < qibo_server_version:
            logger.warning(
                "Local Qibo version (%s) is older than server (%s). Please upgrade.",
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
        :param nshots: number of shots.
        :type nshots: int
        :param verbatim: If True, attempts to run the circuit without any transpilation. Defaults to False.
        :type verbatim: bool

        :return: the QiboJob object.
        :rtype: Optional[QiboJob]
        """
        self.check_client_server_qibo_versions()

        return self._post_circuit(circuit, device, project, nshots, verbatim)

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
        ).json()

        self.pid = response.get("pid")
        if self.pid is None:
            raise JobPostServerError(response["detail"])

        return QiboJob(
            base_url=self.base_url,
            headers=self.headers,
            pid=self.pid,
            circuit=circuit.raw,
            nshots=nshots,
            device=device,
            project=project,
        )

    def print_quota_info(self):
        """Logs or prints user quota info with Rich or fallback."""
        disk_quota = QiboApiRequest.get(
            self.base_url + "/api/disk_quota/",
            headers=self.headers,
            timeout=constants.TIMEOUT,
        ).json()[0]

        projectquotas = QiboApiRequest.get(
            self.base_url + "/api/projectquotas/",
            headers=self.headers,
            timeout=constants.TIMEOUT,
        ).json()

        ui.render_quota(disk_quota, projectquotas)

    def print_job_info(self):
        """Logs or prints job info with Rich or fallback."""
        jobs = QiboApiRequest.get(
            self.base_url + "/api/jobs/",
            headers=self.headers,
            timeout=constants.TIMEOUT,
        ).json()

        if not jobs:
            logger.info("No jobs found in database for user")
            return

        user_set = {job["user"]["email"] for job in jobs}
        if len(user_set) > 1:
            raise ValueError("Multiple accounts found in /api/jobs/.")

        def fmt_dt(dt: str) -> str:
            return dateutil.parser.isoparse(dt).strftime("%Y-%m-%d %H:%M:%S")

        ui.render_jobs(next(iter(user_set)), jobs, fmt_dt)

    def get_job(self, pid: str) -> QiboJob:
        """Retrieves the job from the unique process id."""
        job = QiboJob(base_url=self.base_url, headers=self.headers, pid=pid)
        job.refresh()
        return job

    def delete_job(self, pid: str):
        """Removes the given job from the web server."""
        QiboJob(base_url=self.base_url, headers=self.headers, pid=pid).delete()
        logger.info("Deleted job %s", pid)

    def delete_all_jobs(self) -> list[str]:
        """Removes all jobs from the web server."""
        url = self.base_url + "/api/jobs/bulk_delete/"
        deleted_jobs = QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        ).json()["deleted"]
        logger.info("Deleted %s jobs", len(deleted_jobs))
        return deleted_jobs
