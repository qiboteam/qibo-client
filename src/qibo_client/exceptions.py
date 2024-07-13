"""This module implements some constants and custom exceptions"""


class MalformedResponseError(Exception):
    """Exception raised when server responsed body does not contain expected keys"""

    def __init__(
        self, message="Server response body does not contain all the expected keys"
    ):
        self.message = message
        super().__init__(self.message)


class JobPostServerError(Exception):
    """Exception raised when server fails to post the job to the queue.

    The client should handle such error to aknowledge that job submission was
    not successful without crashing.
    """

    def __init__(self, message="Server failed to post job to queue"):
        self.message = message
        super().__init__(self.message)


class JobApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        self.displayed_message = f"[{self.status_code} Error] {self.message}"
        super().__init__(self.displayed_message)
