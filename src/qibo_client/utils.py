from __future__ import annotations

import typing as T

import requests

from .exceptions import MalformedResponseError, QiboApiError


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


def _extract_clean_message(
    response: requests.Response,
) -> tuple[str, T.Optional[T.Dict]]:
    """Best-effort extraction of a single, user-friendly error string and optional dict payload."""
    data = None
    message = None
    # Try JSON first
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        # common API fields
        for key in ("detail", "message", "error", "title"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                message = val.strip()
                break
        if message is None and "errors" in data:
            message = str(data["errors"])
    if not message:
        # fallbacks
        txt = (response.text or "").strip()
        message = txt if txt else f"HTTP {response.status_code}"

    return message, data if isinstance(data, dict) else None


def _request_and_status_check(request_fn, *args, **kwargs) -> requests.Response:
    """
    Perform the HTTP request, then check status.
    On error, raise QiboApiError with a clean message (no stack trace at call sites that catch it).
    """
    try:
        response: requests.Response = request_fn(*args, **kwargs)
        if not response.ok:
            msg, payload = _extract_clean_message(response)
            method = (
                getattr(getattr(response, "request", None), "method", "GET") or "GET"
            )
            url = getattr(response, "url", args[0] if args else "unknown")
            raise QiboApiError(
                status=response.status_code,
                method=method,
                url=url,
                message=msg,
                payload=payload,
            )
        return response
    except requests.exceptions.RequestException as e:
        # Network / timeout / DNS etc.
        method = kwargs.get("method") or getattr(
            getattr(e, "request", None), "method", "GET"
        )
        url = kwargs.get("url") or (args[0] if args else "unknown")
        error_msg = str(e).strip() or "Could not connect to the server."
        raise QiboApiError(
            status=0,
            method=method,
            url=url,
            message=error_msg,
            payload=None,
        )


def _make_server_request(
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
    ) -> T.Optional[requests.Response]:
        return _make_server_request(
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
    ) -> T.Optional[requests.Response]:
        return _make_server_request(
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
    ) -> T.Optional[requests.Response]:
        return _make_server_request(
            requests.delete,
            keys_to_check,
            endpoint,
            headers=headers,
            timeout=timeout,
        )
