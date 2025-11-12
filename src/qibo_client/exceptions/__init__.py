# __init__.py
# Auto-install by default, but allow users/environments to opt out.
# Recognize common "false" values and avoid crashing if install fails.
import os

from .errors import JobPostServerError, MalformedResponseError, QiboApiError
from .hooks import (
    install_qibo_error_hooks,
    qibo_error_hooks,
    uninstall_qibo_error_hooks,
)

_AUTO = os.getenv("QIBO_API_ERRORS_AUTO", "1").lower() not in {
    "0",
    "false",
    "off",
    "no",
}
if _AUTO:
    try:
        install_qibo_error_hooks()
    except Exception:
        # Never let hook setup break imports
        pass

__all__ = [
    "QiboApiError",
    "MalformedResponseError",
    "JobPostServerError",
    "install_qibo_error_hooks",
    "uninstall_qibo_error_hooks",
    "qibo_error_hooks",
]
