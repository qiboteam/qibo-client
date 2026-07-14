import fixs
import jsf
import pytest
import qibo
import responses

from qibo_client import QiboJobStatus, exceptions, qibo_job
from qibo_client.qibo_job import QiboJob


@pytest.mark.parametrize(
    "status, expected_result",
    [
        ("queueing", QiboJobStatus.QUEUEING),
        ("pending", QiboJobStatus.PENDING),
        ("running", QiboJobStatus.RUNNING),
        ("postprocessing", QiboJobStatus.POSTPROCESSING),
        ("success", QiboJobStatus.SUCCESS),
        ("error", QiboJobStatus.ERROR),
        ("done", None),
        ("invalid", None),
    ],
)
def test_convert_str_to_job_status(status, expected_result):
    result = qibo_job.convert_str_to_job_status(status)
    assert result == expected_result


FAKE_PID = "fakePid"
FAKE_URL = "http://fake.endpoint.com"
FAKE_CIRCUIT = {"fake": "circuit"}
FAKE_NSHOTS = 10
FAKE_DEVICE = "fakeDevice"
FAKE_NUM_QUBITS = 8
FAKE_HARDWARE_TYPE = "fakeHardwareType"
FAKE_DESCRIPTION = "fakeDescription"
FAKE_STATUS = "fakeStatus"
BASE_JOB_STATUS = QiboJobStatus.SUCCESS
BASE_JOB_STATUS_STR = "success"


class TestQiboJob:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.obj = qibo_job.QiboJob(FAKE_PID, FAKE_URL)
        yield

    @pytest.fixture
    @responses.activate
    def refresh_job(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = jsf.JSF(fixs.JOB_SCHEMA).generate()
        response_json["circuit"] = FAKE_CIRCUIT
        response_json["nshots"] = FAKE_NSHOTS
        response_json.update(
            {
                "circuit": FAKE_CIRCUIT,
                "nshots": FAKE_NSHOTS,
                "status": BASE_JOB_STATUS_STR,
            }
        )
        response_json["projectquota"]["partition"].update(
            {
                "name": FAKE_DEVICE,
                "max_num_qubits": FAKE_NUM_QUBITS,
                "hardware_type": FAKE_HARDWARE_TYPE,
                "description": None,
                "status": FAKE_STATUS,
            }
        )
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        self.obj.refresh()

    def test_init_method(self):
        assert self.obj.pid == FAKE_PID
        assert self.obj.base_url == FAKE_URL
        assert self.obj.circuit is None
        assert self.obj.nshots is None
        assert self.obj.device is None
        assert self.obj._status is None
        assert self.obj.frequencies is None

    def test_refresh_with_success(self, refresh_job):
        assert self.obj.circuit == FAKE_CIRCUIT
        assert self.obj.nshots == FAKE_NSHOTS
        assert self.obj.device == FAKE_DEVICE
        assert self.obj._status == BASE_JOB_STATUS

    @responses.activate
    def test_refresh_captures_frequencies(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"status": "success", "frequencies": {"00": 5, "11": 5}}
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        self.obj.refresh()
        assert self.obj.frequencies == {"00": 5, "11": 5}

    @responses.activate
    def test_refresh_with_invalid_pid(self):
        invalid_pid = "invalidPid"
        self.obj.pid = invalid_pid
        endpoint = FAKE_URL + f"/api/jobs/{invalid_pid}/"
        response_json = {"detail": f"Invalid job pid, got {invalid_pid}"}
        responses.add(responses.GET, endpoint, status=404, json=response_json)
        with pytest.raises(exceptions.QiboApiError) as err:
            self.obj.refresh()
        assert response_json["detail"] in str(err.value)

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            ("queueing", QiboJobStatus.QUEUEING),
            ("pending", QiboJobStatus.PENDING),
            ("running", QiboJobStatus.RUNNING),
            ("postprocessing", QiboJobStatus.POSTPROCESSING),
            ("success", QiboJobStatus.SUCCESS),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_status(self, status, expected_result):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"status": status}
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        result = self.obj.status()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUEING, False),
            (QiboJobStatus.PENDING, False),
            (QiboJobStatus.RUNNING, True),
            (QiboJobStatus.POSTPROCESSING, False),
            (QiboJobStatus.SUCCESS, False),
            (QiboJobStatus.ERROR, False),
        ],
    )
    @responses.activate
    def test_running_with_cached_results(self, status, expected_result):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, endpoint, status=200, json={"status": status.name.lower()}
        )
        result = self.obj.running()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUEING, False),
            (QiboJobStatus.PENDING, False),
            (QiboJobStatus.RUNNING, False),
            (QiboJobStatus.POSTPROCESSING, False),
            (QiboJobStatus.SUCCESS, True),
            (QiboJobStatus.ERROR, False),
        ],
    )
    @responses.activate
    def test_success_with_cached_results(self, status, expected_result):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, endpoint, status=200, json={"status": status.name.lower()}
        )
        result = self.obj.success()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_job_status",
        [
            ("success", QiboJobStatus.SUCCESS),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_wait_for_completion_simple(
        self, monkeypatch, caplog, status, expected_job_status
    ):
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        failed_attempts = 3
        for _ in range(failed_attempts + 1):
            responses.add(
                responses.GET, info_endpoint, status=200, json={"status": "running"}
            )
        responses.add(responses.GET, info_endpoint, status=200, json={"status": status})

        job_status = self.obj._wait_for_completion(1e-4, False)
        assert job_status == expected_job_status

    @pytest.mark.parametrize("status", ["success", "error"])
    @responses.activate
    def test_wait_for_completion_verbose(self, monkeypatch, caplog, status):
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)
        monkeypatch.setattr(
            "qibo_client.qibo_job.constants.SECONDS_BETWEEN_CHECKS", 1e-4
        )

        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        statuses_list = [
            "queueing",
            "queueing",
            "pending",
            "running",
            "postprocessing",
            status,
        ]
        for s in statuses_list:
            response_json = {
                "status": s,
                "seconds_to_job_start": 300,
                "job_queue_position": 1,
            }
            responses.add(responses.GET, endpoint, json=response_json, status=200)

        job_status = self.obj._wait_for_completion(verbose=True)
        assert job_status == QiboJobStatus[status.upper()]
        log_text = "".join(caplog.messages)
        assert "* Job QUEUEING" in log_text
        assert "max ETD: 0:05:00" in log_text
        assert "> Job RUNNING" in log_text
        assert "Job COMPLETED" in log_text

    @responses.activate
    def test_delete(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"detail": f"Job {FAKE_PID} deleted"}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)
        response = self.obj.delete()
        assert response.json() == response_json


class TestLiveTTYBranch:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.obj = qibo_job.QiboJob(FAKE_PID, FAKE_URL, device=FAKE_DEVICE)
        monkeypatch.setattr("qibo_client.qibo_job.USE_RICH_UI", True)
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)

    @responses.activate
    def test_live_branch_immediate_success(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # 1. initial refresh()
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        # 2. _wait_live while-True refresh()
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        job_status = self.obj._wait_for_completion(1e-4, verbose=True)
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_polls_then_success(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Sequence of statuses
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        job_status = self.obj._wait_for_completion(1e-4, verbose=True)
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_wait_non_live_non_verbose(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # initial refresh
        responses.add(
            responses.GET, info_endpoint, json={"status": "running"}, status=200
        )
        # loop refresh
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        job_status = self.obj._wait_for_completion(1e-4, verbose=False)
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_with_postprocessing(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Sequence: pending -> postprocessing -> success
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "postprocessing"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        job_status = self.obj._wait_for_completion(1e-4, verbose=True)
        assert job_status == qibo_job.QiboJobStatus.SUCCESS


def _make_job():
    qibo.set_backend("numpy")
    c = qibo.Circuit(2)
    c.add(qibo.gates.H(0))
    c.add(qibo.gates.M(0, 1))
    job = QiboJob(pid="PID1", base_url="http://x", circuit=c.raw, nshots=100)
    return job


def test_result_rebuilds_measurement_outcomes(monkeypatch):
    job = _make_job()

    def fake_wait(wait, verbose):
        job._status = QiboJobStatus.SUCCESS
        job.frequencies = {"00": 60, "11": 40}
        return QiboJobStatus.SUCCESS

    monkeypatch.setattr(job, "_wait_for_completion", fake_wait)
    out = job.result(verbose=False)
    assert dict(out.frequencies()) == {"00": 60, "11": 40}


def test_result_returns_none_on_error(monkeypatch):
    job = _make_job()

    def fake_wait(wait, verbose):
        job._status = QiboJobStatus.ERROR
        job.frequencies = None
        return QiboJobStatus.ERROR

    monkeypatch.setattr(job, "_wait_for_completion", fake_wait)
    assert job.result(verbose=False) is None


def test_result_returns_none_on_empty_frequencies(monkeypatch):
    job = _make_job()

    def fake_wait(wait, verbose):
        job._status = QiboJobStatus.SUCCESS
        job.frequencies = None
        return QiboJobStatus.SUCCESS

    monkeypatch.setattr(job, "_wait_for_completion", fake_wait)
    assert job.result(verbose=False) is None
