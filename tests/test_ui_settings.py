import builtins
import importlib
import sys
import types

import pytest

MODULE_PATH = "qibo_client.ui.settings"


def import_settings(monkeypatch, *, in_notebook=False, has_widgets=True):
    """Reload settings module under controlled IPython/ipywidgets availability."""
    sys.modules.pop(MODULE_PATH, None)

    def fake_get_ipython():
        if not in_notebook:
            return None
        return types.SimpleNamespace(kernel=object())

    ipy_module = types.ModuleType("IPython")
    ipy_module.get_ipython = fake_get_ipython
    monkeypatch.setitem(sys.modules, "IPython", ipy_module)

    if has_widgets:
        monkeypatch.setitem(sys.modules, "ipywidgets", types.ModuleType("ipywidgets"))
    else:
        sys.modules.pop("ipywidgets", None)

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "ipywidgets":
                raise ModuleNotFoundError("ipywidgets missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

    return importlib.import_module(MODULE_PATH)


def test_settings_jupyter_with_widgets(monkeypatch):
    settings = import_settings(monkeypatch, in_notebook=True, has_widgets=True)

    assert settings.IS_NOTEBOOK is True
    assert settings.RICH_NOTEBOOK is True
    assert settings.USE_RICH_UI is True
    assert settings.console.is_jupyter


def test_settings_jupyter_without_widgets(monkeypatch, caplog):
    caplog.set_level("WARNING")
    settings = import_settings(monkeypatch, in_notebook=True, has_widgets=False)

    assert settings.IS_NOTEBOOK is True
    assert settings.RICH_NOTEBOOK is False
    assert settings.USE_RICH_UI is False
    assert "ipywidgets is not installed" in "".join(caplog.messages)


def test_settings_terminal(monkeypatch):
    settings = import_settings(monkeypatch, in_notebook=False, has_widgets=False)

    assert settings.IS_NOTEBOOK is False
    assert settings.RICH_NOTEBOOK is False
    assert settings.USE_RICH_UI == settings.console.is_terminal
