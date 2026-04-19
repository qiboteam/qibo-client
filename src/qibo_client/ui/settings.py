"""UI settings configuration for qibo-client.

This module determines the execution environment and configures appropriate
UI settings (e.g., Rich vs console output, notebook detection).
"""

from rich.console import Console

from ..config_logging import logger


def _in_jupyter() -> bool:
    """Return True if running inside a Jupyter/IPython kernel (incl. VS Code, Colab).

    Checks for running in any notebook-like environment, which affects UI
    behavior and output format.

    Returns:
        True if running in Jupyter/IPython, False otherwise
    """
    try:
        from IPython import get_ipython  # type: ignore

        ip = get_ipython()
        return bool(ip and getattr(ip, "kernel", None))
    except ModuleNotFoundError:
        return False


def _is_ipywidgets_installed() -> bool:
    """Check if ipywidgets are installed for enhanced Rich UI in notebooks.

    ipywidgets provide interactive elements like progress bars and spinners.

    Returns:
        True if ipywidgets is installed, False otherwise
    """
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
"""Flag indicating if running in a notebook environment."""


RICH_NOTEBOOK = IS_NOTEBOOK and _is_ipywidgets_installed()
"""Flag indicating if Rich UI with widgets should be used in notebook."""


console = Console(
    force_jupyter=RICH_NOTEBOOK,
    log_path=False,
    log_time=True,
)
"""Rich console instance configured for the detected environment."""


USE_RICH_UI = (not IS_NOTEBOOK and console.is_terminal) or RICH_NOTEBOOK
"""Flag indicating whether to use Rich UI for output rendering.

Rich UI provides enhanced console output with colors, progress indicators,
and spinners. This defaults to True for terminal output and True for notebooks
when widgets are installed.
"""
