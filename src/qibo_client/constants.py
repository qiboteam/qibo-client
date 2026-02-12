import os
from pathlib import Path

from .config_logging import logger

RESULTS_BASE_FOLDER = Path(os.environ.get("RESULTS_BASE_FOLDER", "/tmp/qibo_client"))
SECONDS_BETWEEN_CHECKS = os.environ.get("SECONDS_BETWEEN_CHECKS", 2)
TIMEOUT = 60
