"""Deterministic probe/Stop interleavings; fake input only."""
# ruff: noqa: F811
import threading

import pytest
from test_runtime import app  # noqa: F401


def test_stop_during_probe_preparation_wins(app, monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    errors = []

    def save():
        entered.set()
        assert resume.wait(2)

    def prepare():
        try:
            app.request_probe({"action": "left"})
        except ValueError as error:
            errors.append(str(error))

    monkeypatch.setattr(app, "_save_probes", save)
    worker = threading.Thread(target=prepare)
    worker.start()
    assert entered.wait(2)
    app.request("stop", {})
    resume.set()
    worker.join(2)
    assert not worker.is_alive()
    assert errors == ["Probe request cancelled by Stop"]
    assert app.active_probe is None and app.mode == "capture"
    assert app.stop_requested.is_set()
    assert not app.controller.enabled and not app.controller.held
    assert not any(down for _, down in app.controller.backend.events)


@pytest.mark.parametrize("name", ["probe", "confirm_probe", "reject_probe"])
def test_probe_http_requests_are_worker_owned_and_stop_invalidates_queue(app, name):
    errors = []
    ready = threading.Event()
    original_put = app.commands.put

    def put(item):
        original_put(item)
        ready.set()

    app.commands.put = put

    def request():
        try:
            app.request(name, {"action": "left"})
        except ValueError as error:
            errors.append(str(error))

    thread = threading.Thread(target=request)
    thread.start()
    assert ready.wait(2)
    assert app.active_probe is None
    app.request("stop", {})
    app._drain_commands()
    thread.join(2)
    assert not thread.is_alive() and errors
    assert app.active_probe is None and app.stop_requested.is_set()
