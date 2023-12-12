from typing import Dict, Optional
from unittest.mock import patch, Mock

from requests.exceptions import HTTPError

import pytest

from qibo_tii_provider import tiiprovider
from qibo_tii_provider.config import MalformedResponseError

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


class MockedResponse:
    def __init__(self, status_code: int, json: Optional[Dict] = None):
        self.status_code = status_code
        self._json = json

    def json(self):
        return self._json

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise HTTPError


def test_check_response_has_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json = {"key1": 0, "key2": 1}
    status_code = 200
    mock_response = MockedResponse(status_code, json)
    tiiprovider.check_response_has_keys(mock_response, keys)


def test_check_response_has_missing_keys():
    """Check response body contains the keys"""
    keys = ["key1", "key2"]
    json = {"key1": 0}
    status_code = 200
    mock_response = MockedResponse(status_code, json)
    with pytest.raises(MalformedResponseError):
        tiiprovider.check_response_has_keys(mock_response, keys)


def _get_tii_client():
    return tiiprovider.TIIProvider("valid_token")


def _execute_check_client_server_qibo_versions(
    mock_request, local_qibo_version, remote_qibo_version
):
    mock_response = MockedResponse(
        status_code=200, json={"qibo_version": remote_qibo_version}
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


class MockedCircuit:
    def __init__(self):
        self.raw = "raw circuit representation"


def test___post_circuit_with_invalid_token(mock_request: Mock):
    mock_get_response = MockedResponse(
        status_code=200, json={"qibo_version": FAKE_QIBO_VERSION}
    )
    mock_request.get.return_value = mock_get_response

    # simulate 404 error due to invalid token
    mock_post_response = MockedResponse(status_code=404)
    mock_request.post.return_value = mock_post_response

    client = _get_tii_client()
    with pytest.raises(HTTPError):
        client._post_circuit(MockedCircuit())
