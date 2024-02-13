"""The `qibo_tii_provider` package"""

import importlib.metadata as im

__version__ = im.version(__package__)

from .tii import TII
