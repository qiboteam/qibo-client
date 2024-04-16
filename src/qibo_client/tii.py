from .qibo_client import Client


def base_url():
    return "https://cloud.qibo.science/"


def TII(token: str) -> Client:
    """Instantiate a TII Client object.

    :param token: the authentication token associated to the webapp user
    :type token: str
    :return: the client instance connected to the TII server
    :rtype: Client
    """
    return Client(base_url(), token)
