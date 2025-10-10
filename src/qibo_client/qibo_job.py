import importlib.metadata as im
import tarfile
import tempfile
import time
import typing as T
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

import qibo
import requests
from rich import box
from rich.align import Align

# ---- Rich UI ----
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

version = im.version(__package__)

from . import constants
from .config_logging import logger
from .utils import QiboApiRequest


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


# -----------------------------
# Helpers
# -----------------------------
def format_hms(seconds: int | float | None) -> str:
    if seconds is None:
        return "-"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def convert_str_to_job_status(status: str):
    return next((s for s in QiboJobStatus if s.value == status), None)


class QiboJobStatus(Enum):
    QUEUEING = "queueing"
    PENDING = "pending"
    RUNNING = "running"
    POSTPROCESSING = "postprocessing"
    SUCCESS = "success"
    ERROR = "error"


def _write_stream_to_tmp_file(stream: T.Iterable) -> Path:
    """Write chunk of bytes to temporary file."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        for chunk in stream:
            if chunk:
                tmp_file.write(chunk)
        archive_path = tmp_file.name
    return Path(archive_path)


def _extract_archive_to_folder(source_archive: Path, destination_folder: Path):
    with tarfile.open(source_archive, "r:gz") as archive:
        archive.extractall(destination_folder)


def _save_and_unpack_stream_response_to_folder(
    stream: T.Iterable, results_folder: Path
):
    """Save the stream to a given folder, then unpack."""
    archive_path = _write_stream_to_tmp_file(stream)
    _extract_archive_to_folder(archive_path, results_folder)
    archive_path.unlink()


def _log_status_non_tty(
    *,
    verbose: bool,
    last_status: T.Optional["QiboJobStatus"],
    printed_pending_with_info: bool,
    job_status: "QiboJobStatus",
    qpos: T.Optional[int],
    etd: T.Optional[int | float],
) -> tuple[T.Optional["QiboJobStatus"], bool]:
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
        # First time we see this status
        if job_status == QiboJobStatus.QUEUEING:
            logger.info("⏳ Job QUEUEING")
        elif job_status == QiboJobStatus.PENDING:
            if qpos is not None or etd is not None:
                logger.info(
                    "🕒 Job PENDING -> position in queue: %s, max ETD: %s",
                    "-" if qpos is None else qpos,
                    format_hms(etd),
                )
                printed_pending_with_info = True
            else:
                logger.info("🕒 Job PENDING")
        elif job_status == QiboJobStatus.RUNNING:
            logger.info("🚀 Job RUNNING")
        elif job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
            icon = "✅" if job_status == QiboJobStatus.SUCCESS else "❌"
            logger.info("%s Job %s", icon, job_status.name)
        # POSTPROCESSING intentionally skipped
        last_status = job_status
    else:
        # Same status again — only upgrade PENDING once when info appears
        if job_status == QiboJobStatus.PENDING and not printed_pending_with_info:
            if qpos is not None or etd is not None:
                logger.info(
                    "🕒 Job PENDING -> position in queue: %s, max ETD: %s",
                    "-" if qpos is None else qpos,
                    format_hms(etd),
                )
                printed_pending_with_info = True

    return last_status, printed_pending_with_info


# -----------------------------
# Rich renderers
# -----------------------------
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
        expand=True,  # outer fills console width
    )


class _Outer:
    """Stable outer container that always wraps the current UI slots."""

    def __init__(self, title: str, ui: "_UISlots"):
        self.title = title
        self.ui = ui

    def __rich_console__(self, console: Console, options):
        # Always render the inner Group and wrap it in the titled panel
        inner = self.ui.renderable()
        yield _outer_container(self.title, inner)

    # Pass-through measurement so Live can size correctly
    def __rich_measure__(self, console: Console, options):
        inner = self.ui.renderable()
        panel = _outer_container(self.title, inner)
        return panel.__rich_measure__(console, options)


def _build_event_panel(
    title: str, subtitle: str | None = None, *, icon: str = "📝"
) -> Panel:
    """
    Build (but do not print) a single-line, fixed-width event banner Panel.
    Caller decides how/when to emit (e.g., grouped with other panels).
    """
    # one-row grid: [icon + title] | [subtitle or empty]
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


class _UISlots:
    """
    Compose a stable, single Rich renderable from named slots.
    Each slot holds any Rich renderable (or None).
    The composed renderable is a Group (tight stack with no extra spacing in Jupyter).
    """

    def __init__(self, order: T.Sequence[str]):
        self._order = list(order)
        self._slots: Dict[str, Optional[RenderableType]] = {
            k: None for k in self._order
        }

    def set(self, name: str, renderable: Optional[RenderableType]) -> None:
        if name not in self._slots:
            raise KeyError(f"Unknown slot '{name}'")
        self._slots[name] = renderable

    def renderable(self, *, title: str | None = None) -> RenderableType:
        """Return full renderable, optionally wrapped in a titled outer container."""
        parts = [r for k in self._order if (r := self._slots[k]) is not None]
        if not parts:
            return Text("")

        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        for p in parts:
            grid.add_row(p)
        return grid


def build_event_job_posted_panel(device: str, pid: str) -> Panel:
    return _build_event_panel(
        f"Job posted on {device}", subtitle=f"pid {pid}", icon="📬"
    )


def _status_panel(
    status: "QiboJobStatus",
    queue_position: int | None,
    etd_seconds: int | float | None,
) -> Panel:
    """
    Single-row, fixed-width row:
      [icon + STATUS] | [queue: ... or empty] | [ETD: ... or empty]
    Queue/ETD are shown only when PENDING.
    """
    status_style_map = {
        QiboJobStatus.PENDING: "bold cyan",
        QiboJobStatus.RUNNING: "bold green",
        QiboJobStatus.SUCCESS: "bold green",
        QiboJobStatus.ERROR: "bold red",
    }
    status_text = Text(f"{status.name}", style=status_style_map.get(status, "bold"))
    icon = _status_icon(status)

    # build the left cell: icon + label on one line
    left_cell = Table.grid(padding=(0, 1))
    left_cell.add_column(no_wrap=True)
    left_cell.add_column(no_wrap=False)
    left_cell.add_row(icon, status_text)

    # main single-row grid
    grid = Table.grid(expand=True)
    grid.add_column(ratio=2, justify="left", no_wrap=False)
    grid.add_column(ratio=1, justify="center", no_wrap=True)
    grid.add_column(ratio=1, justify="right", no_wrap=True)

    if status == QiboJobStatus.PENDING:
        qp = "-" if queue_position is None else str(queue_position)
        etd_str = "-" if etd_seconds is None else format_hms(etd_seconds)
        mid = f"queue: {qp}"
        right = f"Max ETD: {etd_str}"
    else:
        mid = ""
        right = ""

    grid.add_row(left_cell, mid, right)

    border_color = {
        QiboJobStatus.SUCCESS: "green",
        QiboJobStatus.ERROR: "red",
        QiboJobStatus.PENDING: "cyan",
    }.get(status, "dim")

    return Panel(grid, box=box.ROUNDED, border_style=border_color, expand=True)


def _status_icon(status: "QiboJobStatus") -> T.Any:
    """
    Return a renderable (Text/Table/Spinner combo) for the current status.
    IMPORTANT: don't call .add_row() inline and return its result (it's None).
    Build the grid, add rows, THEN return the grid.
    """
    if status == QiboJobStatus.PENDING:
        g = Table.grid(padding=(0, 1))
        g.add_column(no_wrap=True)
        g.add_column(no_wrap=True)
        g.add_row(Text("🕒"), Spinner("dots"))
        return g

    if status == QiboJobStatus.RUNNING:
        g = Table.grid(padding=(0, 1))
        g.add_column(no_wrap=True)
        g.add_column(no_wrap=True)
        g.add_row(Text("🚀"), Spinner("line"))
        return g

    if status == QiboJobStatus.SUCCESS:
        return Text("✅")

    if status == QiboJobStatus.ERROR:
        return Text("❌")

    return Text("ℹ️")


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


def _final_banner(
    status: "QiboJobStatus",
    *,
    pid: str,
    device: str | None,
    elapsed_seconds: int | float | None,
) -> Panel:
    """Compact one-card completion banner."""
    is_success = status == QiboJobStatus.SUCCESS
    color = "green" if is_success else "red"
    icon = "✅" if is_success else "❌"

    # Headline
    headline = Text.assemble(
        f"{icon} ", ("JOB ", "bold"), (status.name, f"bold {color}")
    )

    # Metadata line as small chips
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


# -----------------------------
# QiboJob
# -----------------------------
class QiboJob:
    def __init__(
        self,
        pid: str,
        base_url: str = constants.BASE_URL,
        headers: T.Dict[str, str] | None = None,
        circuit: T.Optional[qibo.Circuit] = None,
        nshots: T.Optional[int] = None,
        device: T.Optional[str] = None,
    ):
        self.base_url = base_url
        self.headers = headers
        self.pid = pid
        self.circuit = circuit
        self.nshots = nshots
        self.device = device

        self._status: T.Optional[QiboJobStatus] = None
        # convenience fields (populated on refresh/status)
        self.queue_position: T.Optional[int] = None
        self.seconds_to_job_start: T.Optional[int | float] = None
        self.queue_last_update: T.Optional[str] = None

        self._preamble: T.Optional[RenderableType] = None

    # ---- server I/O ----
    def _snapshot(self) -> T.Dict:
        """Fetch current job snapshot from the webapp."""
        url = self.base_url + f"/api/jobs/{self.pid}/"
        resp = QiboApiRequest.get(
            url,
            headers=self.headers,
            timeout=constants.TIMEOUT,
            keys_to_check=["status"],
        )
        return resp.json()

    def refresh(self):
        """Refreshes job information from server (no results download)."""
        info = self._snapshot()
        if info:
            self._update_job_info(info)

    def _update_job_info(self, info: T.Dict):
        self.circuit = info.get("circuit")
        self.nshots = info.get("nshots")
        pq = info.get("projectquota") or {}
        part = pq.get("partition") or {}
        self.device = part.get("name", self.device)
        self._status = convert_str_to_job_status(info["status"])

        # live queue info
        self.queue_position = info.get("queue_position")
        self.seconds_to_job_start = info.get("etd_seconds")
        self.queue_last_update = info.get("queue_last_update")

    # ---- convenience ----
    def status(self) -> QiboJobStatus:
        info = self._snapshot()
        self._status = convert_str_to_job_status(info["status"])
        self.queue_position = info.get("queue_position", info.get("job_queue_position"))
        self.seconds_to_job_start = info.get(
            "etd_seconds", info.get("seconds_to_job_start")
        )
        self.queue_last_update = info.get("queue_last_update")
        return self._status

    def running(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.RUNNING

    def success(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.SUCCESS

    # ---- main wait loop ----
    def result(
        self, wait: float = 0.5, verbose: bool = True
    ) -> T.Optional[qibo.result.QuantumState]:
        """Poll server until completion, then download and return result."""
        response, job_status = self._wait_for_response_to_get_request(wait, verbose)

        # create the job results folder
        self.results_folder = constants.RESULTS_BASE_FOLDER / self.pid
        self.results_folder.mkdir(parents=True, exist_ok=True)

        # Save the stream to disk
        try:
            _save_and_unpack_stream_response_to_folder(
                response.iter_content(), self.results_folder
            )
        except tarfile.ReadError as err:
            logger.error("Catched tarfile ReadError: %s", err)
            logger.error(
                "The received file is not a valid gzip archive, the result might "
                "have to be inspected manually. Find the file at `%s`",
                self.results_folder.as_posix(),
            )
            return None

        if job_status == QiboJobStatus.ERROR:
            out_log_path = self.results_folder / "stdout.log"
            stdout = out_log_path.read_text() if out_log_path.is_file() else "-"
            err_log_path = self.results_folder / "stderr.log"
            stderr = err_log_path.read_text() if err_log_path.is_file() else "-"
            logger.error(
                "Job exited with error\n\nStdout:\n%s\n\nStderr:\n%s", stdout, stderr
            )
            return None

        self.results_path = self.results_folder / "results.npy"
        return qibo.result.load_result(self.results_path)

    def _wait_for_response_to_get_request(
        self, seconds_between_checks: T.Optional[int] = None, verbose: bool = True
    ) -> T.Tuple[requests.Response, QiboJobStatus]:
        """Poll the job until completion; return (download_response, final_status)."""
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        # Gentle hint when not verbose
        is_job_unfinished = self.status() not in (
            QiboJobStatus.SUCCESS,
            QiboJobStatus.ERROR,
        )
        if not verbose and is_job_unfinished:
            logger.info("Please wait until your job is completed...")

        url = self.base_url + f"/api/jobs/{self.pid}/"
        # Only show Rich Live in an interactive TTY or Jupyter with ipywidgets.
        use_live = verbose and USE_RICH_UI

        # Render policy: don't update during POSTPROCESSING so previous panel stays visible
        def _render(status: QiboJobStatus, qpos, etd):
            if status == QiboJobStatus.POSTPROCESSING:
                return None
            # NOTE: ensure _status_panel is your one-row, fixed-width panel renderer
            return _status_panel(status, qpos, etd)

        # Small wrapper to fetch status + live fields
        def _fetch_snapshot() -> (
            tuple[QiboJobStatus, T.Optional[int], T.Optional[int | float]]
        ):
            payload = QiboApiRequest.get(
                url, headers=self.headers, timeout=constants.TIMEOUT
            ).json()
            status = convert_str_to_job_status(payload["status"])
            qpos = payload.get("queue_position", payload.get("job_queue_position"))
            etd = payload.get("etd_seconds", payload.get("seconds_to_job_start"))
            return status, qpos, etd

        # --- Live (TTY) branch ---
        if use_live:
            status0, qpos0, etd0 = _fetch_snapshot()

            # Compose a single renderable from named slots.
            # You can add more slots later (e.g., "header", "footer") without changing Live plumbing.
            ui = _UISlots(order=("header", "status", "footer"))
            title = f"Qibo client version {version}"
            ui.set("header", self._preamble)
            ui.set("status", _status_panel(status0, qpos0, etd0))

            outer = _Outer(title, ui)

            with Live(
                outer,
                refresh_per_second=12,
                console=console,
                transient=False,
                vertical_overflow="visible",
            ) as live:
                start_ts = time.perf_counter()
                while True:
                    job_status, qpos, etd = _fetch_snapshot()

                    renderable = _render(job_status, qpos, etd)
                    if renderable is not None:
                        # Swap the status slot in place
                        ui.set("status", renderable)
                        live.refresh()

                    if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                        elapsed = time.perf_counter() - start_ts

                        # Download first so that the final banner is the *last* thing shown
                        response = QiboApiRequest.get(
                            self.base_url + f"/api/jobs/{self.pid}/download/",
                            headers=self.headers,
                            timeout=constants.TIMEOUT,
                        )

                        # Replace the status slot with a compact final banner
                        ui.set(
                            "status",
                            _final_banner(
                                job_status,
                                pid=self.pid,
                                device=self.device,
                                elapsed_seconds=elapsed,
                            ),
                        )
                        live.refresh()
                        return response, job_status

                    time.sleep(seconds_between_checks)

        last_status: T.Optional[QiboJobStatus] = None
        printed_pending_with_info = False

        if verbose and is_job_unfinished:
            logger.info("🚀 Starting qibo client...")
            logger.info("📬 Job posted on %s with pid, %s", self.device, self.pid)

        while True:
            job_status, qpos, etd = _fetch_snapshot()

            # controlled, non-spam logging (prints each status once; PENDING upgraded once)
            last_status, printed_pending_with_info = _log_status_non_tty(
                verbose=verbose,
                last_status=last_status,
                printed_pending_with_info=printed_pending_with_info,
                job_status=job_status,
                qpos=qpos,
                etd=etd,
            )

            if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                if verbose:
                    logger.info("Job COMPLETED")
                response = QiboApiRequest.get(
                    self.base_url + f"/api/jobs/{self.pid}/download/",
                    headers=self.headers,
                    timeout=constants.TIMEOUT,
                )
                return response, job_status

            time.sleep(seconds_between_checks)

    def delete(self) -> str:
        url = self.base_url + f"/api/jobs/{self.pid}/"
        response = QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        )
        return response
