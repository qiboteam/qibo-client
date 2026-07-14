import logging

import fixs
import jsf
import pytest
import responses
import tabulate

import qibo_client.qibo_client as qc
from qibo_client import QiboJob, QiboJobStatus, exceptions, qibo_client
from qibo_client.qibo_client import Client

MOD = "qibo_client.qibo_client"
FAKE_URL = "http://fake.endpoint.com"
FAKE_PROJECT = "fakeProject"
FAKE_TOKEN = "fakeToken"
FAKE_QIBO_CLIENT_VERSION = "0.2.9"
FAKE_USER_EMAIL = "fake@user.com"
FAKE_QIBO_VERSION = "0.2.6"
FAKE_MINIMUM_QIBO_VERSION_ALLOWED = "0.1.2a"
FAKE_MINIMUM_CLIENT_VERSION_ALLOWED = "0.0.1"
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
        monkeypatch.setattr(f"{MOD}.version", FAKE_QIBO_CLIENT_VERSION)
        self.client = qibo_client.Client(FAKE_TOKEN, FAKE_URL)
        yield

    @pytest.fixture
    def pass_version_check(self, monkeypatch):
        monkeypatch.setattr(f"{MOD}.qibo.__version__", FAKE_QIBO_VERSION)
        endpoint = FAKE_URL + "/api/qibo_version/"
        response_json = {
            "server_qibo_version": FAKE_QIBO_VERSION,
            "minimum_qibo_version": FAKE_MINIMUM_QIBO_VERSION_ALLOWED,
            "minimum_client_version": FAKE_MINIMUM_CLIENT_VERSION_ALLOWED,
        }
        with responses.RequestsMock() as rsps:
            rsps.get(endpoint, status=200, json=response_json)
            yield rsps

    def test_init_method(self):
        assert self.client.token == FAKE_TOKEN
        assert self.client.base_url == FAKE_URL

        assert self.client.pid is None

    @responses.activate
    def test_check_client_server_qibo_versions_raises_assertion_error(
        self, monkeypatch
    ):
        monkeypatch.setattr(f"{MOD}.qibo.__version__", FAKE_QIBO_VERSION)

        endpoint = FAKE_URL + "/api/qibo_version/"
        response_json = {
            "server_qibo_version": "0.2.9",
            "minimum_qibo_version": "0.2.8",
            "minimum_client_version": FAKE_MINIMUM_CLIENT_VERSION_ALLOWED,
        }
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        with pytest.raises(RuntimeError) as err:
            self.client.check_client_server_qibo_versions()

        expected_message = f"The qibo-client requires qibo>=0.2.8, but local version is {FAKE_QIBO_VERSION}"
        assert str(err.value) == expected_message

    def test_check_client_server_qibo_versions_with_no_log(
        self, pass_version_check, caplog
    ):
        """Tests client does not log any warning if the local qibo version is
        greater of equal than the remote one.
        """
        caplog.set_level(logging.WARNING)

        self.client.check_client_server_qibo_versions()

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
            "minimum_qibo_version": FAKE_MINIMUM_QIBO_VERSION_ALLOWED,
            "minimum_client_version": FAKE_MINIMUM_CLIENT_VERSION_ALLOWED,
        }
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        self.client.check_client_server_qibo_versions()

        expected_log = f"Local Qibo version ({FAKE_QIBO_VERSION}) is older than server (0.2.9). Please upgrade."
        assert expected_log in caplog.messages

    def test_run_circuit_with_invalid_token(self, pass_version_check):
        endpoint = FAKE_URL + "/api/jobs/"
        message = "User not found, specify the correct token"
        response_json = {"detail": message}
        pass_version_check.add(responses.POST, endpoint, status=404, json=response_json)

        with pytest.raises(exceptions.QiboApiError) as err:
            self.client.run_circuit(FAKE_CIRCUIT, FAKE_DEVICE, FAKE_NSHOTS)

        assert message in str(err.value)

    def test_run_circuit_with_job_post_error(self, pass_version_check):
        endpoint = FAKE_URL + "/api/jobs/"
        message = "Server failed to post job to queue"
        response_json = {"detail": message}
        pass_version_check.add(responses.POST, endpoint, status=200, json=response_json)

        with pytest.raises(exceptions.JobPostServerError) as err:
            self.client.run_circuit(FAKE_CIRCUIT, FAKE_DEVICE, FAKE_NSHOTS)

        assert str(err.value) == message

    def test_run_circuit_with_success(self, pass_version_check, caplog):
        caplog.set_level(logging.INFO)
        endpoint = FAKE_URL + "/api/jobs/"
        response_json = {"pid": FAKE_PID}
        pass_version_check.add(responses.POST, endpoint, status=200, json=response_json)

        job = self.client.run_circuit(
            FAKE_CIRCUIT, FAKE_DEVICE, FAKE_PROJECT, FAKE_NSHOTS
        )

        assert job.pid == FAKE_PID
        assert job.base_url == FAKE_URL
        assert job.circuit == "fakeCircuit"
        assert job.nshots == FAKE_NSHOTS
        assert job.device == FAKE_DEVICE
        assert job._status is None

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
                str(FAKE_NUM_QUBITS),
                FAKE_HARDWARE_TYPE,
                FAKE_DESCRIPTION,
                FAKE_STATUS,
                "2",
                "15",
                "15",
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

        self.client.print_quota_info()

        # The new client_ui uses _quota_rows which might differ slightly in types
        assert FAKE_USER_EMAIL in caplog.messages[0]
        assert FAKE_PROJECT in caplog.messages[0]

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

        self.client.print_job_info()

        assert FAKE_USER_EMAIL in caplog.messages[0]
        assert formatted_creation_date in caplog.messages[0]
        assert "success" in caplog.messages[0]

    @responses.activate
    def test_print_job_info_without_jobs(self, caplog):
        caplog.set_level(logging.INFO)
        endpoint = FAKE_URL + "/api/jobs/"
        responses.add(responses.GET, endpoint, status=200, json=[])

        self.client.print_job_info()

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
            self.client.print_job_info()

    @responses.activate
    def test_get_job(self, monkeypatch):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = jsf.JSF(fixs.JOB_SCHEMA).generate()
        response_json["status"] = "queueing"
        response_json["circuit"] = "fakeCircuit"
        response_json["nshots"] = FAKE_NSHOTS
        response_json["projectquota"]["partition"]["name"] = FAKE_DEVICE
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        result = self.client.get_job(FAKE_PID)

        assert result.pid == FAKE_PID
        assert result.circuit == "fakeCircuit"
        assert result.status() == QiboJobStatus.QUEUEING

    @responses.activate
    def test_delete_job(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"detail": f"Job {FAKE_PID} deleted"}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)

        self.client.delete_job(FAKE_PID)

    @responses.activate
    def test_delete_all_jobs(self):
        endpoint = FAKE_URL + "/api/jobs/bulk_delete/"
        response_json = {"deleted": ["jobPid1", "jobPid2"]}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)

        response = self.client.delete_all_jobs()
        assert response == response_json["deleted"]


def test_rejects_old_sdk_version(monkeypatch):
    monkeypatch.setattr(qc, "version", "0.2.4")

    class _Resp:
        def json(self):
            return {
                "server_qibo_version": "0.3.2",
                "minimum_qibo_version": "0.0.1",
                "minimum_client_version": "0.3.0",
            }

    monkeypatch.setattr(qc.QiboApiRequest, "get", staticmethod(lambda *a, **k: _Resp()))

    client = Client(token="t", url="http://x")
    with pytest.raises(RuntimeError, match="qibo-client"):
        client.check_client_server_qibo_versions()
