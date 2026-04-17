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


def test_quota_rows(sample_projectquotas):
    rows = client_ui._quota_rows(sample_projectquotas)
    assert rows[0][0] == "proj-a"
    assert rows[1][-1] == 0


def test_jobs_rows(sample_jobs):
    timestamps = []

    def fmt(ts):
        timestamps.append(ts)
        return f"formatted:{ts}"

    rows = client_ui._jobs_rows(sample_jobs, fmt)

    assert len(timestamps) == 4
    assert rows[0][1].startswith("formatted:")


def test_render_quota_fallback(monkeypatch, sample_quota, sample_projectquotas):
    monkeypatch.setattr(client_ui, "USE_RICH_UI", False)

    # Need to patch the logger inside the function's local import scope if possible,
    # but client_ui.py does: from ..config_logging import logger
    import qibo_client.config_logging

    logged = []
    monkeypatch.setattr(
        qibo_client.config_logging.logger, "info", lambda m: logged.append(m)
    )

    client_ui.render_quota(sample_quota, sample_projectquotas)
    assert len(logged) == 1
    assert "user@example.com" in logged[0]


def test_render_jobs_fallback(monkeypatch, sample_jobs):
    monkeypatch.setattr(client_ui, "USE_RICH_UI", False)

    import qibo_client.config_logging

    logged = []
    monkeypatch.setattr(
        qibo_client.config_logging.logger, "info", lambda m: logged.append(m)
    )

    client_ui.render_jobs("user@example.com", sample_jobs, str)
    assert len(logged) == 1
    assert "user@example.com" in logged[0]


def test_render_quota_rich(monkeypatch, sample_quota, sample_projectquotas):
    monkeypatch.setattr(client_ui, "USE_RICH_UI", True)
    printed = []

    class DummyConsole:
        def print(self, panel):
            printed.append(panel)

    monkeypatch.setattr(client_ui, "console", DummyConsole())

    client_ui.render_quota(sample_quota, sample_projectquotas)
    assert len(printed) == 1
    assert isinstance(printed[0], Panel)
    assert printed[0].title == "Quota Information"


def test_render_jobs_rich(monkeypatch, sample_jobs):
    monkeypatch.setattr(client_ui, "USE_RICH_UI", True)
    printed = []

    class DummyConsole:
        def print(self, panel):
            printed.append(panel)

    monkeypatch.setattr(client_ui, "console", DummyConsole())

    client_ui.render_jobs("user@example.com", sample_jobs, str)
    assert len(printed) == 1
    assert isinstance(printed[0], Panel)
    assert printed[0].title == "Job Information"
