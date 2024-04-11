import os

from .qibo_client import Client


def base_url():
    qrccluster_ip = os.getenv("QRCCLUSTER_IP", "cloud.qibo.science")
    qrccluster_port = os.getenv("QRCCLUSTER_PORT", "443")
    return f"https://{qrccluster_ip}:{qrccluster_port}/"


def TII(token: str) -> Client:
    """Instantiate a TII Client object.

    :param token: the authentication token associated to the webapp user
    :type token: str
    :return: the client instance connected to the TII server
    :rtype: Client
    """
    return Client(base_url(), token)
