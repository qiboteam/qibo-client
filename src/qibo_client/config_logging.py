import logging
import os

# configure logger
logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
logging_level = os.environ.get("QIBO_CLIENT_LOGGER_LEVEL", logging.INFO)
logger.setLevel(logging_level)
