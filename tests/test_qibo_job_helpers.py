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


def test_final_banner_contains_metadata():
    panel = job_frontend.build_final_banner(
        "SUCCESS", pid="pid-123", device="qpu-a", project="prj"
    )
    text = render_to_text(panel)
    assert "pid-123" in text
    assert "qpu-a" in text
    assert "prj" in text
    assert panel.border_style == "green"


def test_outer_container_and_outer_render_title():
    container = job_frontend._outer_container("Outer Title", Text("content"))
    text = render_to_text(container)
    assert "content" in text

    slots = job_frontend.UISlots(order=("status",))
    slots.set("status", Text("Hello"))
    outer = job_frontend.LiveOuter("Qibo", "1.0.0", slots)
    text = render_to_text(outer)
    assert "Hello" in text


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


def test_outer_container_with_elapsed():
    import time

    timer = job_frontend.ElapsedTimer(start_time=time.perf_counter())
    container = job_frontend._outer_container(
        "Title", Text("body"), elapsed_timer=timer, version="1.0.0"
    )
    text = render_to_text(container)
    assert "body" in text


def test_live_outer_rich_measure():
    from rich.measure import Measurement

    slots = job_frontend.UISlots(order=("status",))
    slots.set("status", Text("Hello", style="gray"))
    outer = job_frontend.LiveOuter("Test", "1.0.0", slots)
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
