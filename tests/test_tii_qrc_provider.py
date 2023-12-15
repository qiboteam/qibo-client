import tarfile
from pathlib import Path
from typing import Callable
from unittest.mock import Mock, patch

import pytest
from requests.exceptions import HTTPError

import utils_test_tii_qrc_provider as utils
from qibo_tii_provider import tii_qrc_provider
from qibo_tii_provider.config import JobPostServerError, MalformedResponseError

PKG = "qibo_tii_provider.tii_qrc_provider"
LOCAL_URL = "http://localhost:8000/"
FAKE_QIBO_VERSION = "0.0.1"
FAKE_PID = "123"
ARCHIVE_NAME = "file.tar.gz"
TIMEOUT = 1


@pytest.fixture(autouse=True)
def mock_qrccluster_ip():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.BASE_URL", LOCAL_URL) as _fixture:
        yield _fixture


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
    with patch(f"{PKG}.TIMEOUT", TIMEOUT) as _fixture:
        yield _fixture


@pytest.fixture
def results_base_folder(tmp_path: Path):
    results_base_folder = tmp_path / "results"
    results_base_folder.mkdir()
    with patch(f"{PKG}.RESULTS_BASE_FOLDER", results_base_folder):
        yield results_base_folder


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


@pytest.fixture
def archive_path(tmp_path):
    return tmp_path / ARCHIVE_NAME


@pytest.fixture
def mock_tempfile(archive_path):
    with patch(f"{PKG}.tempfile") as _mock_tempfile:
        _mock_tempfile.NamedTemporaryFile = utils.get_fake_tmp_file_class(archive_path)
        yield _mock_tempfile


def test_check_response_has_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0, "key2": 1}
    status_code = 200
    mock_response = utils.MockedResponse(status_code, json_data)
    tii_qrc_provider.check_response_has_keys(mock_response, keys)


def test_check_response_has_missing_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0}
    status_code = 200
    mock_response = utils.MockedResponse(status_code, json_data)
    with pytest.raises(MalformedResponseError):
        tii_qrc_provider.check_response_has_keys(mock_response, keys)


def _get_tii_client():
    return tii_qrc_provider.TIIProvider("valid_token")


def test_check_client_server_qibo_versions_with_version_match(mock_request: Mock):
    _get_tii_client()
    mock_request.get.assert_called_once_with(
        LOCAL_URL + "qibo_version/", timeout=TIMEOUT
    )


def test_check_client_server_qibo_versions_with_version_mismatch(mock_request: Mock):
    remote_qibo_version = "0.2.2"

    def _new_side_effect(url, timeout):
        return utils.MockedResponse(
            status_code=200, json_data={"qibo_version": remote_qibo_version}
        )

    mock_request.get.side_effect = _new_side_effect

    with pytest.raises(AssertionError):
        _get_tii_client()

    mock_request.get.assert_called_once_with(
        LOCAL_URL + "qibo_version/", timeout=TIMEOUT
    )


def test__post_circuit_with_invalid_token(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        return utils.MockedResponse(status_code=404)

    mock_request.post.side_effect = _new_side_effect

    client = _get_tii_client()
    with pytest.raises(HTTPError):
        client._post_circuit(utils.MockedCircuit())


def test__post_circuit_not_successful(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        json_data = {"pid": None, "message": "post job to queue failed"}
        return utils.MockedResponse(status_code=200, json_data=json_data)

    mock_request.post.side_effect = _new_side_effect

    client = _get_tii_client()
    with pytest.raises(JobPostServerError):
        client._post_circuit(utils.MockedCircuit())


def test__run_circuit_with_unsuccessful_post_to_queue(mock_request: Mock):
    def _new_side_effect(url, json, timeout):
        json_data = {"pid": None, "message": "post job to queue failed"}
        return utils.MockedResponse(status_code=200, json_data=json_data)

    mock_request.post.side_effect = _new_side_effect

    client = _get_tii_client()
    return_value = client.run_circuit(utils.MockedCircuit())

    assert return_value is None


def test_wait_for_response_to_get_request(mock_request: Mock):
    failed_attempts = 3
    url = "http://example.url"

    keep_waiting = utils.MockedResponse(
        status_code=200, json_data={"content": b"Job still in progress"}
    )
    job_done = utils.MockedResponse(status_code=200)

    mock_request.get.side_effect = [keep_waiting] * failed_attempts + [job_done]

    with patch(f"{PKG}.SECONDS_BETWEEN_CHECKS", 1e-4):
        tii_qrc_provider.wait_for_response_to_get_request(url)

    assert mock_request.get.call_count == failed_attempts + 1


def test__write_stream_to_tmp_file_with_simple_text_stream(
    mock_tempfile: Mock, archive_path: Path
):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    stream = [b"line1\n", b"line2\n"]

    assert not archive_path.is_file()

    result_path = tii_qrc_provider._write_stream_to_tmp_file(stream)

    assert result_path == archive_path
    assert result_path.is_file()
    assert result_path.read_bytes() == b"".join(stream)


def test__write_stream_to_tmp_file(mock_tempfile: Mock, archive_path: Path):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    stream, members, members_contents = utils.get_in_memory_fake_archive_stream()

    assert not archive_path.is_file()

    result_path = tii_qrc_provider._write_stream_to_tmp_file(stream)

    assert result_path == archive_path
    assert result_path.is_file()

    # load the archive in memory and check that the members and the contents
    # match with the expected ones
    with tarfile.open(result_path, "r:gz") as archive:
        result_members = sorted(archive.getnames())
        assert result_members == members
        for member, member_content in zip(members, members_contents):
            with archive.extractfile(member) as result_member:
                result_content = result_member.read()
            assert result_content == member_content


def test__extract_archive_to_folder_with_non_archive_input(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("test content")

    with pytest.raises(tarfile.ReadError):
        tii_qrc_provider._extract_archive_to_folder(file_path, tmp_path)


@patch(
    f"{PKG}._save_and_unpack_stream_response_to_folder", utils.raise_tarfile_readerror
)
def test__get_result_handles_tarfile_readerror(mock_request, results_base_folder):
    file_path = results_base_folder / "file.txt"
    file_path.write_text("test content")

    client = _get_tii_client()
    result = client.run_circuit(utils.MockedCircuit())

    assert result is None


def test__extract_archive_to_folder(archive_path, results_base_folder):
    members, members_contents = utils.create_fake_archive(archive_path)

    tii_qrc_provider._extract_archive_to_folder(archive_path, results_base_folder)

    result_members = []
    result_members_contents = []
    for member_path in sorted(results_base_folder.iterdir()):
        result_members.append(member_path.name)
        result_members_contents.append(member_path.read_bytes())

    assert result_members == members
    assert result_members_contents == members_contents


def test__save_and_unpack_stream_response_to_folder(
    mock_tempfile: Mock, archive_path: Path, results_base_folder: Path
):
    stream, _, _ = utils.get_in_memory_fake_archive_stream()

    assert not archive_path.is_file()

    tii_qrc_provider._save_and_unpack_stream_response_to_folder(
        stream, results_base_folder
    )

    # the archive should have been removed
    assert not archive_path.is_file()


def test__get_result(mock_qibo, mock_request, mock_tempfile, results_base_folder):
    expected_array_path = results_base_folder / FAKE_PID / "results.npy"

    client = _get_tii_client()
    client.pid = FAKE_PID
    result = client._get_result()

    mock_qibo.result.load_result.assert_called_once_with(expected_array_path)
    assert result == expected_array_path


def test__get_result_with_job_status_error(
    mock_qibo, mock_request, mock_tempfile, results_base_folder
):
    mock_request.get.side_effect = _get_request_side_effect(job_status="error")

    client = _get_tii_client()
    client.pid = FAKE_PID
    result = client._get_result()

    mock_qibo.result.load_result.assert_not_called()
    assert result is None


def test__run_circuit(mock_qibo, mock_request, mock_tempfile, results_base_folder):
    expected_array_path = results_base_folder / FAKE_PID / "results.npy"

    client = _get_tii_client()
    client.pid = FAKE_PID
    result = client.run_circuit(utils.MockedCircuit())

    assert result == expected_array_path
