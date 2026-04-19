"""Utility functions and API request handling.

This module provides shared utility functions for HTTP request handling,
error processing, and JSON response validation.
"""

from __future__ import annotations

import typing as T

import requests

from .exceptions import MalformedResponseError, QiboApiError


def check_json_response_has_keys(response_json: T.Dict, keys: T.List[str]):
    """Check that the response body contains certain keys.

    Validates that all required keys are present in the JSON response.
    Raises a MalformedResponseError if any keys are missing.

    Args:
        response_json: The dictionary parsed from JSON response
        keys: List of required key names

    Raises:
        MalformedResponseError: If any keys are missing from the response
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
    """Extract a clean, user-friendly error message and optional payload.

    This function attempts to extract a meaningful error message from
    various possible response formats including JSON errors, text errors,
    and HTTP status-based messages.

    Args:
        response: The requests.Response object

    Returns:
        Tuple of (error_message, data_payload) where data_payload is dict or None
    """
    data = None
    message = None

    # Try to parse JSON response
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        # Priority order for error message fields in JSON response
        for key in ("detail", "message", "error", "title"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                message = val.strip()
                break
        if message is None and "errors" in data:
            message = str(data["errors"])

    # Fallback to plain text
    if not message:
        txt = (response.text or "").strip()
        message = txt if txt else f"HTTP {response.status_code}"

    return message, data if isinstance(data, dict) else None


def _request_and_status_check(request_fn, *args, **kwargs) -> requests.Response:
    """Perform HTTP request and handle status checks and errors.

    Executes the HTTP request and checks the response status. If the request
    fails, creates a QiboApiError with appropriate context including method,
    URL, status code, and error message.

    Args:
        request_fn: The requests method to use (get, post, delete)
        *args: Positional arguments for the request
        **kwargs: Keyword arguments for the request

    Returns:
        The successful requests.Response object

    Raises:
        QiboApiError: If the response status is not OK or network error occurs
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
        # Handle network/timeout/DNS errors
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
    """Make an HTTP request with key validation.

    This is a wrapper function that combines request execution with response
    body validation. It ensures the response contains expected keys before
    returning it to the caller.

    Args:
        request_fn: The requests method to use
        keys_to_check: Optional list of required keys to check in response
        *args: Positional arguments for the request
        **kwargs: Keyword arguments for the request

    Returns:
        The successful requests.Response object

    Raises:
        MalformedResponseError: If response is missing expected keys
        QiboApiError: If request fails
    """
    response = _request_and_status_check(request_fn, *args, **kwargs)
    if keys_to_check is not None:
        # Validate response contains required keys
        check_json_response_has_keys(response.json(), keys_to_check)
    return response


class QiboApiRequest:
    """Interface for making HTTP requests to the Qibo server.

    This class provides static methods for making authenticated API requests
    to the Qibo server. All requests respect timeout and authentication headers.
    """

    @staticmethod
    def get(
        endpoint: str,
        params: T.Optional[T.Dict] = None,
        headers: T.Optional[T.Dict] = None,
        timeout: T.Optional[float] = None,
        keys_to_check: T.Optional[T.List[str]] = None,
    ) -> T.Optional[requests.Response]:
        """Make a GET request to the server.

        Args:
            endpoint: API endpoint path (without base URL)
            params: Query parameters for the request
            headers: HTTP headers for authentication
            timeout: Request timeout in seconds
            keys_to_check: Optional list of required keys in response body

        Returns:
            Response object or None
        """
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
        """Make a POST request to the server.

        Args:
            endpoint: API endpoint path (without base URL)
            headers: HTTP headers for authentication
            json: JSON payload for the request
            timeout: Request timeout in seconds
            keys_to_check: Optional list of required keys in response body

        Returns:
            Response object or None
        """
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
        """Make a DELETE request to the server.

        Args:
            endpoint: API endpoint path (without base URL)
            timeout: Request timeout in seconds
            headers: HTTP headers for authentication
            keys_to_check: Optional list of required keys in response body

        Returns:
            Response object or None
        """
        return _make_server_request(
            requests.delete,
            keys_to_check,
            endpoint,
            headers=headers,
            timeout=timeout,
        )
