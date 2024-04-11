from .qibo_client import Client


def base_url():
    qrccluster_ip = os.environ.get("QRCCLUSTER_IP", "www.qrccluster.com")
    qrccluster_port = os.environ.get("QRCCLUSTER_PORT", "80")
    return f"http://{qrccluster_ip}:{qrccluster_port}/"


def TII(token: str) -> Client:
    """Instantiate a TII Client object.

    :param token: the authentication token associated to the webapp user
    :type token: str
    :return: the client instance connected to the TII server
    :rtype: Client
    """
    return Client(base_url(), token)
