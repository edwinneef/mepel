import threading
import time

import pytest

from maplebot.contracts import CommandContext, CommandGate, readiness


def snapshot():
    return {
        "session_id": "session", "command_epoch": 2,
        "frame": {"id": "session:1", "available": True, "age_ms": 20},
        "calibration": {"capture_verified": True}, "player": {"confidence": 0.99},
    }


def envelope(**changes):
    return {
        "schema_version": 1, "session_id": "session", "command_id": "command-1",
        "command_epoch": 2, "issued_at": time.time(), "expected_frame_id": "session:1",
        "name": "arm", "payload": {}, **changes,
    }


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"session_id": "old"}, {"command_epoch": 1},
    {"issued_at": 0}, {"issued_at": float("nan")}, {"name": "unknown"},
    {"expected_frame_id": "old"}, {"payload": []}, {"payload": {"_context": 1}},
])
def test_gate_refuses_stale_or_invalid_commands_without_dispatch(change):
    with pytest.raises(ValueError):
        CommandGate().accept(envelope(**change), snapshot())


def test_concurrent_duplicate_is_reserved_once():
    gate = CommandGate()
    accepted = []

    def submit():
        try:
            gate.accept(envelope(), snapshot())
            accepted.append(True)
        except ValueError:
            pass

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert accepted == [True]


def test_stop_is_allowed_with_a_stale_view_but_not_a_wrong_session():
    gate = CommandGate()
    assert gate.accept(envelope(name="stop", command_epoch=0, issued_at=0), snapshot())[0] == "stop"
    with pytest.raises(ValueError, match="Session"):
        gate.accept(envelope(name="stop", session_id="old"), snapshot())


def test_queued_context_expires_when_a_stop_supersedes_it():
    context = CommandContext(2, time.time())
    with pytest.raises(ValueError, match="superseded"):
        context.validate(3)


def test_readiness_separates_capture_only_preview_from_combat():
    status = snapshot()
    status["capture_only"] = True
    gates = readiness(status)
    assert gates["preview"]["ready"]
    assert not gates["combat"]["ready"]
    status["frame"]["age_ms"] = 501
    assert not readiness(status)["preview"]["ready"]
