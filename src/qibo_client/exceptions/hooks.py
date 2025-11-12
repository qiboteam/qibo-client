import asyncio
import importlib
import sys
import threading
import weakref
from contextlib import contextmanager

from ..ui.error_renderers import print_api_error
from .errors import QiboApiError

_prev_sys_excepthook = None
_prev_threading_excepthook = None
_prev_asyncio_handlers = weakref.WeakKeyDictionary()  # loop -> previous handler
_installed = False  # idempotency guard


def _ipython_custom_exc_handler(shell, exc_type, exc_value, tb, tb_offset=None):
    """IPython custom exception hook: render API errors cleanly."""
    _ = (shell, exc_type, tb, tb_offset)  # keep signature for IPython; silence linters
    print_api_error(exc_value)


def _get_ipython_shell():
    """Return the active IPython shell instance, or None if unavailable."""
    if "IPython" not in sys.modules:
        return None
    try:
        ipy = importlib.import_module("IPython")
    except ImportError:
        return None
    get_ipython = getattr(ipy, "get_ipython", None)
    if get_ipython is None:
        return None
    try:
        return get_ipython()
    except Exception:
        return None


def _qibo_sys_excepthook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, QiboApiError):
        print_api_error(exc_value)
        return
    if _prev_sys_excepthook is not None:
        return _prev_sys_excepthook(exc_type, exc_value, exc_tb)
    return sys.__excepthook__(exc_type, exc_value, exc_tb)


def _qibo_threading_excepthook(args: threading.ExceptHookArgs):
    if isinstance(args.exc_value, QiboApiError):
        print_api_error(args.exc_value)
        return
    if _prev_threading_excepthook is not None:
        return _prev_threading_excepthook(args)
    return threading.__excepthook__(args)


def _qibo_asyncio_exception_handler(loop, context):
    exc = context.get("exception")
    if isinstance(exc, QiboApiError):
        print_api_error(exc)
        return
    loop.default_exception_handler(context)


def _install_asyncio_handler_if_running():
    """Attach our handler to the *running* loop, if any, with no deprecation warnings."""
    try:
        loop = asyncio.get_running_loop()  # 3.7+: no warning; raises if none
    except RuntimeError:
        return
    # Save previous only once per loop
    if loop not in _prev_asyncio_handlers:
        _prev_asyncio_handlers[loop] = loop.get_exception_handler()
    loop.set_exception_handler(_qibo_asyncio_exception_handler)


def _uninstall_asyncio_handler_all_known_loops():
    """Restore previously saved handlers for loops we touched."""
    for loop, prev in list(_prev_asyncio_handlers.items()):
        try:
            loop.set_exception_handler(prev)
        except Exception:
            pass
        finally:
            _prev_asyncio_handlers.pop(loop, None)


def install_qibo_error_hooks() -> bool:
    """Install hooks once. Returns True if installed this call, False if already installed."""
    global _installed, _prev_sys_excepthook, _prev_threading_excepthook
    if _installed:
        return False

    _prev_sys_excepthook = sys.excepthook
    sys.excepthook = _qibo_sys_excepthook

    _prev_threading_excepthook = getattr(threading, "excepthook", None)
    if hasattr(threading, "excepthook"):
        threading.excepthook = _qibo_threading_excepthook  # type: ignore

    # Asyncio: only if a loop is currently running (no deprecation warning)
    _install_asyncio_handler_if_running()

    shell = _get_ipython_shell()
    if shell is not None:
        try:
            shell.set_custom_exc((QiboApiError,), _ipython_custom_exc_handler)
        except Exception:
            pass

    _installed = True
    return True


def uninstall_qibo_error_hooks() -> bool:
    """Restore previous hooks. Returns True if uninstalled, False if not installed."""
    global _installed
    if not _installed:
        return False

    if _prev_sys_excepthook is not None:
        sys.excepthook = _prev_sys_excepthook

    if _prev_threading_excepthook is not None and hasattr(threading, "excepthook"):
        threading.excepthook = _prev_threading_excepthook  # type: ignore

    _uninstall_asyncio_handler_all_known_loops()

    _installed = False
    return True


@contextmanager
def qibo_error_hooks():
    """Install hooks for the duration of a block. Testing utility."""
    installed_now = install_qibo_error_hooks()
    try:
        yield
    finally:
        if installed_now:
            uninstall_qibo_error_hooks()


def _ipython_custom_exc_handler(shell, exc_type, exc_value, tb, tb_offset=None):
    """IPython custom exception hook: render API errors cleanly."""
    _ = (shell, exc_type, tb, tb_offset)  # keep signature for IPython; silence linters
    print_api_error(exc_value)
