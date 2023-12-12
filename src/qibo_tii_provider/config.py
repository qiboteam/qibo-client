class MalformedResponseError(Exception):
    """Exception raised when server responsed body does not contain expected keys"""

    def __init__(
        self, message="Server response body does not contain all the expected keys"
    ):
        self.message = message
        super().__init__(self.message)
