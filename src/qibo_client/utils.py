import typing as T

import requests

from .exceptions import JobApiError, MalformedResponseError


def check_json_response_has_keys(response_json: T.Dict, keys: T.List[str]):
    """Check that the response body contains certain keys.

    :param response_json: the server json response
    :type response_json: Dict
    :param keys: the keys to be checked in the response body
    :type keys: List[str]

    :raises MalformedResponseError:
        if the server response does not contain all the expected keys.
    """
    response_keys = set(response_json.keys())
    expected_keys = set(keys)
    missing_keys = expected_keys.difference(response_keys)

    if len(missing_keys):
        raise MalformedResponseError(
            f"The server response is missing the following keys: {' '.join(missing_keys)}"
        )


def _request_and_status_check(request_fn, *args, **kwargs):
    try:
        response = request_fn(*args, **kwargs)
        response.raise_for_status()
    except requests.HTTPError:
        raise JobApiError(response.status_code, response.json().get("detail"))

    return response


def _make_request(request_fn, keys_to_check, *args, **kwargs) -> requests.Response:
    response = _request_and_status_check(request_fn, *args, **kwargs)
    if keys_to_check is not None:
        check_json_response_has_keys(response.json(), keys_to_check)
    return response


class QiboApiRequest:

    @staticmethod
    def get(
        endpoint: str,
        params: T.Optional[T.Dict] = None,
        timeout: T.Optional[float] = None,
        keys_to_check: T.Optional[T.List[str]] = None,
    ) -> requests.Response:
        return _make_request(
            requests.get, keys_to_check, endpoint, params=params, timeout=timeout
        )

    @staticmethod
    def post(
        endpoint: str,
        json: T.Optional[T.Dict] = None,
        timeout: T.Optional[float] = None,
        keys_to_check: T.Optional[T.List[str]] = None,
    ) -> requests.Response:
        return _make_request(
            requests.post, keys_to_check, endpoint, json=json, timeout=timeout
        )
