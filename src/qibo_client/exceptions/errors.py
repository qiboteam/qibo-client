"""Exceptions module for qibo-client.

This module implements custom exceptions used throughout the client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MalformedResponseError(Exception):
    """Exception raised when server response body does not contain expected keys.

    This error indicates that the API response was malformed and did not contain
    the expected fields needed for proper processing.

    Attributes:
        message: A descriptive error message explaining what keys were missing
    """

    def __init__(
        self,
        message: str = "Server response body does not contain all the expected keys",
    ):
        self.message = message
        super().__init__(self.message)


class JobPostServerError(Exception):
    """Exception raised when server fails to post the job to the queue.

    This error indicates that the job was not successfully submitted to the server.
    The client should handle this gracefully to inform the user about the failed
    submission without crashing.

    Attributes:
        message: A descriptive error message about the failure
    """

    def __init__(self, message: str = "Server failed to post job to queue"):
        self.message = message
        super().__init__(self.message)


@dataclass
class QiboApiError(RuntimeError):
    """A clean, user-facing API error with no traceback noise.

    This exception provides a user-friendly error message extracted from API
    responses, making debugging easier for end users while maintaining technical
    details in the payload for advanced debugging purposes.

    Attributes:
        status: HTTP status code (0 for network layer errors)
        method: HTTP method string (GET/POST/DELETE)
        url: Full request URL that caused the error
        message: A friendly error message extracted from the response
        payload: Optional parsed JSON payload for debugging/advanced usage
    """

    status: int
    method: str
    url: str
    message: str
    payload: dict[str, Any] | None = None

    def __post_init__(self):
        # Keep the base Exception message concise by using just the message
        super().__init__(self.message)

    def summary(self) -> str:
        """Return a normalized, presentation-agnostic summary string.

        Returns:
            A summary string formatted as "[status] [message] ([method] [url])"
        """
        return f"[{self.status} Error] {self.message} ({self.method} {self.url})"

    def get_plain_message(self) -> str:
        """Backward-compatible helper used in tests/CLI fallbacks.

        Returns:
            The same summary string as summary(). Used to maintain backward compatibility.
        """
        return self.summary()
