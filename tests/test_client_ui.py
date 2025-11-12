import pytest
from rich.panel import Panel
from rich.table import Table

from qibo_client.ui import client_ui


@pytest.fixture
def sample_quota():
    return {
        "user": {"email": "user@example.com"},
        "kbs_left": 500.0,
        "kbs_max": 1000.0,
    }


@pytest.fixture
def sample_projectquotas():
    return [
        {
            "project": "proj-a",
            "partition": {
                "name": "device-a",
                "max_num_qubits": 12,
                "hardware_type": "qpu",
                "description": "fast device",
                "status": "available",
            },
            "seconds_left": 120.5,
            "shots_left": 10,
            "jobs_left": 2,
        },
        {
            "project": "proj-b",
            "partition": {
                "name": "device-b",
                "max_num_qubits": 8,
                "hardware_type": "sim",
                "description": "slow device",
                "status": "maintenance",
            },
            "seconds_left": 0.0,
            "shots_left": 0,
            "jobs_left": 0,
        },
    ]


@pytest.fixture
def sample_jobs():
    return [
        {
            "pid": "pid-1",
            "created_at": "2023-01-01T00:00:00",
            "updated_at": "2023-01-01T00:00:10",
            "status": "success",
            "result_path": "/results/1",
        },
        {
            "pid": "pid-2",
            "created_at": "2023-01-02T00:00:00",
            "updated_at": "2023-01-02T00:00:10",
            "status": "failed",
            "result_path": "/results/2",
        },
    ]


def test_quota_rows_from_payload(sample_projectquotas):
    rows = client_ui._quota_rows_from_payload(sample_projectquotas)
    assert rows[0][0] == "proj-a"
    assert rows[1][-1] == 0


def test_jobs_rows_from_payload(sample_jobs):
    timestamps = []

    def fmt(ts):
        timestamps.append(ts)
        return f"formatted:{ts}"

    rows = client_ui._jobs_rows_from_payload(sample_jobs, fmt)

    assert timestamps == [
        "2023-01-01T00:00:00",
        "2023-01-01T00:00:10",
        "2023-01-02T00:00:00",
        "2023-01-02T00:00:10",
    ]
    assert rows[0][1].startswith("formatted:")


def test_render_quota_fallback_logs_table(
    monkeypatch, sample_quota, sample_projectquotas
):
    logged = []
    monkeypatch.setattr(
        client_ui.logger, "info", lambda message: logged.append(message)
    )

    def fake_tabulate(rows, headers):
        assert rows == client_ui._quota_rows_from_payload(sample_projectquotas)
        assert "Project Name" in headers[0]
        return "TABULATED"

    monkeypatch.setattr(client_ui.tabulate, "tabulate", fake_tabulate)

    client_ui.render_quota_fallback(sample_quota, sample_projectquotas)

    assert len(logged) == 1
    assert "user@example.com" in logged[0]
    assert logged[0].endswith("TABULATED")


def test_render_jobs_fallback_logs_table(monkeypatch, sample_jobs):
    logged = []
    monkeypatch.setattr(
        client_ui.logger, "info", lambda message: logged.append(message)
    )

    def fake_tabulate(rows, headers):
        assert rows == client_ui._jobs_rows_from_payload(sample_jobs, str)
        assert headers[0] == "Pid"
        return "TABULATED"

    monkeypatch.setattr(client_ui.tabulate, "tabulate", fake_tabulate)

    client_ui.render_jobs_fallback("user@example.com", sample_jobs, str)

    assert logged == ["User: user@example.com\nTABULATED"]


def test_render_quota_rich_prints_panel(
    monkeypatch, sample_quota, sample_projectquotas
):
    printed = []

    class DummyConsole:
        def print(self, panel):
            printed.append(panel)

    monkeypatch.setattr(client_ui, "console", DummyConsole())

    client_ui.render_quota_rich(sample_quota, sample_projectquotas)

    assert len(printed) == 1
    panel = printed[0]
    assert isinstance(panel, Panel)
    assert panel.title == "Quota Information"
    assert isinstance(panel.renderable, Table)
    assert panel.renderable.row_count == len(sample_projectquotas)
    assert panel.subtitle is not None and "Disk quota used" in panel.subtitle


def test_render_jobs_rich_prints_panel(monkeypatch, sample_jobs):
    printed = []

    class DummyConsole:
        def print(self, panel):
            printed.append(panel)

    monkeypatch.setattr(client_ui, "console", DummyConsole())

    client_ui.render_jobs_rich("user@example.com", sample_jobs, str)

    panel = printed[0]
    assert isinstance(panel, Panel)
    assert panel.title == "Job Information"
    assert panel.renderable.row_count == len(sample_jobs)
    status_cells = panel.renderable.columns[3]._cells
    assert status_cells[0] == "[green]success[/green]"
    assert status_cells[1] == "[red]failed[/red]"


def test_render_quota_dispatch(monkeypatch, sample_quota, sample_projectquotas):
    called = []
    monkeypatch.setattr(
        client_ui, "render_quota_rich", lambda *args: called.append("rich")
    )
    monkeypatch.setattr(
        client_ui, "render_quota_fallback", lambda *args: called.append("fallback")
    )

    monkeypatch.setattr(client_ui, "USE_RICH_UI", True)
    client_ui.render_quota(sample_quota, sample_projectquotas)
    assert called == ["rich"]

    called.clear()
    monkeypatch.setattr(client_ui, "USE_RICH_UI", False)
    client_ui.render_quota(sample_quota, sample_projectquotas)
    assert called == ["fallback"]


def test_render_jobs_dispatch(monkeypatch, sample_jobs):
    called = []
    monkeypatch.setattr(
        client_ui, "render_jobs_rich", lambda *args: called.append("rich")
    )
    monkeypatch.setattr(
        client_ui, "render_jobs_fallback", lambda *args: called.append("fallback")
    )

    monkeypatch.setattr(client_ui, "USE_RICH_UI", True)
    client_ui.render_jobs("user@example.com", sample_jobs, str)
    assert called == ["rich"]

    called.clear()
    monkeypatch.setattr(client_ui, "USE_RICH_UI", False)
    client_ui.render_jobs("user@example.com", sample_jobs, str)
    assert called == ["fallback"]
