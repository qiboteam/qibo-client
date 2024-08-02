"""The `qibo-client` package"""

import importlib.metadata as im

__version__ = im.version(__package__)

from .qibo_client import Client
from .qibo_job import QiboJob, QiboJobStatus
