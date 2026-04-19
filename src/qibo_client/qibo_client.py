"""Client class for interacting with the Qibo server.

This module implements the main Client class for managing interactions
with the remote Qibo server, including job submission and monitoring.
"""

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
    """Client for managing Qibo server interactions.

    This class provides a high-level interface for submitting quantum computing
    jobs to the Qibo server, monitoring their progress, and retrieving results.

    Attributes:
        token: Authentication token for server access
        headers: HTTP headers including authentication
        base_url: Base URL for the Qibo server API
        pid: Process ID of the most recent job
        results_folder: Folder where job results are stored
        results_path: Path to the most recent results file
    """

    def __init__(self, token: str, url: str):
        """Initialize the Client with authentication.

        Args:
            token: Authentication token for the webapp user
            url: Server API URL
        """
        self.token = token
        self.headers = {"x-api-token": token, "x-qibo-client-version": version}
        self.base_url = url

        # Job management
        self.pid = None
        self.results_folder = None
        self.results_path = None

    def check_client_server_qibo_versions(self):
        """Check that client and server qibo package versions match.

        Validates that the local Qibo version meets the server's requirements
        and optionally warns if the local version is older than the server's.

        Raises:
            RuntimeError: If the local qibo version is below the server's minimum
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
        """Run a quantum circuit on the cluster.

        This method submits a quantum circuit to the Qibo server for execution
        and returns a job object that can be used to monitor status and retrieve results.

        Args:
            circuit: The Qibo circuit to run
            device: The device to execute the circuit on
            project: The project to associate with this job. Defaults to "personal"
            nshots: Number of measurement shots (quantum executions)
            verbatim: If True, attempts to run circuit without transpilation

        Returns:
            QiboJob object for monitoring the job, or None if submission failed

        Raises:
            JobPostServerError: If the server fails to process the job submission
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
        """Submit a circuit to the server.

        Args:
            circuit: The circuit to submit
            device: Device identifier for execution
            project: Project name
            nshots: Number of shots for measurement
            verbatim: Whether to use verbatim execution mode

        Returns:
            QiboJob object for monitoring

        Raises:
            JobPostServerError: If server does not return a valid PID
        """
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
        """Print or log user quota information.

        Retrieves disk usage and project quota information from the server
        and displays it using the configured UI (Rich or plain logging).

        Returns:
            None
        """
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
        """Print or log information about completed jobs.

        Retrieves job information from the server and displays it.
        Expects at most one user account.

        Raises:
            ValueError: If multiple user accounts are found in job list
        """
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
            """Format ISO datetime to readable string."""
            return dateutil.parser.isoparse(dt).strftime("%Y-%m-%d %H:%M:%S")

        ui.render_jobs(next(iter(user_set)), jobs, fmt_dt)

    def get_job(self, pid: str) -> QiboJob:
        """Retrieve an existing job by process ID.

        Args:
            pid: Process ID of the job to retrieve

        Returns:
            QiboJob object representing the retrieved job
        """
        job = QiboJob(base_url=self.base_url, headers=self.headers, pid=pid)
        job.refresh()
        return job

    def delete_job(self, pid: str):
        """Remove a job from the server.

        Args:
            pid: Process ID of the job to delete
        """
        QiboJob(base_url=self.base_url, headers=self.headers, pid=pid).delete()
        logger.info("Deleted job %s", pid)

    def delete_all_jobs(self) -> list[str]:
        """Remove all jobs from the server.

        Returns:
            List of PIDs that were deleted
        """
        url = self.base_url + "/api/jobs/bulk_delete/"
        deleted_jobs = QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        ).json()["deleted"]
        logger.info("Deleted %s jobs", len(deleted_jobs))
        return deleted_jobs
