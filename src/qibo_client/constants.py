"""Configuration constants for qibo-client behavior.

These constants control the default behavior of the client.
They can be overridden via environment variables.
"""

import os

SECONDS_BETWEEN_CHECKS = int(os.environ.get("SECONDS_BETWEEN_CHECKS", 2))
"""Default time interval between status checks for running jobs.


Environment variable:
    SECONDS_BETWEEN_CHECKS: Default is 2 seconds.
        Increase this value if you want less frequent polling.
"""


TIMEOUT = 60
"""Default timeout in seconds for API requests."""
