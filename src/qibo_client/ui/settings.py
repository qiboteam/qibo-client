from rich.console import Console

from ..config_logging import logger


def _in_jupyter() -> bool:
    """Return True if running inside a Jupyter/IPython kernel (incl. VS Code, Colab)."""
    try:
        from IPython import get_ipython  # type: ignore

        ip = get_ipython()
        return bool(ip and getattr(ip, "kernel", None))
    except ModuleNotFoundError:
        return False


def _is_ipywidgets_installed() -> bool:
    try:
        import ipywidgets

        return True
    except ModuleNotFoundError:
        logger.warning(
            "Note: ipywidgets is not installed. "
            "Falling back to standard logging. "
            "Install with: `pip install ipywidgets` to enable the Rich UI."
        )
        return False


IS_NOTEBOOK = _in_jupyter()
RICH_NOTEBOOK = IS_NOTEBOOK and _is_ipywidgets_installed()

_CONSOLE_KWARGS = {
    "force_jupyter": RICH_NOTEBOOK,
    "log_path": False,
    "log_time": True,
}

console = Console(**_CONSOLE_KWARGS)

USE_RICH_UI = (not IS_NOTEBOOK and console.is_terminal) or RICH_NOTEBOOK


def new_console() -> Console:
    """Return a fresh Console instance with our standard configuration."""
    return Console(**_CONSOLE_KWARGS)


def reset_console_live_state(target: Console | None = None) -> None:
    """Clear any stray Rich Live contexts so each job starts fresh."""
    console_obj = target or console
    stack = getattr(console_obj, "_live_stack", None)
    if not stack:
        return

    cleared = 0
    while stack:
        try:
            console_obj.clear_live()
        except Exception:  # pragma: no cover - extremely defensive
            stack.pop()
        finally:
            cleared += 1

    if cleared:
        logger.debug("Cleared stale Rich Live contexts: count=%s", cleared)
