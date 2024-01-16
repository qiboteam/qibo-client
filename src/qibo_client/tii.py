import os

from .qibo_client import Client

QRCCLUSTER_IP = os.environ.get("QRCCLUSTER_IP", "www.qrccluster.com")
BASE_URL = f"http://{QRCCLUSTER_IP}/"


def TII(token: str) -> Client:
    """Instantiate a TII Client object.

    :param token: the authentication token associated to the webapp user
    :type token: str

    :return: the client instance connected to the TII server
    :rtype: Client
    """
    return Client(BASE_URL, token)
