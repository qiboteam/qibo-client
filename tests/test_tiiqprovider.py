from pathlib import Path
import tarfile
from unittest.mock import patch, Mock

import pytest
from requests.exceptions import HTTPError

import tests.utils_test_tiiqprovider as utils

from qibo_tii_provider import tiiprovider
from qibo_tii_provider.config import MalformedResponseError, JobPostServerError

PKG = "qibo_tii_provider.tiiprovider"
LOCAL_URL = "http://localhost:8000/"
FAKE_QIBO_VERSION = "0.0.1"


@pytest.fixture(autouse=True)
def mock_qrccluster_ip():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.BASE_URL", LOCAL_URL) as _fixture:
        yield _fixture


@pytest.fixture(autouse=True)
def mock_local_qibo_version():
    """Ensure that all the requests are made on localhost"""
    with patch(f"{PKG}.qibo.__version__", FAKE_QIBO_VERSION) as _fixture:
        yield _fixture


@pytest.fixture
def mock_request():
    """Returns a mocked get request"""
    with patch(f"{PKG}.requests") as _mock_request:
        yield _mock_request


def test_check_response_has_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0, "key2": 1}
    status_code = 200
    mock_response = utils.MockedResponse(status_code, json_data)
    tiiprovider.check_response_has_keys(mock_response, keys)


def test_check_response_has_missing_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json_data = {"key1": 0}
    status_code = 200
    mock_response = utils.MockedResponse(status_code, json_data)
    with pytest.raises(MalformedResponseError):
        tiiprovider.check_response_has_keys(mock_response, keys)


def _get_tii_client():
    return tiiprovider.TIIProvider("valid_token")


def _execute_check_client_server_qibo_versions(
    mock_request, local_qibo_version, remote_qibo_version
):
    mock_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": remote_qibo_version}
    )
    mock_request.get.return_value = mock_response

    with patch(f"{PKG}.qibo.__version__", local_qibo_version):
        _get_tii_client()


def test_check_client_server_qibo_versions_with_version_match(mock_request: Mock):
    _execute_check_client_server_qibo_versions(
        mock_request, FAKE_QIBO_VERSION, FAKE_QIBO_VERSION
    )

    mock_request.get.assert_called_once_with(LOCAL_URL + "qibo_version/")


def test_check_client_server_qibo_versions_with_version_mismatch(mock_request):
    remote_qibo_version = "0.2.2"

    with pytest.raises(AssertionError):
        _execute_check_client_server_qibo_versions(
            mock_request, FAKE_QIBO_VERSION, remote_qibo_version
        )

    mock_request.get.assert_called_once_with(LOCAL_URL + "qibo_version/")


def test__post_circuit_with_invalid_token(mock_request: Mock):
    mock_get_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    mock_post_response = utils.MockedResponse(status_code=404)
    mock_request.post.return_value = mock_post_response

    client = _get_tii_client()
    with pytest.raises(HTTPError):
        client._post_circuit(utils.MockedCircuit())


def test__post_circuit_not_successful(mock_request: Mock):
    mock_get_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    json_data = {"pid": None, "message": "post job to queue failed"}
    mock_post_response = utils.MockedResponse(status_code=200, json_data=json_data)
    mock_request.post.return_value = mock_post_response

    client = _get_tii_client()
    with pytest.raises(JobPostServerError):
        client._post_circuit(utils.MockedCircuit())


def test__run_circuit_with_unsuccessful_post_to_queue(mock_request: Mock):
    mock_get_response = utils.MockedResponse(
        status_code=200, json_data={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    json_data = {"pid": None, "message": "post job to queue failed"}
    mock_post_response = utils.MockedResponse(status_code=200, json_data=json_data)
    mock_request.post.return_value = mock_post_response

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
        tiiprovider.wait_for_response_to_get_request(url)

    assert mock_request.get.call_count == failed_attempts + 1


# STREAM = ["line1\n", "line2\n"]
ARCHIVE_NAME = "file.tar.gz"


@patch(f"{PKG}.tempfile")
def test__write_stream_to_tmp_file_with_simple_text_stream(
    mock_tempfile: Mock, tmp_path: Path
):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    stream = [b"line1\n", b"line2\n"]
    file_path = tmp_path / ARCHIVE_NAME

    mock_tempfile.NamedTemporaryFile = utils.get_fake_tmp_file_class(file_path)

    assert not file_path.is_file()

    result_path = tiiprovider._write_stream_to_tmp_file(stream)

    assert result_path == file_path
    assert result_path.is_file()

    assert result_path.read_bytes() == b"".join(stream)


@patch(f"{PKG}.tempfile")
def test__write_stream_to_tmp_file(mock_tempfile: Mock, tmp_path: Path):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    file_path = tmp_path / ARCHIVE_NAME
    stream, members, members_contents = utils.get_in_memory_fake_archive_stream(
        file_path
    )

    mock_tempfile.NamedTemporaryFile = utils.get_fake_tmp_file_class(file_path)

    assert not file_path.is_file()

    result_path = tiiprovider._write_stream_to_tmp_file(stream)

    assert result_path == file_path
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

    destination_folder = tmp_path / "destination_folder"
    destination_folder.mkdir()

    with pytest.raises(tarfile.TarError):
        tiiprovider._extract_archive_to_folder(file_path, destination_folder)


def test__extract_archive_to_folder(tmp_path):
    archive_path = tmp_path / ARCHIVE_NAME
    destination_folder = tmp_path / "destination_folder"
    destination_folder.mkdir()

    members, members_contents = utils.create_fake_archive(archive_path)

    tiiprovider._extract_archive_to_folder(archive_path, destination_folder)

    result_members = []
    result_members_contents = []
    for member_path in sorted(destination_folder.iterdir()):
        result_members.append(member_path.name)
        result_members_contents.append(member_path.read_bytes())

    assert result_members == members
    assert result_members_contents == members_contents


@patch(f"{PKG}.tempfile")
def test__save_and_unpack_stream_response_to_folder(
    mock_tempfile: Mock, tmp_path: Path
):
    file_path = tmp_path / ARCHIVE_NAME
    destination_folder = tmp_path / "destination_folder"
    destination_folder.mkdir()

    mock_tempfile.NamedTemporaryFile = utils.get_fake_tmp_file_class(file_path)

    stream, _, _ = utils.get_in_memory_fake_archive_stream(file_path)

    assert not file_path.is_file()

    tiiprovider._save_and_unpack_stream_response_to_folder(stream, destination_folder)

    # the archive should have been removed
    assert not file_path.is_file()


