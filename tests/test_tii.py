from unittest.mock import Mock, patch

from qibo_client import tii

PKG = "qibo_client.tii"
FAKE_URL = "http://tii.url.com:1234"
FAKE_TOKEN = "fakeToken"


@patch(f"{PKG}.BASE_URL", FAKE_URL)
@patch(f"{PKG}.Client.check_client_server_qibo_versions")
def test_TII(mock_method: Mock):
    client = tii.TII(FAKE_TOKEN)
    assert client.url == FAKE_URL
