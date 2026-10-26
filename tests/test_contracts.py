import threading
import time

import pytest

from maplebot.contracts import CommandContext, CommandGate, catalog_warning, readiness


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


def test_fresh_read_only_preview_cannot_authorize_input_from_stale_recognition():
    status = snapshot()
    status["frame"]["age_ms"] = 5000
    status["preview_frame"] = {"id": "preview:99", "available": True, "age_ms": 10}
    assert not readiness(status)["combat"]["ready"]
    with pytest.raises(ValueError, match="fresh matching frame"):
        CommandGate().accept(envelope(), status)



def test_gate_accepts_three_fps_latency_but_not_older_frames():
    status = snapshot()
    status["frame"] = {"id": "session:7", "available": True, "age_ms": 1200}
    assert readiness(status)["preview"]["ready"]
    CommandGate().accept(envelope(command_id="seen-frame", expected_frame_id="session:7"), status)
    CommandGate().accept(envelope(command_id="next-frame", expected_frame_id="session:6"), status)
    with pytest.raises(ValueError, match="fresh matching frame"):
        CommandGate().accept(envelope(expected_frame_id="session:5"), status)
    status["frame"]["age_ms"] = 1600
    assert not readiness(status)["preview"]["ready"]
    with pytest.raises(ValueError, match="fresh matching frame"):
        CommandGate().accept(envelope(expected_frame_id="session:7"), status)


def test_fresh_command_context_tolerates_one_slow_worker_loop():
    CommandContext(2, time.time() - 1.2).validate(2, max_age=1.5)
    with pytest.raises(ValueError, match="expired"):
        CommandContext(2, time.time() - 2).validate(2, max_age=1.5)

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
    status["frame"]["age_ms"] = 1501
    assert not readiness(status)["preview"]["ready"]


def test_blocked_reasons_name_the_lag_and_the_paused_catalog():
    status = snapshot()
    status["frame"]["age_ms"] = 4200
    assert readiness(status)["preview"]["reason"] == (
        "Recognition is 4.2 s behind the game picture (limit 1.5 s)"
    )
    assert catalog_warning({"catalog_paused": False}) is None
    assert "minimap visible" in catalog_warning({"catalog_paused": True})
    failed = {"catalog_paused": True, "map_filter_error": "OCR missing"}
    assert "OCR missing" in catalog_warning(failed)
