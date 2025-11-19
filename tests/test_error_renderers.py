import builtins

import pytest
from rich.panel import Panel
from rich.table import Table

from qibo_client.exceptions.errors import QiboApiError
from qibo_client.ui import error_renderers


@pytest.fixture
def api_error():
    return QiboApiError(
        status=404,
        method="GET",
        url="https://example.com",
        message="Not Found",
    )


def test_build_api_error_panel_structure(api_error):
    panel = error_renderers._build_api_error_panel(api_error)

    assert isinstance(panel, Panel)
    assert panel.title == "Request failed"
    assert panel.border_style == "red"
    assert isinstance(panel.renderable, Table)

    body_cell = panel.renderable.columns[0]._cells[-1]
    assert hasattr(body_cell, "plain") and api_error.message in body_cell.plain


def test_print_api_error_with_rich_and_panel(monkeypatch, api_error):
    printed = []

    class DummyConsole:
        def print(self, *args, **kwargs):
            printed.append((args, kwargs))

    monkeypatch.setattr(error_renderers, "USE_RICH_UI", True)
    monkeypatch.setattr(error_renderers, "console", DummyConsole())
    panel = object()
    monkeypatch.setattr(error_renderers, "_build_api_error_panel", lambda error: panel)

    error_renderers.print_api_error(api_error)

    assert printed == [((panel,), {})]


def test_print_api_error_with_rich_without_panel(monkeypatch, api_error):
    printed = []

    class DummyConsole:
        def print(self, *args, **kwargs):
            printed.append((args, kwargs))

    monkeypatch.setattr(error_renderers, "USE_RICH_UI", True)
    monkeypatch.setattr(error_renderers, "console", DummyConsole())
    monkeypatch.setattr(error_renderers, "_build_api_error_panel", lambda error: None)

    error_renderers.print_api_error(api_error)

    assert printed == [((api_error.summary(),), {"style": "bold red"})]


def test_print_api_error_plain_fallback(monkeypatch, api_error):
    captured = []
    monkeypatch.setattr(error_renderers, "USE_RICH_UI", False)
    monkeypatch.setattr(error_renderers, "console", None)
    monkeypatch.setattr(builtins, "print", lambda message: captured.append(message))

    error_renderers.print_api_error(api_error)

    assert captured == [api_error.summary()]
