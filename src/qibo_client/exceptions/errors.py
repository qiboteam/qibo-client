"""This module implements some constants and custom exceptions"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MalformedResponseError(Exception):
    """Exception raised when server responsed body does not contain expected keys"""

    def __init__(
        self,
        message: str = "Server response body does not contain all the expected keys",
    ):
        self.message = message
        super().__init__(self.message)


class JobPostServerError(Exception):
    """Exception raised when server fails to post the job to the queue.

    The client should handle such error to aknowledge that job submission was
    not successful without crashing.
    """

    def __init__(self, message: str = "Server failed to post job to queue"):
        self.message = message
        super().__init__(self.message)


@dataclass
class QiboApiError(RuntimeError):
    """Clean, user-facing API error (no traceback noise).

    Attributes:
        status: HTTP status code (0 for network layer errors)
        method: HTTP method string (GET/POST/DELETE)
        url: full request URL
        message: a friendly error message extracted from the response
        payload: optional parsed JSON payload (dict) for debugging/advanced usage
    """

    status: int
    method: str
    url: str
    message: str
    payload: dict[str, Any] | None = None

    def __post_init__(self):
        # Keep the base Exception message concise
        super().__init__(self.message)

    def summary(self) -> str:
        """Return a normalized, presentation-agnostic summary string."""
        return f"[{self.status} Error] {self.message} ({self.method} {self.url})"

    def get_plain_message(self) -> str:
        """Backward-compatible helper used in tests/CLI fallbacks."""
        return self.summary()
