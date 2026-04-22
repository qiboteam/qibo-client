"""Logging configuration for the qibo-client.

This module sets up the default logging configuration for the client.
The log level can be overridden via the QIBO_CLIENT_LOGGER_LEVEL environment variable.
"""

import logging
import os

# Configure basic logging format
logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Set the log level from environment variable or default to INFO
# Common levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
logging_level = os.environ.get("QIBO_CLIENT_LOGGER_LEVEL", logging.INFO)
logger.setLevel(logging_level)
