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

console = Console(
    force_jupyter=RICH_NOTEBOOK,
    log_path=False,
    log_time=True,
)

USE_RICH_UI = (not IS_NOTEBOOK and console.is_terminal) or RICH_NOTEBOOK
