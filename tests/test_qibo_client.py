import logging
import typing as T

import pytest
import responses

from qibo_client import QiboJob, exceptions, qibo_client

MOD = "qibo_client.qibo_client"
FAKE_URL = "http://fake.endpoint.com/api"
FAKE_TOKEN = "fakeToken"
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
FAKE_LAB_LOCATION = "fakeLabLocation"
FAKE_DEVICE = "fakeDevice"


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
        monkeypatch.setattr(
            f"{MOD}.constants.MINIMUM_QIBO_VERSION_ALLOWED",
            FAKE_MINIMUM_QIBO_VERSION_ALLOWED,
        )
        endpoint = FAKE_URL + "/qibo_version/"
        response_json = {"qibo_version": FAKE_QIBO_VERSION}
        with responses.RequestsMock() as rsps:
            rsps.get(endpoint, status=200, json=response_json)
            yield rsps

    def test_init_method(self):
        assert self.obj.token == FAKE_TOKEN
        assert self.obj.base_url == FAKE_URL

        assert self.obj.pid is None
        assert self.obj.results_folder is None
        assert self.obj.results_path is None

    def test_check_client_server_qibo_versions_raises_assertion_error(
        self, monkeypatch
    ):
        monkeypatch.setattr(f"{MOD}.qibo.__version__", FAKE_QIBO_VERSION)
        monkeypatch.setattr(
            f"{MOD}.constants.MINIMUM_QIBO_VERSION_ALLOWED",
            "0.2.8",
        )

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
        monkeypatch.setattr(
            f"{MOD}.constants.MINIMUM_QIBO_VERSION_ALLOWED",
            FAKE_MINIMUM_QIBO_VERSION_ALLOWED,
        )
        endpoint = FAKE_URL + "/qibo_version/"
        response_json = {"qibo_version": "0.2.9"}
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        self.obj.check_client_server_qibo_versions()

        expected_log = (
            "Local Qibo package version does not match the server one, please "
            f"upgrade: {FAKE_QIBO_VERSION} -> 0.2.9"
        )
        assert expected_log in caplog.messages

    def test_run_circuit_with_invalid_token(self, pass_version_check):
        endpoint = FAKE_URL + "/run_circuit/"
        message = "User not found, specify the correct token"
        response_json = {"detail": message}
        pass_version_check.add(responses.POST, endpoint, status=404, json=response_json)

        with pytest.raises(exceptions.JobApiError) as err:
            self.obj.run_circuit(
                FAKE_CIRCUIT, FAKE_NSHOTS, FAKE_LAB_LOCATION, FAKE_DEVICE
            )

        expected_message = f"[404 Error] {message}"
        assert str(err.value) == expected_message

    def test_run_circuit_with_job_post_error(self, pass_version_check):
        endpoint = FAKE_URL + "/run_circuit/"
        message = "Server failed to post job to queue"
        response_json = {"detail": message}
        pass_version_check.add(responses.POST, endpoint, status=200, json=response_json)

        with pytest.raises(exceptions.JobPostServerError) as err:
            self.obj.run_circuit(
                FAKE_CIRCUIT, FAKE_NSHOTS, FAKE_LAB_LOCATION, FAKE_DEVICE
            )

        assert str(err.value) == message

    def test_run_circuit_with_success(self, pass_version_check, caplog):
        caplog.set_level(logging.INFO)
        endpoint = FAKE_URL + "/run_circuit/"
        response_json = {"pid": FAKE_PID}
        pass_version_check.add(responses.POST, endpoint, status=200, json=response_json)

        job = self.obj.run_circuit(
            FAKE_CIRCUIT, FAKE_NSHOTS, FAKE_LAB_LOCATION, FAKE_DEVICE
        )

        assert job.pid == FAKE_PID
        assert job.base_url == FAKE_URL
        assert job.circuit == "fakeCircuit"
        assert job.nshots == FAKE_NSHOTS
        assert job.lab_location == FAKE_LAB_LOCATION
        assert job.device == FAKE_DEVICE
        assert job._status is None

        expected_messages = [
            f"Job posted on server with pid {FAKE_PID}",
            f"Check results availability for {FAKE_PID} job in your reserved "
            f"page at {FAKE_URL}",
        ]
        for expected_message in expected_messages:
            assert expected_message in caplog.messages


# @pytest.fixture
# def results_base_folder(tmp_path: Path):
#     results_base_folder = tmp_path / "results"
#     results_base_folder.mkdir()
#     with patch(f"{PKG}.constants.RESULTS_BASE_FOLDER", results_base_folder):
#         yield results_base_folder


# def test__post_circuit_not_successful(mock_request: Mock):
#     def _new_side_effect(url, json, timeout):
#         json_data = {"pid": None, "message": "post job to queue failed"}
#         return utils.MockedResponse(status_code=200, json_data=json_data)

#     mock_request.post.side_effect = _new_side_effect

#     client = _get_local_client()
#     with pytest.raises(JobPostServerError):
#         client._post_circuit(utils.MockedCircuit())


# def test__run_circuit(mock_qibo, mock_request, mock_tempfile, results_base_folder):
#     expected_array_path = results_base_folder / FAKE_PID / "results.npy"

#     client = _get_local_client()
#     client.pid = FAKE_PID
#     result = client.run_circuit(utils.MockedCircuit())

#     assert result == expected_array_path


# def test__run_circuit_with_unsuccessful_post_to_queue(mock_request: Mock):
#     def _new_side_effect(url, json, timeout):
#         json_data = {"pid": None, "message": "post job to queue failed"}
#         return utils.MockedResponse(status_code=200, json_data=json_data)

#     mock_request.post.side_effect = _new_side_effect

#     client = _get_local_client()
#     return_value = client.run_circuit(utils.MockedCircuit())

#     assert return_value is None


# def test__run_circuit_without_waiting_for_results(mock_request: Mock):
#     def _new_side_effect(url, json, timeout):
#         json_data = {"pid": None, "message": "post job to queue failed"}
#         return utils.MockedResponse(status_code=200, json_data=json_data)

#     mock_request.post.side_effect = _new_side_effect

#     client = _get_tii_client()
#     return_value = client.run_circuit(utils.MockedCircuit(), wait_for_results=False)

#     assert return_value is None
