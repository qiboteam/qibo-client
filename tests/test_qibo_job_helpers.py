import logging

import pytest
from rich.console import Console
from rich.spinner import Spinner
from rich.text import Text

from qibo_client.qibo_job import QiboJobStatus
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
    assert caplog.messages[-1] == "✅ Job SUCCESS"


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

    assert caplog.messages[-1] == "🕒 Job PENDING"
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
        caplog.messages[-1]
        == "🕒 Job PENDING -> position in queue: 3, max ETD: 0:02:00"
    )


def test_status_icon_variants():
    pending_icon = job_frontend._status_icon("PENDING")
    assert pending_icon.columns[1]._cells and isinstance(
        pending_icon.columns[1]._cells[0], Spinner
    )

    success_icon = job_frontend._status_icon("SUCCESS")
    assert isinstance(success_icon, Text)
    assert success_icon.plain == "✅"


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


def test_pending_panel_waits_for_info():
    panel = job_frontend._pending_panel(None, None)
    text = render_to_text(panel)
    assert "waiting for queue info" in text


def test_final_banner_contains_metadata():
    panel = job_frontend.build_final_banner(
        "SUCCESS", pid="pid-123", device="qpu-a", elapsed_seconds=90
    )
    text = render_to_text(panel)
    assert "pid pid-123" in text
    assert "device qpu-a" in text
    assert "elapsed 0:01:30" in text
    assert panel.border_style == "green"


def test_build_event_panel_and_job_posted_panel():
    panel = job_frontend._build_event_panel("Test Event", "details", icon="⭐")
    text = render_to_text(panel)
    assert "Test Event" in text
    assert "details" in text

    job_panel = job_frontend.build_event_job_posted_panel("device-a", "pid-1")
    job_text = render_to_text(job_panel)
    assert "Job posted on device-a" in job_text
    assert "pid pid-1" in job_text


def test_outer_container_and_outer_render_title():
    panel = job_frontend._outer_container("Outer Title", Text("content"))
    assert panel.title == "[bold magenta]Outer Title[/]"

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
