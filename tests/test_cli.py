import sys
import threading

import pytest

from maplebot.__main__ import main


@pytest.mark.parametrize("capture_only", [False, True])
def test_dashboard_restart_closes_old_session_before_relaunching_same_mode(
    monkeypatch, tmp_path, capture_only
):
    events = []
    config = tmp_path / "restart settings.toml"
    config.write_text("", encoding="utf-8")
    arguments = ["maplebot", "--config", str(config), "debug"]
    if capture_only:
        arguments.append("--capture-only")

    class App:
        def __init__(self, config, *, capture_only):
            assert capture_only is ("--capture-only" in arguments)
            self.closed = threading.Event()

        def start(self):
            events.append("started")

        def close(self):
            events.append("keys and workers closed")

    class Server:
        def shutdown(self):
            events.append("server stopped")

        def server_close(self):
            events.append("socket closed")

    def serve(app, port, *, on_restart):
        on_restart()
        return Server()

    def popen(argv):
        events.append("relaunch")
        assert argv == [sys.executable, "-m", "maplebot", *arguments[1:]]

    def exit_process(code):
        events.append(f"exit {code}")

    monkeypatch.setattr("sys.argv", arguments)
    monkeypatch.setattr("maplebot.runtime.Application", App)
    monkeypatch.setattr("maplebot.debugger.serve", serve)
    monkeypatch.setattr("subprocess.Popen", popen)
    monkeypatch.setattr("os._exit", exit_process)

    main()

    assert events == [
        "started",
        "keys and workers closed",
        "server stopped",
        "socket closed",
        "relaunch",
        "exit 0",
    ]
