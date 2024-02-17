import os

from .qibo_client import Client

QRCCLUSTER_IP = os.environ.get("QRCCLUSTER_IP", "www.qrccluster.com")
QRCCLUSTER_PORT = os.environ.get("QRCCLUSTER_PORT", "80")
BASE_URL = f"http://{QRCCLUSTER_IP}:{QRCCLUSTER_PORT}/"


def TII(token: str) -> Client:
    """Instantiate a TII Client object.

    :param token: the authentication token associated to the webapp user
    :type token: str

    :return: the client instance connected to the TII server
    :rtype: Client
    """
    return Client(BASE_URL, token)
