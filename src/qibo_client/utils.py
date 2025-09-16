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
    On error, extract a clean error message from the response.
    """
    try:
        response = request_fn(*args, **kwargs)
        if not response.ok:
            # Try to extract a clean error message from the response
            error_message = None
            try:
                payload = response.json()
                # Try to get the most specific error message available
                error_message = (
                    payload.get("detail")
                    or payload.get("error")
                    or payload.get("message")
                    or str(payload)  # Fall back to string representation of the payload
                )
            except (ValueError, TypeError, AttributeError):
                # If we can't parse JSON, use the response text or status code
                error_message = (
                    response.text.strip() or f"Error: HTTP {response.status_code}"
                )

            # Clean up the error message if it's a string representation of a dict/list
            if isinstance(error_message, str) and error_message.startswith(("{", "[")):
                try:
                    import json

                    parsed = json.loads(error_message)
                    if isinstance(parsed, dict):
                        error_message = (
                            parsed.get("detail") or parsed.get("error") or str(parsed)
                        )
                    else:
                        error_message = str(parsed)
                except (ValueError, TypeError, AttributeError):
                    pass

            raise JobApiError(response.status_code, str(error_message).strip())
        return response
    except requests.exceptions.RequestException as e:
        # Handle connection errors, timeouts, etc.
        error_msg = str(e)
        if not error_msg or "HTTPSConnectionPool" in error_msg:
            error_msg = "Could not connect to the server. Please check your internet connection and try again."
        raise JobApiError(0, error_msg) from None


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
