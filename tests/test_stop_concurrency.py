"""Barrier-controlled controller callbacks versus real application snapshots; fake input only."""
import threading
import time

import pytest
from test_runtime import app  # noqa: F401

from maplebot.decision import Action
from maplebot.keyboard import InputObservation


@pytest.mark.parametrize("failure", ["safety", "observation"])
def test_executor_stop_and_concurrent_status_complete(app, monkeypatch, failure):  # noqa: F811
    controller = app.controller
    executor_ready = threading.Event()
    snapshot_ready = threading.Event()
    callback_done = threading.Event()
    callback_locks = []
    original_safe = controller.safe
    original_snapshot = controller.state_snapshot
    original_callback = controller.on_stop
    now = time.perf_counter()
    observation = InputObservation(now, now + 10, 1, 1, 1)

    def meet_status():
        executor_ready.set()
        assert snapshot_ready.wait(2)

    def safe():
        if failure == "safety" and threading.current_thread() is controller.executor:
            meet_status()
            return False
        return original_safe()

    def observe():
        if failure == "observation" and threading.current_thread() is controller.executor:
            meet_status()
            return None
        return observation

    def snapshot():
        if threading.current_thread().name == "concurrent-status":
            assert app.stop_lock._is_owned()
            snapshot_ready.set()
        return original_snapshot()

    def stopped(code, reason):
        owned = controller.lock._is_owned()
        callback_locks.append(owned)
        # Fail before entering the historical deadlock, keeping failure bounded.
        if owned:
            callback_done.set()
            return
        original_callback(code, reason)
        callback_done.set()

    monkeypatch.setattr(controller, "safe", safe)
    monkeypatch.setattr(controller, "observation", observe)
    monkeypatch.setattr(controller, "state_snapshot", snapshot)
    monkeypatch.setattr(controller, "on_stop", stopped)
    controller.enable()
    assert isinstance(controller.submit(Action("left", .1)), int)
    assert executor_ready.wait(2)
    status = threading.Thread(target=app.snapshot, name="concurrent-status", daemon=True)
    status.start()
    assert callback_done.wait(2)
    status.join(2)
    assert not status.is_alive()
    assert callback_locks and not any(callback_locks)
    app.request("stop", {})
    assert app.snapshot()["input_state"]["enabled"] is False
    assert not controller.held
    assert not any(down for _, down in controller.backend.events)

