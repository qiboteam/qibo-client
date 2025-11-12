"""This module implements some constants and custom exceptions"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Rich is an optional runtime dependency for UI; we guard imports.
try:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover
    Panel = None
    Text = None
    Table = None


class MalformedResponseError(Exception):
    """Exception raised when server responsed body does not contain expected keys"""

    def __init__(
        self,
        message: str = "Server response body does not contain all the expected keys",
    ):
        self.message = message
        super().__init__(self.message)


class JobPostServerError(Exception):
    """Exception raised when server fails to post the job to the queue.

    The client should handle such error to aknowledge that job submission was
    not successful without crashing.
    """

    def __init__(self, message: str = "Server failed to post job to queue"):
        self.message = message
        super().__init__(self.message)


@dataclass
class QiboApiError(RuntimeError):
    """Clean, user-facing API error (no traceback noise).

    Attributes:
        status: HTTP status code (0 for network layer errors)
        method: HTTP method string (GET/POST/DELETE)
        url: full request URL
        message: a friendly error message extracted from the response
        payload: optional parsed JSON payload (dict) for debugging/advanced usage
    """

    status: int
    method: str
    url: str
    message: str
    payload: dict[str, Any] | None = None

    def __post_init__(self):
        # Keep the base Exception message concise
        super().__init__(self.message)

    # ---- Pretty rendering helpers (Rich) ----
    def rich_panel(self):
        """Return a Rich Panel renderable summarizing the error (or None if Rich unavailable)."""
        if Panel is None or Text is None or Table is None:  # Rich not available
            return None

        # One-row grid: [icon + title] | [meta (method+url)]
        title_text = Text.assemble(
            ("API Error ", "bold red"), (str(self.status), "bold red")
        )
        meta = Text.assemble(
            (" ",),
            ("[", "dim"),
            (self.method, "bold"),
            ("] ", "dim"),
            (self.url, "dim"),
        )

        grid = Table.grid(expand=True)
        grid.add_column(ratio=2, justify="left", no_wrap=False)
        grid.add_column(ratio=3, justify="right", no_wrap=False)

        grid.add_row(title_text, meta)

        # Body: the message itself
        body = Text(self.message)

        outer = Table.grid(expand=True)
        outer.add_column(ratio=1)
        outer.add_row(grid)
        outer.add_row(body)

        return Panel(outer, border_style="red", title="Request failed", expand=True)

    def print_rich(self):
        """Print the error as a Rich panel (falls back to plain text if Rich missing)."""
        try:
            from rich.console import Console
        except Exception:
            # Fallback: single clean line, no ANSI
            print(f"[{self.status} Error] {self.message} ({self.method} {self.url})")
            return
        panel = self.rich_panel()
        c = Console()
        if panel is not None:
            c.print(panel)
        else:
            c.print(
                f"[bold red][{self.status} Error][/bold red] {self.message}  [dim]{self.method} {self.url}[/dim]"
            )

    def get_plain_message(self) -> str:
        return f"\x1b[91m[{self.status} Error] {self.message} ({self.method} {self.url})\x1b[0m"
