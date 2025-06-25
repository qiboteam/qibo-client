import logging

import fixs
import jsf
import pytest
import responses
import tabulate

from qibo_client import QiboJob, QiboJobStatus, exceptions, qibo_client

MOD = "qibo_client.qibo_client"
FAKE_URL = "http://fake.endpoint.com"
FAKE_PROJECT = "fakeProject"
FAKE_TOKEN = "fakeToken"
FAKE_USER_EMAIL = "fake@user.com"
FAKE_QIBO_VERSION = "0.2.6"
FAKE_MINIMUM_QIBO_VERSION_ALLOWED = "0.2.4"
FAKE_PID = "123"
TIMEOUT = 1


class FakeCircuit:

    @property
    def raw(self):
        return "fakeCircuit"


FAKE_CIRCUIT = FakeCircuit()
FAKE_NSHOTS = 10
FAKE_DEVICE = "fakeDevice"
FAKE_NUM_QUBITS = 8
FAKE_HARDWARE_TYPE = "fakeHardwareType"
FAKE_DESCRIPTION = "fakeDescription"
FAKE_STATUS = "fakeStatus"


class TestQiboClient:
    @pytest.fixture(
        autouse=True,
    )
    def setup_and_teardown(self, monkeypatch):
        monkeypatch.setattr(f"{MOD}.constants.BASE_URL", FAKE_URL)
        self.obj = qibo_client.Client(FAKE_TOKEN, FAKE_URL)
        yield

    @pytest.fixture
    def pass_version_check(self, monkeypatch):
        monkeypatch.setattr(f"{MOD}.qibo.__version__", FAKE_QIBO_VERSION)
        endpoint = FAKE_URL + "/api/qibo_version/"
        response_json = {
            "server_qibo_version": FAKE_QIBO_VERSION,
            "minimum_client_qibo_version": FAKE_MINIMUM_QIBO_VERSION_ALLOWED,
        }
        with responses.RequestsMock() as rsps:
            rsps.get(endpoint, status=200, json=response_json)
            yield rsps

    def test_init_method(self):
        assert self.obj.token == FAKE_TOKEN
        assert self.obj.base_url == FAKE_URL

        assert self.obj.pid is None
        assert self.obj.results_folder is None
        assert self.obj.results_path is None

    @responses.activate
    def test_check_client_server_qibo_versions_raises_assertion_error(
        self, monkeypatch
    ):
        monkeypatch.setattr(f"{MOD}.qibo.__version__", FAKE_QIBO_VERSION)

        endpoint = FAKE_URL + "/api/qibo_version/"
        response_json = {
            "server_qibo_version": "0.2.9",
            "minimum_client_qibo_version": "0.2.8",
        }
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        with pytest.raises(AssertionError) as err:
            self.obj.check_client_server_qibo_versions()

        expected_message = (
            "The qibo-client package requires an installed qibo package version"
            f">=0.2.8, the local qibo version is {FAKE_QIBO_VERSION}"
        )
        assert str(err.value) == expected_message

    def test_check_client_server_qibo_versions_with_no_log(
        self, pass_version_check, caplog
    ):
        """Tests client does not log any warning if the local qibo version is
        greater of equal than the remote one.
        """
        caplog.set_level(logging.WARNING)

        self.obj.check_client_server_qibo_versions()

        assert caplog.messages == []

    @responses.activate
    def test_check_client_server_qibo_versions_with_warning(self, monkeypatch, caplog):
        """Tests client logs a warning if the remote qibo version is greater
        than the local one.
        """
        caplog.set_level(logging.WARNING)
        monkeypatch.setattr(f"{MOD}.qibo.__version__", FAKE_QIBO_VERSION)

        endpoint = FAKE_URL + "/api/qibo_version/"
        response_json = {
            "server_qibo_version": "0.2.9",
            "minimum_client_qibo_version": FAKE_MINIMUM_QIBO_VERSION_ALLOWED,
        }
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        self.obj.check_client_server_qibo_versions()

        expected_log = (
            "Local Qibo package version does not match the server one, please "
            f"upgrade: {FAKE_QIBO_VERSION} -> 0.2.9"
        )
        assert expected_log in caplog.messages

    def test_run_circuit_with_invalid_token(self, pass_version_check):
        endpoint = FAKE_URL + "/api/jobs/"
        message = "User not found, specify the correct token"
        response_json = {"detail": message}
        pass_version_check.add(responses.POST, endpoint, status=404, json=response_json)

        with pytest.raises(exceptions.JobApiError) as err:
            self.obj.run_circuit(FAKE_CIRCUIT, FAKE_DEVICE, FAKE_NSHOTS)

        expected_message = f"\033[91m[404 Error] {message}\033[0m"
        assert str(err.value) == expected_message

    def test_run_circuit_with_job_post_error(self, pass_version_check):
        endpoint = FAKE_URL + "/api/jobs/"
        message = "Server failed to post job to queue"
        response_json = {"detail": message}
        pass_version_check.add(responses.POST, endpoint, status=200, json=response_json)

        with pytest.raises(exceptions.JobPostServerError) as err:
            self.obj.run_circuit(FAKE_CIRCUIT, FAKE_DEVICE, FAKE_NSHOTS)

        assert str(err.value) == message

    def test_run_circuit_with_success(self, pass_version_check, caplog):
        caplog.set_level(logging.INFO)
        endpoint = FAKE_URL + "/api/jobs/"
        response_json = {"pid": FAKE_PID}
        pass_version_check.add(responses.POST, endpoint, status=200, json=response_json)

        job = self.obj.run_circuit(FAKE_CIRCUIT, FAKE_DEVICE, FAKE_PROJECT, FAKE_NSHOTS)

        assert job.pid == FAKE_PID
        assert job.base_url == FAKE_URL
        assert job.circuit == "fakeCircuit"
        assert job.nshots == FAKE_NSHOTS
        assert job.device == FAKE_DEVICE
        assert job._status is None

        expected_messages = [
            f"Job posted on server with pid {FAKE_PID}",
        ]
        for expected_message in expected_messages:
            assert expected_message in caplog.messages

    @responses.activate
    def test_print_quota_info(self, caplog):
        caplog.set_level(logging.INFO)

        endpoint = FAKE_URL + "/api/disk_quota/"
        response_json = [
            {
                "user": {"email": FAKE_USER_EMAIL},
                "kbs_left": 5,
                "kbs_max": 10,
            }
        ]
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        endpoint = FAKE_URL + "/api/projectquotas/"
        response_json = [
            {
                "project": FAKE_PROJECT,
                "partition": {
                    "name": FAKE_DEVICE,
                    "max_num_qubits": FAKE_NUM_QUBITS,
                    "hardware_type": FAKE_HARDWARE_TYPE,
                    "description": FAKE_DESCRIPTION,
                    "status": FAKE_STATUS,
                },
                "seconds_left": 1.5,
                "shots_left": 15,
                "jobs_left": 15,
            }
        ]
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        rows = [
            (
                FAKE_PROJECT,
                FAKE_DEVICE,
                FAKE_NUM_QUBITS,
                FAKE_HARDWARE_TYPE,
                FAKE_DESCRIPTION,
                FAKE_STATUS,
                1.5,
                15,
                15,
            )
        ]
        expected_table = tabulate.tabulate(
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
        expected_message = (
            f"User: {FAKE_USER_EMAIL}\n"
            "Disk quota left [KBs]: 5.00 / 10.00\n"
            f"{expected_table}"
        )

        self.obj.print_quota_info()

        assert caplog.messages == [expected_message]

    @responses.activate
    def test_print_job_info_with_success(self, caplog):
        caplog.set_level(logging.INFO)
        endpoint = FAKE_URL + "/api/jobs/"
        fake_creation_date = "2000-01-01T00:00:00.128372Z"
        formatted_creation_date = "2000-01-01 00:00:00"
        fake_update_date = "2000-01-02T00:00:00.128372Z"
        formatted_update_date = "2000-01-02 00:00:00"
        fake_result_path = "fakeResult.Path"
        response_json = [
            {
                "pid": FAKE_PID + "1",
                "user": {"email": FAKE_USER_EMAIL},
                "created_at": fake_creation_date,
                "updated_at": fake_update_date,
                "status": "success",
                "result_path": fake_result_path,
            },
            {
                "pid": FAKE_PID + "2",
                "user": {"email": FAKE_USER_EMAIL},
                "created_at": fake_creation_date,
                "updated_at": fake_update_date,
                "status": "error",
                "result_path": "",
            },
        ]

        responses.add(responses.GET, endpoint, status=200, json=response_json)

        rows = [
            (
                FAKE_PID + "1",
                formatted_creation_date,
                formatted_update_date,
                "success",
                fake_result_path,
            ),
            (
                FAKE_PID + "2",
                formatted_creation_date,
                formatted_update_date,
                "error",
                "",
            ),
        ]
        expected_table = tabulate.tabulate(
            rows, headers=["Pid", "Created At", "Updated At", "Status", "Results"]
        )
        expected_message = f"User: {FAKE_USER_EMAIL}\n" f"{expected_table}"

        self.obj.print_job_info()

        assert caplog.messages == [expected_message]

    @responses.activate
    def test_print_job_info_without_jobs(self, caplog):
        caplog.set_level(logging.INFO)
        endpoint = FAKE_URL + "/api/jobs/"
        responses.add(responses.GET, endpoint, status=200, json=[])

        self.obj.print_job_info()

        assert caplog.messages == ["No jobs found in database for user"]

    @responses.activate
    def test_print_job_info_raises_valuerror(self, caplog):
        caplog.set_level(logging.INFO)

        endpoint = FAKE_URL + "/api/jobs/"
        response_json = [
            {
                "pid": FAKE_PID + "1",
                "user": {"email": FAKE_USER_EMAIL + "1"},
            },
            {
                "pid": FAKE_PID + "2",
                "user": {"email": FAKE_USER_EMAIL + "2"},
            },
        ]

        responses.add(responses.GET, endpoint, status=200, json=response_json)

        with pytest.raises(ValueError):
            self.obj.print_job_info()

    @responses.activate
    def test_get_job(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = jsf.JSF(fixs.JOB_SCHEMA).generate()
        response_json["status"] = "queueing"
        response_json["circuit"] = "fakeCircuit"
        response_json["nshots"] = FAKE_NSHOTS
        response_json["projectquota"]["partition"]["name"] = FAKE_DEVICE
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        result = self.obj.get_job(FAKE_PID)

        expected_result = QiboJob(
            pid=FAKE_PID,
            base_url=FAKE_URL,
            circuit="fakeCircuit",
            nshots=FAKE_NSHOTS,
            headers={"x-api-token": FAKE_TOKEN},
            device=FAKE_DEVICE,
        )
        expected_result._status = QiboJobStatus.QUEUEING
        assert vars(result) == vars(expected_result)

    @responses.activate
    def test_delete_job(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"detail": f"Job {FAKE_PID} deleted"}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)

        response = self.obj.delete_job(FAKE_PID)
        assert response == response_json["detail"]

    @responses.activate
    def test_delete_all_jobs(self):
        endpoint = FAKE_URL + "/api/jobs/bulk_delete/"
        response_json = {"deleted": ["jobPid1", "jobPid2"]}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)

        response = self.obj.delete_all_jobs()
        assert response == response_json["deleted"]
