import socket
import threading
from types import SimpleNamespace

import pytest
from test_debugger import RestartApp

from maplebot.__main__ import _shutdown
from maplebot.debugger import serve


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_shutdown_releases_input_and_closes_listener_before_background_cleanup(cleanup_fails):
    app = RestartApp()
    app.closed = threading.Event()
    app.controller = SimpleNamespace(stop=lambda *a, **k: app.held.clear())
    cleaning = threading.Event()
    finish = threading.Event()
    errors = []

    def close():
        assert not app.held and app.closed.is_set()
        cleaning.set()
        assert finish.wait(2)
        if cleanup_fails:
            raise RuntimeError("Cleanup failed")

    app.close = close
    server = serve(app, 0)
    port = server.server_port

    def shutdown():
        try:
            _shutdown(app, server)
        except Exception as error:
            errors.append(str(error))

    worker = threading.Thread(target=shutdown, daemon=True)
    worker.start()
    try:
        assert cleaning.wait(2)
        assert not app.held
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=.2)
    finally:
        finish.set()
        worker.join(2)
    assert not worker.is_alive()
    assert errors == (["Cleanup failed"] if cleanup_fails else [])


@pytest.mark.parametrize("startup_fails", [False, True])
def test_debug_main_finishes_shutdown_even_when_startup_fails(monkeypatch, startup_fails):
    from maplebot import __main__, debugger, runtime
    from maplebot.config import Config

    running = {}

    class App(RestartApp):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.closed = threading.Event()
            self.controller = SimpleNamespace(stop=lambda *a, **k: self.held.clear())
            running["app"] = self

        def start(self):
            if startup_fails:
                raise RuntimeError("Startup failed")
            running["shutdown"]()

        def close(self):
            assert not self.held
            running["cleaned"] = True

    def server(app, port, **callbacks):
        running["shutdown"] = callbacks["on_shutdown"]
        running["server"] = serve(app, 0, **callbacks)
        return running["server"]

    monkeypatch.setattr(runtime, "Application", App)
    monkeypatch.setattr(debugger, "serve", server)
    monkeypatch.setattr(Config, "load", lambda path: Config())
    monkeypatch.setattr("sys.argv", ["maplebot", "debug", "--capture-only"])
    if startup_fails:
        with pytest.raises(RuntimeError, match="Startup failed"):
            __main__.main()
    else:
        __main__.main()
    assert running["cleaned"] and running["app"].closed.is_set()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", running["server"].server_port), timeout=.2)
