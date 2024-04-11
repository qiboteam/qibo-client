from unittest.mock import Mock, patch

from qibo_client import tii

PKG = "qibo_client.tii"
FAKE_TOKEN = "fakeToken"


def test_base_url():
    assert tii.base_url() == "https://cloud.qibo.science/"


def fake_url():
    return "http://tii.url.com:1234"


@patch(f"{PKG}.base_url", fake_url)
@patch(f"{PKG}.Client.check_client_server_qibo_versions")
def test_TII(mock_method: Mock):
    client = tii.TII(FAKE_TOKEN)
    assert client.url == fake_url()
