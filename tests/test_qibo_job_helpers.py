import logging

import pytest
from rich.console import Console
from rich.spinner import Spinner
from rich.text import Text

from qibo_client.ui import job_frontend


def render_to_text(renderable) -> str:
    console = Console(width=80, record=True)
    console.print(renderable)
    return console.export_text(clear=True).strip()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "-"),
        (0, "0:00:00"),
        (65.4, "0:01:05"),
        (3661, "1:01:01"),
    ],
)
def test_format_hms_handles_none_and_rounding(seconds, expected):
    assert job_frontend.format_hms(seconds) == expected


def test_log_status_non_tty_logs_once_per_status(caplog):
    caplog.set_level(logging.INFO, logger="qibo_client.config_logging")

    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=None,
        printed_pending_with_info=False,
        job_status="SUCCESS",
        qpos=None,
        etd=None,
    )

    assert last == "SUCCESS"
    assert printed is False
    assert caplog.messages[-1] == "+ Job SUCCESS"


def test_log_status_non_tty_pending_upgrades_once(caplog):
    caplog.set_level(logging.INFO, logger="qibo_client.config_logging")
    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=None,
        printed_pending_with_info=False,
        job_status="PENDING",
        qpos=None,
        etd=None,
    )

    assert caplog.messages[-1] == "* Job PENDING"
    caplog.clear()

    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=last,
        printed_pending_with_info=printed,
        job_status="PENDING",
        qpos=3,
        etd=120,
    )

    assert printed is True
    assert (
        caplog.messages[-1] == "* Job PENDING -> position in queue: 3, max ETD: 0:02:00"
    )


def test_status_icon_variants():
    pending_icon = job_frontend._status_icon("PENDING")
    assert pending_icon.columns[1]._cells and isinstance(
        pending_icon.columns[1]._cells[0], Spinner
    )

    success_icon = job_frontend._status_icon("SUCCESS")
    assert isinstance(success_icon, Text)
    assert success_icon.plain == "+"


def test_status_panel_pending_contains_queue_info():
    panel = job_frontend.build_status_panel(
        "PENDING", queue_position=5, etd_seconds=125
    )
    text = render_to_text(panel)
    assert "queue: 5" in text
    assert "Max ETD: 0:02:05" in text
    assert panel.border_style == "cyan"


def test_status_panel_success_has_green_border():
    panel = job_frontend.build_status_panel(
        "SUCCESS", queue_position=None, etd_seconds=None
    )
    text = render_to_text(panel)
    assert "queue:" not in text
    assert panel.border_style == "green"


def test_status_panel_shows_metadata_row():
    panel = job_frontend.build_status_panel(
        "RUNNING",
        queue_position=None,
        etd_seconds=None,
        pid="abc123",
        device="tii-sim",
    )
    text = render_to_text(panel)
    assert "abc123" in text
    assert "tii-sim" in text


def test_pending_panel_waits_for_info():
    panel = job_frontend._pending_panel(None, None)
    text = render_to_text(panel)
    assert "waiting for queue info" in text


def test_final_banner_contains_metadata():
    panel = job_frontend.build_final_banner(
        "SUCCESS", pid="pid-123", device="qpu-a", project="prj"
    )
    text = render_to_text(panel)
    assert "pid-123" in text
    assert "qpu-a" in text
    assert "prj" in text
    assert panel.border_style == "green"


def test_build_event_panel():
    panel = job_frontend._build_event_panel("Test Event", "details", icon="⭐")
    text = render_to_text(panel)
    assert "Test Event" in text
    assert "details" in text


def test_outer_container_and_outer_render_title():
    container = job_frontend._outer_container("Outer Title", Text("content"))
    text = render_to_text(container)
    assert "Outer Title" in text
    assert "content" in text

    slots = job_frontend.UISlots(order=("status",))
    slots.set("status", Text("Hello"))
    outer = job_frontend.LiveOuter("Qibo", slots)
    text = render_to_text(outer)
    assert "Hello" in text
    assert "Qibo" in text


def test_ui_slots_renderable_and_validation():
    ui = job_frontend.UISlots(order=("header", "footer"))
    ui.set("header", Text("Top"))
    ui.set("footer", Text("Bottom"))
    text = render_to_text(ui.renderable())
    assert "Top" in text and "Bottom" in text

    with pytest.raises(KeyError):
        ui.set("unknown", Text("fail"))


def test_ui_slots_empty_renderable():
    ui = job_frontend.UISlots(order=("header",))
    result = ui.renderable()
    assert isinstance(result, Text)
    assert result.plain == ""


def test_non_blocking_key_reader_non_tty(monkeypatch):
    """NonBlockingKeyReader degrades gracefully when stdin is not a TTY."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with job_frontend.NonBlockingKeyReader() as reader:
        assert not reader.active
        assert reader.get_key() is None


def test_non_blocking_key_reader_not_isatty(monkeypatch):
    """Cover lines 98-99: fileno succeeds but isatty returns False."""
    fake_fd = 99
    monkeypatch.setattr(
        "sys.stdin", type("FakeStdin", (), {"fileno": lambda self: fake_fd})()
    )
    monkeypatch.setattr(job_frontend.os, "isatty", lambda fd: False)

    with job_frontend.NonBlockingKeyReader() as reader:
        assert not reader.active
        assert reader._fd is None


def test_capture_circuit_drawing_none():
    assert job_frontend._capture_circuit_drawing(None) is None


def test_capture_circuit_drawing_valid():
    import qibo

    circ = qibo.Circuit(2)
    circ.add(qibo.gates.H(0))
    circ.add(qibo.gates.CNOT(0, 1))
    result = job_frontend._capture_circuit_drawing(circ.raw)
    assert result is not None
    assert isinstance(result, str)


def test_capture_circuit_drawing_invalid():
    assert job_frontend._capture_circuit_drawing({"invalid": True}) is None


def test_circuit_summary_none():
    assert job_frontend._circuit_summary(None) is None


def test_circuit_summary_valid():
    import qibo

    circ = qibo.Circuit(2)
    circ.add(qibo.gates.H(0))
    circ.add(qibo.gates.CNOT(0, 1))
    result = job_frontend._circuit_summary(circ.raw)
    assert result is not None
    assert result["nqubits"] == 2
    assert result["ngates"] == 2
    assert "h" in result["gate_names"]
    assert "cx" in result["gate_names"]


def test_circuit_summary_invalid():
    assert job_frontend._circuit_summary({"invalid": True}) is None


def test_status_icon_all_variants():
    for status in (
        "QUEUEING",
        "PENDING",
        "RUNNING",
        "POSTPROCESSING",
        "SUCCESS",
        "ERROR",
    ):
        icon = job_frontend._status_icon(status)
        assert icon is not None

    unknown = job_frontend._status_icon("UNKNOWN")
    assert isinstance(unknown, Text)
    assert unknown.plain == "?"


def test_build_circuit_panel_with_valid_circuit():
    import qibo

    circ = qibo.Circuit(2)
    circ.add(qibo.gates.H(0))
    circ.add(qibo.gates.CNOT(0, 1))
    panel = job_frontend.build_circuit_panel(circ.raw, nshots=100)
    assert panel is not None
    text = render_to_text(panel)
    assert "circuit summary" in text
    assert "nshots" in text
    assert "100" in text


def test_build_circuit_panel_none():
    assert job_frontend.build_circuit_panel(None, nshots=None) is None


def test_outer_container_with_elapsed_and_keybind():
    import time

    timer = job_frontend.ElapsedTimer(start_time=time.perf_counter())
    container = job_frontend._outer_container(
        "Title", Text("body"), elapsed_timer=timer, keybind_hint="[dim]press c[/]"
    )
    text = render_to_text(container)
    assert "Title" in text
    assert "body" in text


def test_live_outer_rich_measure():
    from rich.measure import Measurement

    slots = job_frontend.UISlots(order=("status",))
    slots.set("status", Text("Hello"))
    outer = job_frontend.LiveOuter("Test", slots)
    console = Console(width=80)
    opts = console.options
    m = outer.__rich_measure__(console, opts)
    assert isinstance(m, Measurement)


def test_elapsed_timer_renders():
    import time

    timer = job_frontend.ElapsedTimer(start_time=time.perf_counter())
    console = Console(width=80, record=True)
    console.print(timer)
    text = console.export_text()
    assert "elapsed" in text


def test_pending_panel_with_info():
    panel = job_frontend._pending_panel(3, 120)
    text = render_to_text(panel)
    assert "3" in text
    assert "0:02:00" in text


def test_log_status_non_tty_not_verbose():
    last, printed = job_frontend.log_status_non_tty(
        verbose=False,
        last_status=None,
        printed_pending_with_info=False,
        job_status="RUNNING",
        qpos=None,
        etd=None,
    )
    assert last is None
    assert printed is False


def test_log_status_non_tty_queueing(caplog):
    caplog.set_level(logging.INFO, logger="qibo_client.config_logging")
    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=None,
        printed_pending_with_info=False,
        job_status="QUEUEING",
        qpos=None,
        etd=None,
    )
    assert last == "QUEUEING"
    assert "* Job QUEUEING" in caplog.messages


def test_log_status_non_tty_running(caplog):
    caplog.set_level(logging.INFO, logger="qibo_client.config_logging")
    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=None,
        printed_pending_with_info=False,
        job_status="RUNNING",
        qpos=None,
        etd=None,
    )
    assert last == "RUNNING"
    assert "> Job RUNNING" in caplog.messages


def test_log_status_non_tty_error(caplog):
    caplog.set_level(logging.INFO, logger="qibo_client.config_logging")
    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=None,
        printed_pending_with_info=False,
        job_status="ERROR",
        qpos=None,
        etd=None,
    )
    assert last == "ERROR"
    assert "x Job ERROR" in caplog.messages


def test_log_status_non_tty_pending_with_initial_info(caplog):
    caplog.set_level(logging.INFO, logger="qibo_client.config_logging")
    last, printed = job_frontend.log_status_non_tty(
        verbose=True,
        last_status=None,
        printed_pending_with_info=False,
        job_status="PENDING",
        qpos=5,
        etd=60,
    )
    assert last == "PENDING"
    assert printed is True
    assert "position in queue: 5" in caplog.messages[-1]


def test_final_banner_error():
    panel = job_frontend.build_final_banner(
        "ERROR", pid="pid-err", device="qpu-x", project=None
    )
    text = render_to_text(panel)
    assert "ERROR" in text
    assert "pid-err" in text
    assert panel.border_style == "red"


def test_final_banner_no_device_no_project():
    panel = job_frontend.build_final_banner(
        "SUCCESS", pid="pid-1", device=None, project=None
    )
    text = render_to_text(panel)
    assert "pid-1" in text


def test_non_blocking_key_reader_tty_path(monkeypatch):
    """Cover NonBlockingKeyReader lines 97-102, 110: full TTY enter/exit/get_key."""
    fake_fd = 99
    old_settings = [1, 2, 3]  # fake termios settings

    monkeypatch.setattr(
        "sys.stdin", type("FakeStdin", (), {"fileno": lambda self: fake_fd})()
    )
    monkeypatch.setattr(job_frontend.os, "isatty", lambda fd: True)
    monkeypatch.setattr(job_frontend.termios, "tcgetattr", lambda fd: old_settings)
    monkeypatch.setattr(job_frontend.tty, "setcbreak", lambda fd: None)

    restore_calls = []
    monkeypatch.setattr(
        job_frontend.termios,
        "tcsetattr",
        lambda fd, when, settings: restore_calls.append((fd, when, settings)),
    )

    with job_frontend.NonBlockingKeyReader() as reader:
        assert reader.active is True
        assert reader._fd == fake_fd
        assert reader._old_settings == old_settings

    # __exit__ should have restored settings
    assert len(restore_calls) == 1
    assert restore_calls[0][0] == fake_fd
    assert restore_calls[0][2] == old_settings


def test_non_blocking_key_reader_get_key_with_data(monkeypatch):
    """Cover NonBlockingKeyReader lines 116-119: get_key when data available."""
    reader = job_frontend.NonBlockingKeyReader()
    reader._fd = 99
    reader.active = True

    monkeypatch.setattr(
        job_frontend.select, "select", lambda r, w, x, t: ([99], [], [])
    )
    monkeypatch.setattr(job_frontend.os, "read", lambda fd, n: b"x")

    assert reader.get_key() == "x"


def test_non_blocking_key_reader_get_key_no_data(monkeypatch):
    """Cover NonBlockingKeyReader line 119: get_key returns None when no data."""
    reader = job_frontend.NonBlockingKeyReader()
    reader._fd = 99
    reader.active = True

    monkeypatch.setattr(job_frontend.select, "select", lambda r, w, x, t: ([], [], []))

    assert reader.get_key() is None


def test_elapsed_timer_rich_measure():
    """Cover ElapsedTimer.__rich_measure__ lines 269-271."""
    import time

    from rich.measure import Measurement

    timer = job_frontend.ElapsedTimer(start_time=time.perf_counter())
    c = Console(width=80)
    m = timer.__rich_measure__(c, c.options)
    assert isinstance(m, Measurement)
    assert m.minimum == 15
    assert m.maximum == 25
