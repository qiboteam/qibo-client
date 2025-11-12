"""Shared Rich/CLI helpers for Qibo job status rendering."""

from __future__ import annotations

import typing as T

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ..config_logging import logger


def format_hms(seconds: int | float | None) -> str:
    if seconds is None:
        return "-"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def log_status_non_tty(
    *,
    verbose: bool,
    last_status: T.Optional[str],
    printed_pending_with_info: bool,
    job_status: str,
    qpos: T.Optional[int],
    etd: T.Optional[int | float],
) -> tuple[T.Optional[str], bool]:
    """
    Non-TTY logging strategy:
      - Log each status once.
      - For PENDING: log once; if queue/ETD info shows up later, emit one upgraded line.
      - Skip POSTPROCESSING.
    Returns updated (last_status, printed_pending_with_info).
    """
    if not verbose:
        return last_status, printed_pending_with_info

    if job_status != last_status:
        if job_status == "QUEUEING":
            logger.info("⏳ Job QUEUEING")
        elif job_status == "PENDING":
            if qpos is not None or etd is not None:
                logger.info(
                    "🕒 Job PENDING -> position in queue: %s, max ETD: %s",
                    "-" if qpos is None else qpos,
                    format_hms(etd),
                )
                printed_pending_with_info = True
            else:
                logger.info("🕒 Job PENDING")
        elif job_status == "RUNNING":
            logger.info("🚀 Job RUNNING")
        elif job_status in ("SUCCESS", "ERROR"):
            icon = "✅" if job_status == "SUCCESS" else "❌"
            logger.info("%s Job %s", icon, job_status)
        last_status = job_status
    else:
        if job_status == "PENDING" and not printed_pending_with_info:
            if qpos is not None or etd is not None:
                logger.info(
                    "🕒 Job PENDING -> position in queue: %s, max ETD: %s",
                    "-" if qpos is None else qpos,
                    format_hms(etd),
                )
                printed_pending_with_info = True

    return last_status, printed_pending_with_info


def _outer_container(title: str, inner: RenderableType) -> Panel:
    header_style = "bold magenta"

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_row(inner)

    return Panel(
        grid,
        title=f"[{header_style}]{title}[/]",
        border_style="magenta",
        box=box.DOUBLE,
        padding=(1, 2),
        expand=True,
    )


class LiveOuter:
    """Stable outer container that always wraps the current UI slots."""

    def __init__(self, title: str, ui: UISlots):
        self.title = title
        self.ui = ui

    def __rich_console__(self, console: Console, options):
        inner = self.ui.renderable()
        yield _outer_container(self.title, inner)

    def __rich_measure__(self, console: Console, options):
        inner = self.ui.renderable()
        panel = _outer_container(self.title, inner)
        return panel.__rich_measure__(console, options)


def _build_event_panel(
    title: str, subtitle: str | None = None, *, icon: str = "📝"
) -> Panel:
    row = Table.grid(expand=True)
    row.add_column(ratio=3, justify="left", no_wrap=False)
    row.add_column(ratio=2, justify="right", no_wrap=True)

    left = Table.grid(padding=(0, 1))
    left.add_column(no_wrap=True)
    left.add_column(no_wrap=False)
    left.add_row(Text(icon), Text.from_markup(f"[bold]{title}[/]"))

    right = "" if subtitle is None else Text(subtitle, style="dim")
    row.add_row(left, right)

    return Panel(row, box=box.ROUNDED, border_style="magenta", expand=True)


def build_event_job_posted_panel(device: str, pid: str) -> Panel:
    return _build_event_panel(
        f"Job posted on {device}", subtitle=f"pid {pid}", icon="📬"
    )


def _status_icon(status: str) -> T.Any:
    if status == "PENDING":
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(Text("🕒"), Spinner("dots"))
        return grid

    if status == "RUNNING":
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(Text("🚀"), Spinner("line"))
        return grid

    if status == "SUCCESS":
        return Text("✅")

    if status == "ERROR":
        return Text("❌")

    return Text("ℹ️")


def build_status_panel(
    status: str,
    queue_position: int | None,
    etd_seconds: int | float | None,
) -> Panel:
    status_style_map = {
        "PENDING": "bold cyan",
        "RUNNING": "bold green",
        "SUCCESS": "bold green",
        "ERROR": "bold red",
    }
    status_text = Text(f"{status}", style=status_style_map.get(status, "bold"))
    icon = _status_icon(status)

    left_cell = Table.grid(padding=(0, 1))
    left_cell.add_column(no_wrap=True)
    left_cell.add_column(no_wrap=False)
    left_cell.add_row(icon, status_text)

    grid = Table.grid(expand=True)
    grid.add_column(ratio=2, justify="left", no_wrap=False)
    grid.add_column(ratio=1, justify="center", no_wrap=True)
    grid.add_column(ratio=1, justify="right", no_wrap=True)

    if status == "PENDING":
        qp = "-" if queue_position is None else str(queue_position)
        etd_str = "-" if etd_seconds is None else format_hms(etd_seconds)
        mid = f"queue: {qp}"
        right = f"Max ETD: {etd_str}"
    else:
        mid = ""
        right = ""

    grid.add_row(left_cell, mid, right)

    border_color = {
        "SUCCESS": "green",
        "ERROR": "red",
        "PENDING": "cyan",
    }.get(status, "dim")

    return Panel(grid, box=box.ROUNDED, border_style=border_color, expand=True)


def _pending_panel(
    queue_position: int | None, etd_seconds: int | float | None
) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row("[bold cyan]Job PENDING[/]", "")
    if queue_position is not None:
        table.add_row("Position in queue:", f"[bold]{queue_position}[/]")
    if etd_seconds is not None:
        table.add_row("Max ETD:", f"[bold]{format_hms(etd_seconds)}[/]")
    if queue_position is None and etd_seconds is None:
        table.add_row("", "[dim]waiting for queue info…[/]")
    return Panel(table, border_style="cyan", box=box.ROUNDED, expand=True)


def build_final_banner(
    status: str,
    *,
    pid: str,
    device: str | None,
    elapsed_seconds: int | float | None,
) -> Panel:
    is_success = status == "SUCCESS"
    color = "green" if is_success else "red"
    icon = "✅" if is_success else "❌"

    headline = Text.assemble(f"{icon} ", ("JOB ", "bold"), (status, f"bold {color}"))

    meta = Table.grid(padding=(0, 2))
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)

    meta.add_row(
        Text.from_markup(f"[dim]pid[/] [bold]{pid}[/]"),
        Text.from_markup(f"[dim]device[/] [bold]{device or '-'}[/]"),
        Text.from_markup(f"[dim]elapsed[/] [bold]{format_hms(elapsed_seconds)}[/]"),
    )

    content = Group(
        Align.left(headline),
        Rule(style=color),
        meta,
    )
    return Panel(content, border_style=color, box=box.ROUNDED, expand=True)


class UISlots:
    """
    Compose a stable, single Rich renderable from named slots.
    Each slot holds any Rich renderable (or None).
    The composed renderable is a grid stack.
    """

    def __init__(self, order: T.Sequence[str]):
        self._order = list(order)
        self._slots: dict[str, T.Optional[RenderableType]] = {
            key: None for key in self._order
        }

    def set(self, name: str, renderable: T.Optional[RenderableType]) -> None:
        if name not in self._slots:
            raise KeyError(f"Unknown slot '{name}'")
        self._slots[name] = renderable

    def renderable(self) -> RenderableType:
        parts = [renderable for key in self._order if (renderable := self._slots[key])]
        if not parts:
            return Text("")

        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        for part in parts:
            grid.add_row(part)
        return grid


__all__ = [
    "UISlots",
    "LiveOuter",
    "build_event_job_posted_panel",
    "build_final_banner",
    "build_status_panel",
    "format_hms",
    "log_status_non_tty",
]
