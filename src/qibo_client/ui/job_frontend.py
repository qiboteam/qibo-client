"""Shared Rich/CLI helpers for Qibo job status rendering."""

from __future__ import annotations

import io
import os
import select
import sys
import termios
import time
import tty
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
CLR_CIRCUIT = "cyan"

# ---------------------------------------------------------------------------
# Stage pipeline definition
# ---------------------------------------------------------------------------
STAGES = ("QUEUEING", "PENDING", "RUNNING", "POSTPROCESSING", "SUCCESS")

_STAGE_ICONS: dict[str, str] = {
    "QUEUEING": "*",
    "PENDING": "*",
    "RUNNING": ">",
    "POSTPROCESSING": "~",
    "SUCCESS": "+",
    "ERROR": "x",
}

_STAGE_STYLE: dict[str, str] = {
    "QUEUEING": CLR_WARNING,
    "PENDING": f"bold {CLR_ACCENT}",
    "RUNNING": CLR_RUNNING,
    "POSTPROCESSING": CLR_POSTPROC,
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


class NonBlockingKeyReader:
    """Context manager that puts stdin into raw/non-blocking mode for keypress detection."""

    def __init__(self):
        self._fd: int | None = None
        self._old_settings = None
        self.active: bool = False

    def __enter__(self):
        try:
            self._fd = sys.stdin.fileno()
            if not os.isatty(self._fd):
                self._fd = None
                return self
            self._old_settings = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self.active = True
        except (termios.error, ValueError, io.UnsupportedOperation, OSError):
            # Not a real TTY (e.g. Jupyter, piped stdin, CI) – degrade gracefully
            self._fd = None
        return self

    def __exit__(self, *exc):
        if self._fd is not None and self._old_settings is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)

    def get_key(self) -> str | None:
        """Return a single character if a key was pressed, else None."""
        if self._fd is None:
            return None
        rlist, _, _ = select.select([self._fd], [], [], 0)
        if rlist:
            return os.read(self._fd, 1).decode("utf-8", errors="ignore")
        return None


def _capture_circuit_drawing(circuit_dict: dict | None) -> str | None:
    """Reconstruct a Qibo circuit from its raw dict and capture its draw() output."""
    if circuit_dict is None:
        return None
    try:
        import qibo

        circ = qibo.Circuit.from_dict(circuit_dict)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        circ.draw()
        sys.stdout = old_stdout
        drawing = buf.getvalue().rstrip("\n")
        return drawing if drawing else None
    except Exception:
        return None


def _circuit_summary(circuit_dict: dict | None) -> dict | None:
    """Extract summary stats from a circuit dict."""
    if circuit_dict is None:
        return None
    try:
        import qibo

        circ = qibo.Circuit.from_dict(circuit_dict)
        return {
            "nqubits": circ.nqubits,
            "depth": circ.depth,
            "ngates": circ.ngates,
            "gate_names": dict(circ.gate_names),
        }
    except Exception:
        return None


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
# Pipeline progress tracker
# ---------------------------------------------------------------------------
def _build_pipeline_tracker(current_status: str) -> RenderableType:
    """Horizontal stage pipeline: ✓QUEUE → ●PENDING → ○RUNNING → ..."""
    if current_status == "ERROR":
        error_mode = True
        active_idx = -1
    else:
        error_mode = False
        active_idx = STAGES.index(current_status) if current_status in STAGES else -1

    row = Text()
    for i, stage in enumerate(STAGES):
        icon = _STAGE_ICONS.get(stage, "")
        if error_mode:
            row.append(f" {icon} {stage} ", style=CLR_MUTED)
        elif i < active_idx:
            row.append(f" ✓ {stage} ", style=CLR_SUCCESS)
        elif i == active_idx:
            style = _STAGE_STYLE.get(stage, "bold")
            row.append(f" {icon} {stage} ", style=style)
        else:
            row.append(f" ○ {stage} ", style=CLR_MUTED)

        if i < len(STAGES) - 1:
            if error_mode:
                row.append(" → ", style=CLR_MUTED)
            elif i < active_idx:
                row.append(" → ", style=CLR_SUCCESS)
            else:
                row.append(" → ", style=CLR_MUTED)

    if error_mode:
        row.append(" → ", style=CLR_MUTED)
        row.append(f" {_STAGE_ICONS['ERROR']} ERROR ", style=f"bold {CLR_ERROR}")

    return Align.center(row)


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
) -> RenderableType:
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_row(Rule(title=Text(title, style="bold"), style="default"))
    grid.add_row(inner)

    # Build bottom rule parts
    bottom_title = None
    if elapsed_timer is not None or keybind_hint is not None:
        parts = Text()
        if elapsed_timer is not None:
            elapsed = time.perf_counter() - elapsed_timer.start_time
            parts.append("elapsed ", style="dim")
            parts.append(format_hms(elapsed), style="bold")
        if keybind_hint is not None:
            if len(parts):
                parts.append("  ")
            parts.append_text(Text.from_markup(keybind_hint))
        bottom_title = parts
    grid.add_row(Rule(title=bottom_title, style="default"))
    return grid


class LiveOuter:
    """Stable outer container that always wraps the current UI slots."""

    def __init__(
        self,
        title: str,
        ui: UISlots,
        *,
        elapsed_timer: ElapsedTimer | None = None,
        keybind_hint: str | None = None,
    ):
        self.title = title
        self.ui = ui
        self.elapsed_timer = elapsed_timer
        self.keybind_hint = keybind_hint

    def __rich_console__(self, console: Console, options):
        inner = self.ui.renderable()
        yield _outer_container(
            self.title,
            inner,
            elapsed_timer=self.elapsed_timer,
            keybind_hint=self.keybind_hint,
        )

    def __rich_measure__(self, console: Console, options):
        from rich.measure import Measurement

        return Measurement(options.min_width, options.max_width)


# ---------------------------------------------------------------------------
# Event panel (job posted)
# ---------------------------------------------------------------------------
def _build_event_panel(
    title: str, subtitle: str | None = None, *, icon: str = ">"
) -> Panel:
    row = Table.grid(expand=True)
    row.add_column(ratio=3, justify="left", no_wrap=True)
    row.add_column(ratio=2, justify="right", no_wrap=True)

    left = Table.grid(padding=(0, 1))
    left.add_column(no_wrap=True)
    left.add_column(no_wrap=True)
    left.add_row(Text(icon), Text.from_markup(f"[bold]{title}[/]"))

    right = "" if subtitle is None else Text(subtitle, style="dim")
    row.add_row(left, right)

    return Panel(row, box=box.ROUNDED, border_style=CLR_PRIMARY, expand=True)


def build_event_job_posted_panel(
    device: str,
    pid: str,
    nshots: int | None = None,
    project: str | None = None,
) -> Panel:
    title = f"Job posted on {device}"
    if project is not None:
        title += f" - project {project}"
    if nshots is not None:
        title += f" - nshots {nshots}"
    return _build_event_panel(title, subtitle=f"pid {pid}", icon=">")


# ---------------------------------------------------------------------------
# Circuit panel
# ---------------------------------------------------------------------------
def build_circuit_panel(circuit_dict: dict | None) -> Panel | None:
    """Build a panel showing the circuit diagram and summary stats."""
    drawing = _capture_circuit_drawing(circuit_dict)
    summary = _circuit_summary(circuit_dict)
    if drawing is None and summary is None:
        return None

    parts: list[RenderableType] = []

    if drawing is not None:
        parts.append(
            Panel(
                Text(drawing),
                title=f"[bold {CLR_ACCENT}]Circuit Diagram[/]",
                border_style=CLR_MUTED,
                box=box.ROUNDED,
                expand=True,
                padding=(0, 1),
            )
        )

    if summary is not None:
        stats = Table.grid(padding=(0, 2), expand=False)
        stats.add_column(style=CLR_LABEL, no_wrap=True)
        stats.add_column(style="bold", no_wrap=True)
        stats.add_row("Qubits", str(summary["nqubits"]))
        stats.add_row("Depth", str(summary["depth"]))
        stats.add_row("Gates", str(summary["ngates"]))

        # Gate breakdown
        gate_parts = []
        for gate, count in sorted(summary["gate_names"].items(), key=lambda x: -x[1]):
            gate_parts.append(f"[{CLR_ACCENT}]{gate}[/]:[bold]{count}[/]")
        if gate_parts:
            stats.add_row("Breakdown", Text.from_markup("  ".join(gate_parts)))

        parts.append(stats)

    content = Group(*parts) if len(parts) > 1 else parts[0]
    return Panel(
        content,
        title=f"[{CLR_PRIMARY_BOLD}]Circuit[/]",
        border_style=CLR_PRIMARY,
        box=box.ROUNDED,
        expand=True,
        padding=(0, 1),
    )


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
# Status panel (main live panel)
# ---------------------------------------------------------------------------
def build_status_panel(
    status: str,
    queue_position: int | None,
    etd_seconds: int | float | None,
    *,
    elapsed_timer: ElapsedTimer | None = None,
    nshots: int | None = None,
) -> Panel:
    # Pipeline tracker at the top
    pipeline = _build_pipeline_tracker(status)

    # Status row: icon + label
    status_text = Text(status, style=_STAGE_STYLE.get(status, "bold"))
    icon = _status_icon(status)

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

    border = _BORDER_STYLE.get(status, "dim")
    content = Group(
        pipeline,
        Rule(style=CLR_MUTED),
        info_grid,
    )

    return Panel(
        content,
        box=box.ROUNDED,
        border_style=border,
        expand=True,
        title=f"[bold {border}]Status[/]",
    )


# ---------------------------------------------------------------------------
# Pending detail panel (kept for backward compat)
# ---------------------------------------------------------------------------
def _pending_panel(
    queue_position: int | None, etd_seconds: int | float | None
) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="right")
    table.add_row(f"[bold {CLR_ACCENT}]Job PENDING[/]", "")
    if queue_position is not None:
        table.add_row("Position in queue:", f"[bold]{queue_position}[/]")
    if etd_seconds is not None:
        table.add_row("Max ETD:", f"[bold]{format_hms(etd_seconds)}[/]")
    if queue_position is None and etd_seconds is None:
        table.add_row("", f"[{CLR_MUTED}]waiting for queue info…[/]")
    return Panel(table, border_style=CLR_ACCENT, box=box.ROUNDED, expand=True)


# ---------------------------------------------------------------------------
# Final banner
# ---------------------------------------------------------------------------
def build_final_banner(
    status: str,
    *,
    pid: str,
    device: str | None,
    elapsed_seconds: int | float | None,
    nshots: int | None = None,
) -> Panel:
    is_success = status == "SUCCESS"
    color = CLR_SUCCESS if is_success else CLR_ERROR
    icon = "+" if is_success else "x"

    # Pipeline tracker showing final state
    pipeline = _build_pipeline_tracker(status)

    headline = Text.assemble(f"{icon} ", ("JOB ", "bold"), (status, f"bold {color}"))

    meta = Table.grid(padding=(0, 2))
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)
    meta.add_column(no_wrap=True)

    meta.add_row(
        Text.from_markup(
            f"[{CLR_LABEL}]nshots[/] [bold]{nshots if nshots is not None else '-'}[/]"
        ),
        Text.from_markup(f"[{CLR_LABEL}]pid[/] [bold]{pid}[/]"),
        Text.from_markup(f"[{CLR_LABEL}]device[/] [bold]{device or '-'}[/]"),
        Text.from_markup(
            f"[{CLR_LABEL}]elapsed[/] [{CLR_TIMER}]{format_hms(elapsed_seconds)}[/]"
        ),
    )

    content = Group(
        pipeline,
        Rule(style=color),
        Align.left(headline),
        Rule(style=color),
        meta,
    )
    return Panel(content, border_style=color, box=box.ROUNDED, expand=True)


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
    "NonBlockingKeyReader",
    "UISlots",
    "LiveOuter",
    "build_circuit_panel",
    "build_event_job_posted_panel",
    "build_final_banner",
    "build_status_panel",
    "format_hms",
    "log_status_non_tty",
]
