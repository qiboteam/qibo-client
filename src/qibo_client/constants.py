import os
from pathlib import Path

MINIMUM_QIBO_VERSION_ALLOWED = "0.2.4"

RESULTS_BASE_FOLDER = Path(os.environ.get("RESULTS_BASE_FOLDER", "/tmp/qibo_client"))
SECONDS_BETWEEN_CHECKS = os.environ.get("SECONDS_BETWEEN_CHECKS", 2)

TIMEOUT = 60
