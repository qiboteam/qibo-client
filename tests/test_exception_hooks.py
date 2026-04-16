import asyncio
import importlib
import sys
import threading
import types

import pytest

from qibo_client.exceptions.errors import QiboApiError


@pytest.fixture
def hooks(monkeypatch):
    """Return a freshly reloaded hooks module with clean global state."""
    monkeypatch.setenv("QIBO_API_ERRORS_AUTO", "0")
    import qibo_client.exceptions.hooks as hooks_mod

    hooks_mod.uninstall_qibo_error_hooks()
    hooks_mod = importlib.reload(hooks_mod)
    yield hooks_mod
    hooks_mod.uninstall_qibo_error_hooks()
    hooks_mod.install_qibo_error_hooks()


def make_api_error(message: str = "boom"):
    return QiboApiError(status=400, method="GET", url="http://test", message=message)


def test_ipython_custom_exc_handler_invokes_renderer(monkeypatch, hooks):
    captured = []
    monkeypatch.setattr(hooks, "print_api_error", lambda exc: captured.append(exc))
    err = make_api_error()

    hooks._ipython_custom_exc_handler(None, QiboApiError, err, None)

    assert captured == [err]


def test_get_ipython_shell_returns_shell(monkeypatch, hooks):
    shell = object()
    fake_module = types.SimpleNamespace(get_ipython=lambda: shell)
    monkeypatch.setitem(sys.modules, "IPython", fake_module)
    monkeypatch.setattr(hooks.importlib, "import_module", lambda name: fake_module)

    assert hooks._get_ipython_shell() is shell


def test_get_ipython_shell_missing_getter(monkeypatch, hooks):
    fake_module = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "IPython", fake_module)
    monkeypatch.setattr(hooks.importlib, "import_module", lambda name: fake_module)

    assert hooks._get_ipython_shell() is None


def test_qibo_sys_excepthook_renders_api_errors(monkeypatch, hooks):
    err = make_api_error()
    captured = []
    monkeypatch.setattr(hooks, "print_api_error", lambda exc: captured.append(exc))

    hooks._qibo_sys_excepthook(QiboApiError, err, None)

    assert captured == [err]


def test_qibo_sys_excepthook_delegates_to_previous(hooks):
    calls = []

    def previous(exc_type, exc_value, exc_tb):
        calls.append((exc_type, exc_value, exc_tb))

    hooks._prev_sys_excepthook = previous
    err = ValueError("not qibo")

    hooks._qibo_sys_excepthook(ValueError, err, None)

    assert calls == [(ValueError, err, None)]


def test_qibo_threading_excepthook_renders_api_errors(monkeypatch, hooks):
    err = make_api_error()
    captured = []
    monkeypatch.setattr(hooks, "print_api_error", lambda exc: captured.append(exc))
    args = types.SimpleNamespace(exc_value=err)

    hooks._qibo_threading_excepthook(args)

    assert captured == [err]


def test_qibo_threading_excepthook_delegates_to_previous(hooks):
    calls = []

    def previous(args):
        calls.append(args)

    hooks._prev_threading_excepthook = previous
    args = types.SimpleNamespace(exc_value=ValueError("nope"))

    hooks._qibo_threading_excepthook(args)

    assert calls == [args]


def test_qibo_asyncio_exception_handler_renders_api_errors(monkeypatch, hooks):
    err = make_api_error()
    captured = []
    monkeypatch.setattr(hooks, "print_api_error", lambda exc: captured.append(exc))
    loop = types.SimpleNamespace(default_exception_handler=lambda ctx: None)

    hooks._qibo_asyncio_exception_handler(loop, {"exception": err})

    assert captured == [err]


def test_qibo_asyncio_exception_handler_uses_default_for_other_errors(hooks):
    class DummyLoop:
        def __init__(self):
            self.captured = None

        def default_exception_handler(self, context):
            self.captured = context

    loop = DummyLoop()
    context = {"exception": ValueError("boom")}

    hooks._qibo_asyncio_exception_handler(loop, context)

    assert loop.captured is context


def test_install_and_uninstall_hooks_manage_global_state(monkeypatch, hooks):
    original_sys_hook = sys.excepthook
    original_thread_hook = getattr(threading, "excepthook", None)
    async_calls = []
    monkeypatch.setattr(
        hooks, "_install_asyncio_handler_if_running", lambda: async_calls.append(True)
    )

    class DummyShell:
        def __init__(self):
            self.calls = []

        def set_custom_exc(self, handled_types, handler):
            self.calls.append((handled_types, handler))

    shell = DummyShell()
    monkeypatch.setattr(hooks, "_get_ipython_shell", lambda: shell)

    assert hooks.install_qibo_error_hooks() is True
    assert sys.excepthook is hooks._qibo_sys_excepthook
    if hasattr(threading, "excepthook"):
        assert threading.excepthook is hooks._qibo_threading_excepthook
    assert async_calls == [True]
    assert shell.calls == [((QiboApiError,), hooks._ipython_custom_exc_handler)]

    assert hooks.install_qibo_error_hooks() is False

    assert hooks.uninstall_qibo_error_hooks() is True
    assert sys.excepthook is original_sys_hook
    if hasattr(threading, "excepthook"):
        assert threading.excepthook is original_thread_hook
    assert hooks.uninstall_qibo_error_hooks() is False


def test_asyncio_install_and_restore_helpers(hooks):
    async def runner():
        hooks._install_asyncio_handler_if_running()

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner())

        assert loop.get_exception_handler() is hooks._qibo_asyncio_exception_handler
        assert loop in hooks._prev_asyncio_handlers
        assert hooks._prev_asyncio_handlers[loop] is None

        hooks._uninstall_asyncio_handler_all_known_loops()
        assert loop.get_exception_handler() is None
        assert loop not in hooks._prev_asyncio_handlers
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_qibo_error_hooks_context_manager_installs_temporarily(hooks):
    original_sys_hook = sys.excepthook

    with hooks.qibo_error_hooks():
        assert sys.excepthook is hooks._qibo_sys_excepthook

    assert sys.excepthook is original_sys_hook


def test_get_ipython_shell_not_in_modules(monkeypatch, hooks):
    monkeypatch.delitem(sys.modules, "IPython", raising=False)
    assert hooks._get_ipython_shell() is None


def test_get_ipython_shell_import_error(monkeypatch, hooks):
    monkeypatch.setitem(sys.modules, "IPython", types.ModuleType("IPython"))
    monkeypatch.setattr(
        hooks.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError("no")),
    )
    assert hooks._get_ipython_shell() is None


def test_get_ipython_shell_get_ipython_raises(monkeypatch, hooks):
    def bad_get_ipython():
        raise RuntimeError("boom")

    fake_module = types.SimpleNamespace(get_ipython=bad_get_ipython)
    monkeypatch.setitem(sys.modules, "IPython", fake_module)
    monkeypatch.setattr(hooks.importlib, "import_module", lambda name: fake_module)
    assert hooks._get_ipython_shell() is None


def test_qibo_sys_excepthook_falls_back_to_sys_excepthook(hooks, monkeypatch):
    hooks._prev_sys_excepthook = None
    calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: calls.append(a))
    err = ValueError("test")
    hooks._qibo_sys_excepthook(ValueError, err, None)
    assert len(calls) == 1


def test_qibo_threading_excepthook_falls_back_to_threading(hooks, monkeypatch):
    hooks._prev_threading_excepthook = None
    calls = []
    monkeypatch.setattr(threading, "__excepthook__", lambda a: calls.append(a))
    args = types.SimpleNamespace(exc_value=ValueError("nope"))
    hooks._qibo_threading_excepthook(args)
    assert len(calls) == 1


def test_uninstall_asyncio_handler_handles_exception(hooks):
    class BadLoop:
        def set_exception_handler(self, handler):
            raise RuntimeError("loop closed")

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    loop = BadLoop()
    hooks._prev_asyncio_handlers[loop] = None
    # Should not raise
    hooks._uninstall_asyncio_handler_all_known_loops()
    assert loop not in hooks._prev_asyncio_handlers
