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
    missing = set(keys) - response_keys
    if missing:
        raise MalformedResponseError(
            f"The server response is missing the following keys: {' '.join(missing)}"
        )


def _request_and_status_check(request_fn, *args, **kwargs) -> requests.Response:
    """
    Perform the HTTP request, then check status.
    On error, attempt to pull out JSON['detail'], but fall back to text.
    """
    response = request_fn(*args, **kwargs)
    if not response.ok:
        # Try JSON detail first
        detail = None
        try:
            payload = response.json()
            detail = payload.get("detail") or payload
        except (ValueError, TypeError):
            # not JSON or missing
            detail = response.text or f"HTTP {response.status_code}"
        raise JobApiError(response.status_code, detail)
    return response


def _make_request(
    request_fn, keys_to_check: T.Optional[T.List[str]], *args, **kwargs
) -> requests.Response:
    response = _request_and_status_check(request_fn, *args, **kwargs)
    if keys_to_check is not None:
        # Will raise MalformedResponseError if missing
        check_json_response_has_keys(response.json(), keys_to_check)
    return response


class QiboApiRequest:

    @staticmethod
    def get(
        endpoint: str,
        params: T.Optional[T.Dict] = None,
        headers: T.Optional[T.Dict] = None,
        timeout: T.Optional[float] = None,
        keys_to_check: T.Optional[T.List[str]] = None,
    ) -> requests.Response:
        return _make_request(
            requests.get,
            keys_to_check,
            endpoint,
            params=params,
            headers=headers,
            timeout=timeout,
        )

    @staticmethod
    def post(
        endpoint: str,
        headers: T.Optional[T.Dict] = None,
        json: T.Optional[T.Dict] = None,
        timeout: T.Optional[float] = None,
        keys_to_check: T.Optional[T.List[str]] = None,
    ) -> requests.Response:
        return _make_request(
            requests.post,
            keys_to_check,
            endpoint,
            headers=headers,
            json=json,
            timeout=timeout,
        )

    @staticmethod
    def delete(
        endpoint: str,
        timeout: T.Optional[float] = None,
        headers: T.Optional[T.Dict] = None,
        keys_to_check: T.Optional[T.List[str]] = None,
    ) -> requests.Response:
        return _make_request(
            requests.delete,
            keys_to_check,
            endpoint,
            headers=headers,
            timeout=timeout,
        )
