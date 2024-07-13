from typing import Callable
from unittest.mock import Mock, patch

import pytest
from requests.exceptions import HTTPError

from qibo_client import qibo_client
from qibo_client.exceptions import JobPostServerError, MalformedResponseError

PKG = "qibo_client.qibo_client"
LOCAL_URL = "http://localhost:8000/"
FAKE_QIBO_VERSION = "0.2.4"
FAKE_PID = "123"
TIMEOUT = 1


@pytest.fixture(autouse=True)
def mock_qibo():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.qibo") as _mock_qibo:
        _mock_qibo.__version__ = FAKE_QIBO_VERSION
        _mock_qibo.result.load_result.side_effect = lambda x: x
        yield _mock_qibo


@pytest.fixture(scope="module", autouse=True)
def mock_timeout():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.constants.TIMEOUT", TIMEOUT) as _fixture:
        yield _fixture


# @pytest.fixture
# def results_base_folder(tmp_path: Path):
#     results_base_folder = tmp_path / "results"
#     results_base_folder.mkdir()
#     with patch(f"{PKG}.constants.RESULTS_BASE_FOLDER", results_base_folder):
#         yield results_base_folder


def _get_request_side_effect(job_status: str = "success") -> Callable:
    """Return a callable mock for the get request function

    Job status parameter controls the response header of `get_result/{pid}`
    endpoint.

    :param job_status: the Job-Status header of the mocked response
    :type job_status: str

    :return: the get request side effect function
    :rtype: Callable
    """

    def _request_side_effect(url, timeout):
        if url == LOCAL_URL + "qibo_version/":
            return utils.MockedResponse(
                status_code=200,
                json_data={"qibo_version": FAKE_QIBO_VERSION},
            )
        if url == LOCAL_URL + f"get_result/{FAKE_PID}/":
            stream, _, _ = utils.get_in_memory_fake_archive_stream()
            json_data = {
                "content": None,
                "iter_content": stream,
                "headers": {"Job-Status": job_status},
            }
            return utils.MockedResponse(status_code=200, json_data=json_data)

    return _request_side_effect


def _post_request_side_effect(url, json, timeout):
    if url == LOCAL_URL + "run_circuit/":
        json_data = {"pid": FAKE_PID, "message": "Success. Job posted"}
        return utils.MockedResponse(status_code=200, json_data=json_data)


@pytest.fixture
def mock_request():
    with patch(f"{PKG}.requests") as _mock_request:
        _mock_request.get.side_effect = _get_request_side_effect()
        _mock_request.post.side_effect = _post_request_side_effect
        yield _mock_request


def _get_local_client():
    return qibo_client.Client("valid_token", LOCAL_URL)


def test_check_client_server_qibo_versions_with_version_match(mock_request: Mock):
    _get_local_client()
    mock_request.get.assert_called_once_with(
        LOCAL_URL + "qibo_version/", timeout=TIMEOUT
    )


def test_check_client_server_qibo_versions_with_version_mismatch(
    mock_qibo: Mock, mock_request: Mock
):
    mock_qibo.__version__ = "0.2.1"
    with (
        patch(f"{PKG}.constants.MINIMUM_QIBO_VERSION_ALLOWED", "0.1.9"),
        patch(f"{PKG}.logger") as mock_logger,
    ):
        _get_local_client()
    mock_logger.warning.assert_called_once()


def test_check_client_server_qibo_versions_with_low_local_version(mock_qibo: Mock):
    mock_qibo.__version__ = "0.0.1"
    with pytest.raises(AssertionError):
        _get_local_client()


def test__post_circuit_with_invalid_token(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        return utils.MockedResponse(status_code=404)

    mock_request.post.side_effect = _new_side_effect

    client = _get_local_client()
    with pytest.raises(HTTPError):
        client._post_circuit(utils.MockedCircuit())


def test__post_circuit_not_successful(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        json_data = {"pid": None, "message": "post job to queue failed"}
        return utils.MockedResponse(status_code=200, json_data=json_data)

    mock_request.post.side_effect = _new_side_effect

    client = _get_local_client()
    with pytest.raises(JobPostServerError):
        client._post_circuit(utils.MockedCircuit())


def test__run_circuit(mock_qibo, mock_request, mock_tempfile, results_base_folder):
    expected_array_path = results_base_folder / FAKE_PID / "results.npy"

    client = _get_local_client()
    client.pid = FAKE_PID
    result = client.run_circuit(utils.MockedCircuit())

    assert result == expected_array_path


def test__run_circuit_with_unsuccessful_post_to_queue(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        json_data = {"pid": None, "message": "post job to queue failed"}
        return utils.MockedResponse(status_code=200, json_data=json_data)

    mock_request.post.side_effect = _new_side_effect

    client = _get_local_client()
    return_value = client.run_circuit(utils.MockedCircuit())

    assert return_value is None


def test__run_circuit_without_waiting_for_results(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        json_data = {"pid": None, "message": "post job to queue failed"}
        return utils.MockedResponse(status_code=200, json_data=json_data)

    mock_request.post.side_effect = _new_side_effect

    client = _get_tii_client()
    return_value = client.run_circuit(utils.MockedCircuit(), wait_for_results=False)

    assert return_value is None
