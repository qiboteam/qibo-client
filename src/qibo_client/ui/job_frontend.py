"""Shared Rich/CLI helpers for Qibo job status rendering."""

from __future__ import annotations

import time
import typing as T

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ..config_logging import logger

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
CLR_PRIMARY = "magenta"
CLR_PRIMARY_BOLD = "bold magenta"
CLR_ACCENT = "cyan"
CLR_SUCCESS = "green"
CLR_ERROR = "red"
CLR_WARNING = "yellow"
CLR_RUNNING = "bold blue"
CLR_POSTPROC = "bold magenta"
CLR_MUTED = "dim"
CLR_TIMER = "bold yellow"
CLR_LABEL = "dim"

# ---------------------------------------------------------------------------
# Stage style definition
# ---------------------------------------------------------------------------
_STAGE_STYLE: dict[str, str] = {
    "QUEUEING": f"bold {CLR_WARNING}",
    "PENDING": f"bold {CLR_ACCENT}",
    "RUNNING": f"bold {CLR_RUNNING}",
    "POSTPROCESSING": f"bold {CLR_POSTPROC}",
    "SUCCESS": f"bold {CLR_SUCCESS}",
    "ERROR": f"bold {CLR_ERROR}",
}

_BORDER_STYLE: dict[str, str] = {
    "QUEUEING": CLR_WARNING,
    "PENDING": CLR_ACCENT,
    "RUNNING": "blue",
    "POSTPROCESSING": CLR_PRIMARY,
    "SUCCESS": CLR_SUCCESS,
    "ERROR": CLR_ERROR,
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def format_hms(seconds: int | float | None) -> str:
    if seconds is None:
        return "-"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Non-TTY logging (unchanged API)
# ---------------------------------------------------------------------------
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
            logger.info("* Job QUEUEING")
        elif job_status == "PENDING":
            if qpos is not None or etd is not None:
                logger.info(
                    "* Job PENDING -> position in queue: %s, max ETD: %s",
                    "-" if qpos is None else qpos,
                    format_hms(etd),
                )
                printed_pending_with_info = True
            else:
                logger.info("* Job PENDING")
        elif job_status == "RUNNING":
            logger.info("> Job RUNNING")
        elif job_status in ("SUCCESS", "ERROR"):
            icon = "+" if job_status == "SUCCESS" else "x"
            logger.info("%s Job %s", icon, job_status)
        last_status = job_status
    else:
        if job_status == "PENDING" and not printed_pending_with_info:
            if qpos is not None or etd is not None:
                logger.info(
                    "* Job PENDING -> position in queue: %s, max ETD: %s",
                    "-" if qpos is None else qpos,
                    format_hms(etd),
                )
                printed_pending_with_info = True

    return last_status, printed_pending_with_info


# ---------------------------------------------------------------------------
# Elapsed timer renderable
# ---------------------------------------------------------------------------
class ElapsedTimer:
    """A live-updating elapsed time display. Reads wall-clock on each render."""

    def __init__(self, start_time: float | None = None):
        self.start_time = start_time or time.perf_counter()

    def __rich_console__(self, console: Console, options):
        elapsed = time.perf_counter() - self.start_time
        yield Text.from_markup(
            f"[{CLR_LABEL}]elapsed[/] [{CLR_TIMER}]{format_hms(elapsed)}[/]"
        )

    def __rich_measure__(self, console: Console, options):
        from rich.measure import Measurement

        return Measurement(15, 25)


# ---------------------------------------------------------------------------
# Outer container
# ---------------------------------------------------------------------------
def _outer_container(
    title: str,
    inner: RenderableType,
    *,
    elapsed_timer: ElapsedTimer | None = None,
    keybind_hint: str | None = None,
    version: str | None = None,
) -> RenderableType:
    grid = Table.grid(expand=False)
    grid.add_column(ratio=1)
    grid.add_row(Rule(title=Text(title, style="bold"), style="default"))
    grid.add_row(inner)

    # Build bottom rule parts
    bottom_title = None
    if elapsed_timer is not None:
        parts = Text()
        if elapsed_timer is not None:
            elapsed = time.perf_counter() - elapsed_timer.start_time
            parts.append("elapsed ", style="dim")
            parts.append(format_hms(elapsed), style="bold")
        bottom_title = parts
    grid.add_row(Rule(title=bottom_title, style="default"))
    return grid


class LiveOuter:
    """Stable outer container that always wraps the current UI slots."""

    def __init__(
        self,
        title: str,
        version: str,
        ui: UISlots,
        *,
        elapsed_timer: ElapsedTimer | None = None,
    ):
        self.title = title
        self.version = version
        self.ui = ui
        self.elapsed_timer = elapsed_timer

    def __rich_console__(self, console: Console, options):
        inner = self.ui.renderable()
        yield _outer_container(
            self.title,
            inner,
            elapsed_timer=self.elapsed_timer,
            version=self.version,
        )

    def __rich_measure__(self, console: Console, options):
        from rich.measure import Measurement

        return Measurement(options.min_width, options.max_width)


# ---------------------------------------------------------------------------
# Status icon with spinners
# ---------------------------------------------------------------------------
def _status_icon(status: str) -> T.Any:
    if status == "QUEUEING":
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(Text("*"), Spinner("dots", style=CLR_WARNING))
        return grid

    if status == "PENDING":
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(Text("*"), Spinner("dots", style=CLR_ACCENT))
        return grid

    if status == "RUNNING":
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(Text(">"), Spinner("line", style="blue"))
        return grid

    if status == "POSTPROCESSING":
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(Text("~"), Spinner("bouncingBar", style=CLR_PRIMARY))
        return grid

    if status == "SUCCESS":
        return Text("+")

    if status == "ERROR":
        return Text("x")

    return Text("?")


# ---------------------------------------------------------------------------
# Shared metadata row
# ---------------------------------------------------------------------------
def _build_meta_row(
    *,
    pid: str | None = None,
    device: str | None = None,
    project: str | None = None,
) -> Table:
    """Build a compact metadata row:  pid  device  project."""
    meta = Table.grid(padding=(0, 2))
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)

    meta.add_row(
        Text.from_markup(f"[{CLR_LABEL}]job-pid[/] [bold]{pid or '-'}[/]"),
        Text.from_markup(f"[{CLR_LABEL}]device[/] [bold]{device or '-'}[/]"),
        Text.from_markup(f"[{CLR_LABEL}]project[/] [bold]{project or '-'}[/]"),
    )
    return meta


# ---------------------------------------------------------------------------
# Shared metadata row
# ---------------------------------------------------------------------------
def _build_provider_row(
    *,
    provider: str | None = None,
    version: str | None = None,
) -> Table:
    """Build a compact metadata row:  pid  device  project."""
    meta = Table.grid(padding=(0, 2), expand=True)
    meta.add_column()
    meta.add_column(justify="right", no_wrap=True)

    meta.add_row(
        Text.from_markup(f"[{CLR_LABEL}]provider[/] [bold]{provider or '-'}[/]"),
        Text.from_markup(f"[{CLR_LABEL}]qibo-client[/] [bold]{version or '-'}[/]"),
    )
    return meta


# ---------------------------------------------------------------------------
# Status panel (main live panel)
# ---------------------------------------------------------------------------
def build_status_panel(
    status: str,
    queue_position: int | None,
    etd_seconds: int | float | None,
    *,
    provider: str | None = None,
    version: str | None = None,
    pid: str | None = None,
    device: str | None = None,
    project: str | None = None,
) -> Panel:

    # Status row: icon + label
    status_text = Text(status, style=_STAGE_STYLE.get(status, "bold"))
    icon = _status_icon(status)

    border = _BORDER_STYLE.get(status, "dim")

    meta0 = _build_provider_row(
        provider=provider,
        version=version,
    )

    meta1 = _build_meta_row(
        pid=pid,
        device=device,
        project=project,
    )

    left_cell = Table.grid(padding=(0, 1))
    left_cell.add_column(no_wrap=True)
    left_cell.add_column(no_wrap=False)
    left_cell.add_row(icon, status_text)

    # Info grid: status | queue/details | timer
    info_grid = Table.grid(expand=True)
    info_grid.add_column(ratio=2, justify="left", no_wrap=False)
    info_grid.add_column(ratio=1, justify="center", no_wrap=True)
    info_grid.add_column(ratio=1, justify="right", no_wrap=True)

    if status == "PENDING":
        qp = "-" if queue_position is None else str(queue_position)
        etd_str = "-" if etd_seconds is None else format_hms(etd_seconds)
        mid = f"queue: {qp}"
        right = f"Max ETD: {etd_str}"
    else:
        mid = ""
        right = ""

    info_grid.add_row(left_cell, mid, right)

    content = Group(
        meta0,
        Rule(style=CLR_MUTED),
        meta1,
        Rule(style=CLR_MUTED),
        info_grid,
    )

    return Panel(
        content,
        box=box.ROUNDED,
        border_style=border,
        expand=True,
    )


# ---------------------------------------------------------------------------
# Final banner
# ---------------------------------------------------------------------------
def build_final_banner(
    status: str,
    *,
    provider: str,
    version: str,
    pid: str,
    device: str | None,
    project: str | None,
) -> Panel:
    is_success = status == "SUCCESS"
    color = CLR_SUCCESS if is_success else CLR_ERROR
    icon = "+" if is_success else "x"

    meta0 = _build_provider_row(
        provider=provider,
        version=version,
    )

    meta1 = _build_meta_row(
        pid=pid,
        device=device,
        project=project,
    )

    headline = Text.assemble(
        f"{icon} ", ("job completed with ", "bold"), (status, f"bold {color}")
    )

    content = Group(
        meta0,
        Rule(style=color),
        meta1,
        Rule(style=color),
        headline,
    )
    return Panel(
        content,
        border_style=color,
        box=box.ROUNDED,
        subtitle="",
        subtitle_align="right",
        expand=True,
    )


# ---------------------------------------------------------------------------
# UISlots
# ---------------------------------------------------------------------------
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
    "ElapsedTimer",
    "UISlots",
    "LiveOuter",
    "build_final_banner",
    "build_status_panel",
    "format_hms",
    "log_status_non_tty",
]
