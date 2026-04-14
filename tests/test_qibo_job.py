import fixs
import jsf
import pytest
import responses

from qibo_client import QiboJobStatus, exceptions, qibo_job

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
FAKE_CIRCUIT = "fakeCircuit"
FAKE_NSHOTS = 10
FAKE_DEVICE = "fakeDevice"
FAKE_NUM_QUBITS = 8
FAKE_HARDWARE_TYPE = "fakeHardwareType"
FAKE_DESCRIPTION = "fakeDescription"
FAKE_STATUS = "fakeStatus"
BASE_JOB_STATUS = QiboJobStatus.SUCCESS
BASE_JOB_STATUS_STR = "success"
FAKE_RESULT = "fakeResult"


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
        response_json["nshots"] = FAKE_CIRCUIT
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

    def test_refresh_with_success(self, refresh_job):
        assert self.obj.circuit == FAKE_CIRCUIT
        assert self.obj.nshots == FAKE_NSHOTS
        assert self.obj.device == FAKE_DEVICE
        assert self.obj._status == BASE_JOB_STATUS

    @responses.activate
    def test_refresh_with_invalid_pid(self):
        invalid_pid = "invalidPid"
        self.obj.pid = invalid_pid
        endpoint = FAKE_URL + f"/api/jobs/{invalid_pid}/"
        response_json = {"detail": f"Invalid job pid, got {invalid_pid}"}
        responses.add(responses.GET, endpoint, status=404, json=response_json)

        with pytest.raises(exceptions.QiboApiError) as err:
            self.obj.refresh()

        assert str(err.value) == response_json["detail"]

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
    def test_running_with_cached_results(
        self, status: QiboJobStatus, expected_result: bool
    ):
        self.obj._status = status
        result = self.obj.running()
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
    def test_running_without_cached_results(
        self, monkeypatch, status: QiboJobStatus, expected_result: bool
    ):
        assert self.obj._status is None

        def change_obj_status_to():
            self.obj._status = status

        monkeypatch.setattr(self.obj, "refresh", change_obj_status_to)
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
    def test_success_with_cached_results(
        self, status: QiboJobStatus, expected_result: bool
    ):
        self.obj._status = status
        result = self.obj.success()
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
    def test_success_without_cached_results(
        self, monkeypatch, status: QiboJobStatus, expected_result: bool
    ):
        assert self.obj._status is None

        def change_obj_status_to():
            self.obj._status = status

        monkeypatch.setattr(self.obj, "refresh", change_obj_status_to)
        result = self.obj.success()
        assert result == expected_result

    def test_result_with_job_status_error(self, monkeypatch):
        snapshot = {"stdout": "some output", "stderr": "some error"}
        monkeypatch.setattr(
            self.obj,
            "_wait_for_response_to_get_request",
            lambda *args, **kwargs: (snapshot, QiboJobStatus.ERROR),
        )
        result = self.obj.result()
        assert result is None

    def test_result_with_job_status_success(self, monkeypatch):
        class FakeCircuit:
            measurements = []
            nqubits = 3

        snapshot = {"circuit": {"some": "dict"}, "frequencies": {"000": 100}}
        monkeypatch.setattr(
            self.obj,
            "_wait_for_response_to_get_request",
            lambda *args, **kwargs: (snapshot, QiboJobStatus.SUCCESS),
        )
        monkeypatch.setattr(
            "qibo_client.qibo_job.qibo.Circuit.from_dict",
            lambda x: FakeCircuit(),
        )
        monkeypatch.setattr(
            "qibo_client.qibo_job.qibo.result.MeasurementOutcomes.from_frequencies",
            lambda *args, **kwargs: FAKE_RESULT,
        )
        result = self.obj.result()
        assert result == FAKE_RESULT

    @pytest.mark.parametrize(
        "status, expected_job_status",
        [
            ("success", QiboJobStatus.SUCCESS),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_wait_for_response_to_get_request_simple(
        self, monkeypatch, caplog, status, expected_job_status
    ):

        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)

        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"

        failed_attempts = 3
        for _ in range(failed_attempts):
            responses.add(
                responses.GET,
                info_endpoint,
                status=200,
                json={"status": "running"},
            )

        final_payload = {"status": status}
        responses.add(
            responses.GET,
            info_endpoint,
            status=200,
            json=final_payload,
        )

        response, job_status = self.obj._wait_for_response_to_get_request(1e-4, False)

        assert job_status == expected_job_status
        assert response == final_payload
        assert len(responses.calls) == 1 + failed_attempts

        # first call is to status
        assert responses.calls[0].request.url == info_endpoint

        # other calls are to result
        for i in range(failed_attempts):
            r = responses.calls[i].request
            assert r.url == info_endpoint

        expected_logs = ["Please wait until your job is completed..."]
        assert caplog.messages == expected_logs

    @pytest.mark.parametrize(
        "status",
        ["success", "error"],
    )
    @responses.activate
    def test_wait_for_response_to_get_request_verbose(
        self, monkeypatch, caplog, status
    ):
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)
        monkeypatch.setattr(
            "qibo_client.qibo_job.constants.SECONDS_BETWEEN_CHECKS", 1e-4
        )

        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, endpoint, status=200)

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
            responses.add(
                responses.GET,
                endpoint,
                json=response_json,
                status=200,
            )
        self.obj._wait_for_response_to_get_request(verbose=True)

        expected_logs = [
            "🚀 Starting qibo client...",
            "📬 Job posted on None with pid, fakePid",
            "⏳ Job QUEUEING",
            "🕒 Job PENDING -> position in queue: 1, max ETD: 0:05:00",
            "🚀 Job RUNNING",
            "✅ Job SUCCESS" if status == "success" else "❌ Job ERROR",
            "Job COMPLETED",
        ]
        assert caplog.messages == expected_logs

    @responses.activate
    def test_delete(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"detail": f"Job {FAKE_PID} deleted"}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)

        response = self.obj.delete()
        assert response.json() == response_json
