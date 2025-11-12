"""Helpers for presenting errors on CLI/notebook front-ends."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..exceptions.errors import QiboApiError

try:
    from .settings import USE_RICH_UI, console
except Exception:  # pragma: no cover - settings import failed, fallback to plain prints
    USE_RICH_UI = False
    console = None


def _build_api_error_panel(error: QiboApiError):
    """Return a Rich panel describing the error, or None if Rich unavailable."""
    title_text = Text.assemble(
        ("API Error ", "bold red"),
    )

    grid = Table.grid(expand=True)
    grid.add_column(ratio=2, justify="left", no_wrap=False)
    grid.add_column(ratio=3, justify="right", no_wrap=False)
    grid.add_row(title_text)

    body = Text(error.message)

    outer = Table.grid(expand=True)
    outer.add_column(ratio=1)
    outer.add_row(grid)
    outer.add_row(body)

    return Panel(outer, border_style="red", title="Request failed", expand=True)


def print_api_error(error: QiboApiError) -> None:
    """Render the given error using Rich when available, fallback to plain text."""
    message = error.summary()

    if USE_RICH_UI and console is not None:
        panel = _build_api_error_panel(error)
        if panel:
            console.print(panel)
        else:
            console.print(message, style="bold red")
        return

    # Final fallback: Rich disabled/unavailable.
    print(message)


__all__ = ["print_api_error"]
