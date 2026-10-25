import json
import time
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from maplebot.capture import Calibration
from maplebot.config import Config
from maplebot.contracts import CommandContext
from maplebot.geometry import Rect
from maplebot.runtime import REQUIRED_PROBES, STOP_REASONS, Application, StopSeverity
from maplebot.windows import Window


class FakeWindows:
    def __init__(self):
        self.window = Window(1, "MapleStory", Rect(0, 0, 1024, 768), True, 96)
        self.visible = True

    def get(self, hwnd):
        return self.window

    def unobscured(self, hwnd, region):
        return self.visible

    def pressed(self, key):
        return False


class Backend:
    def __init__(self):
        self.events = []

    def send(self, key, down):
        self.events.append((key, down))


class HoldingBackend(Backend):
    def __init__(self):
        super().__init__()
        self.down = False

    def send(self, key, down):
        super().send(key, down)
        self.down = down


def test_area_editing_bypasses_capture_queue_releases_keys_and_never_resumes(app):
    app.mode = "live"
    with app.controller.lock:
        app.controller.held["right"] = time.perf_counter() + 8
    assert app.request("area_begin", {}) == {"editing": True}
    assert app.controller.backend.events == [("right", False)]
    assert app.commands.empty() and not app._input_safe()
    assert app.snapshot()["area_editing"]
    assert "editing" in app.snapshot()["readiness"]["preview"]["reason"]
    for name in ("arm", "probe", "dry_run", "autopotter_live"):
        with pytest.raises(ValueError, match="Finish area editing"):
            app.request(name, {})
    assert app.request("area_end", {}) == {"editing": False}
    assert app.mode == "capture" and not app.controller.enabled
    assert app.stop_requested.is_set()


def test_area_save_requires_stopped_edit_mode_before_touching_data(app):
    with pytest.raises(ValueError, match="Begin area editing"):
        app.request("area_save", {"profile": {}})
    assert not (app.data / "areas").exists()


def test_area_capture_save_and_reload_use_immutable_views_while_stopped(app):
    class CurrentCapture:
        def window(self, hwnd, calibration):
            return app.image.copy(), app.window, app.region

    app.preview._capture_once(CurrentCapture())
    app.request("area_begin", {})
    view = app.request("area_capture", {})["view"]
    profile = {
        "schema_version": 1, "id": "b" * 32, "revision": 0, "name": "Taught area",
        "boundary": {"x": 0, "y": 0, "width": view["width"], "height": view["height"]},
        "views": [view], "zones": [], "platforms": [], "ropes": [], "links": [],
    }
    saved = app.request("area_save", {"profile": profile})["profile"]
    assert app.request("area_load", {"area_id": profile["id"]})["profile"] == saved
    assert app.request("area_list", {})["areas"][0]["revision"] == 1
    assert app.areas.frame(view["image"]).startswith(b"\x89PNG")
    assert app.area_editing and not app.controller.enabled and app.mode == "capture"
    assert app.controller.backend.events == []


def test_area_edit_started_during_arm_preparation_still_blocks_countdown(app, monkeypatch):
    app.probed.update(REQUIRED_PROBES)
    original = app.windows.get

    def interleaved_get(hwnd):
        app.request("area_begin", {})
        return original(hwnd)

    monkeypatch.setattr(app.windows, "get", interleaved_get)
    with pytest.raises(ValueError, match="Finish area editing"):
        app._command("arm", {})
    assert app.mode == "capture" and not app.controller.enabled
    assert app.controller.backend.events == []


def test_frozen_selection_uses_current_preview_without_refreshing_input_evidence(app):
    class CurrentCapture:
        def window(self, hwnd, calibration):
            return np.full_like(app.image, 37), app.window, app.region

    app.preview._capture_once(CurrentCapture())
    before = app.snapshot()["frame"]
    frozen = app._command("freeze", {})
    pixels, _, region = app.frozen[frozen["id"]]
    assert np.all(pixels == 37)
    assert region == app.region
    assert app.snapshot()["frame"] == before
    assert app.controller.backend.events == []


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("maplebot.runtime.Windows", FakeWindows)
    monkeypatch.setattr("maplebot.runtime.Win32Input", Backend)
    config = Config()
    config = replace(config, capture=replace(config.capture, data_dir=str(tmp_path)))
    app = Application(config)
    monkeypatch.setattr(app.alarm.backend, "play", lambda path: None)
    monkeypatch.setattr(app.alarm.backend, "stop", lambda: None)
    monkeypatch.setattr(app.alarm.backend, "beep", lambda: None)
    app.hwnd = 1
    app.calibration = Calibration("MapleStory", 1024, 768, 96, Rect(0, 0, 1024, 768), True, True)
    app.image = np.zeros((768, 1024, 3), dtype=np.uint8)
    app.window = app.windows.window
    app.region = app.window.client
    yield app
    app.controller.close()


@pytest.mark.parametrize("change", ["focus", "geometry", "dpi", "title", "visibility"])
def test_input_gate_checks_window_focus_geometry_dpi_title_and_occlusion(app, change):
    assert app._input_safe()
    values = {
        "focus": {"focused": False},
        "geometry": {"client": Rect(0, 0, 1200, 900)},
        "dpi": {"dpi": 144},
        "title": {"title": "Unrelated application"},
    }
    if change == "visibility":
        app.windows.visible = False
    else:
        app.windows.window = replace(app.windows.window, **values[change])
    assert not app._input_safe()


def test_calibration_releases_keys_and_blocks_probe_until_live_view(app):
    app.controller.enable()
    with app.controller.lock:
        app.controller.held["right"] = time.perf_counter() + 0.2
    frozen = app._command("freeze", {})
    assert frozen["width"] == 1024
    assert app.calibrating
    assert app.controller.backend.events == [("right", False)]
    with pytest.raises(ValueError, match="Return to live"):
        app._command("probe", {"action": "attack"})
    with pytest.raises(ValueError, match="live screenshot"):
        app._command("confirm_capture", {})
    app._command("resume_view", {})
    assert app._command("probe", {"action": "attack"})["mode"] == "probe_wait"
    assert app.controller.backend.events == [("right", False)]


def test_emergency_during_countdown_latches_and_never_sends_input(app):
    app.probed.update(REQUIRED_PROBES)
    app._command("arm", {})
    app.pending_at = 0
    app.controller.stop("Emergency stop hotkey")
    _, status = app._process(app.image, time.perf_counter())
    assert app.mode == "capture"
    assert status["state"] == "IDLE"
    assert app.controller.backend.events == []


def test_uncertain_detection_cancels_live_mode_without_key_down(app):
    app.controller.enable()
    app.agent.start()
    app.mode = "live"
    _, status = app._process(app.image, time.perf_counter())
    assert status["state"] == "IDLE"
    assert app.mode == "capture"
    assert "Uncertain player" in status["reason"]
    assert app.controller.backend.events == []


def test_live_processing_continues_while_submitted_key_is_held(app, monkeypatch):
    backend = HoldingBackend()
    app.controller.close()
    app.controller = app.controller.__class__(
        backend, app.config.input, app._input_safe, lambda: False, timing=app.config.timing
    )
    app.controller.enable()
    app.agent.start()
    app.mode = "live"
    monkeypatch.setattr(app.detector, "detect", lambda image, now: type("O", (), {
        "player": type("P", (), {"confidence": 1.0})(), "failures": [], "camera_shift": (0, 0),
        "camera_confidence": 1.0, "monsters": []
    })())
    monkeypatch.setattr("maplebot.runtime.annotate", lambda image, *args: image)
    monkeypatch.setattr("maplebot.runtime.asdict", lambda value: {})
    monkeypatch.setattr(app.agent, "step_input", lambda policy_input: type("D", (), {
        "state": "LIVE", "reason": "test", "target": None,
        "action": __import__("maplebot.decision", fromlist=["Action"]).Action("right", 0.25),
    })())
    app._process(app.image, time.perf_counter())
    deadline = time.perf_counter() + 1
    while not backend.down:
        assert time.perf_counter() < deadline
        time.sleep(0.002)
    app._process(app.image, time.perf_counter())
    assert app.mode == "live"
    assert backend.down


def test_arm_cannot_start_without_current_session_required_probes(app):
    with pytest.raises(ValueError, match="Confirm required probes"):
        app._command("arm", {})


def test_manual_region_and_unverified_capture_block_gameplay_input(app):
    app._command("manual", {"x": 0, "y": 0, "width": 1024, "height": 768})
    assert not app._input_safe()
    with pytest.raises(ValueError, match="verify the Game view"):
        app._command("arm", {})
    assert app.controller.backend.events == []


def test_canceled_queued_command_cannot_arm_input_later(app):
    canceled = Future()
    canceled.cancel()
    app.commands.put(("arm", {}, canceled))
    app._drain_commands()
    assert app.mode == "capture"
    assert not app.controller.enabled


def test_stop_request_releases_without_waiting_for_the_capture_queue(app):
    app.controller.enable()
    with app.controller.lock:
        app.controller.held["right"] = time.perf_counter() + 0.2
    assert app.request("pause", {}) == {"ok": True}
    assert app.commands.empty()
    assert not app.controller.enabled
    assert app.controller.backend.events == [("right", False)]


def test_stop_supersedes_a_queued_versioned_start(app):
    epoch = app.command_epoch
    future = Future()
    app.commands.put(("dry_run", {"_context": CommandContext(epoch, time.time())}, future))
    app.request("stop", {})
    app._drain_commands()
    with pytest.raises(ValueError, match="superseded"):
        future.result()
    assert app.mode == "capture"
    assert not app.controller.enabled


def test_stop_during_start_preparation_wins_over_the_start(app, monkeypatch):
    context = CommandContext(app.command_epoch, time.time())
    original_stop = app._stop

    def stop_again(code, message):
        result = original_stop(code, message)
        app.request("stop", {})
        return result

    monkeypatch.setattr(app, "_stop", stop_again)
    with pytest.raises(ValueError, match="superseded"):
        app._command("dry_run", {"_context": context})
    assert app.mode == "capture"
    assert not app.controller.enabled


def test_published_frames_are_identified_and_superseded_bytes_cannot_be_read(app):
    from maplebot.frame_encoder import FramePacket

    now = time.time()
    packet = FramePacket(1, "1", app.image, app.image, {"captured_at": now}, 0)
    app._encoded(packet, b"raw-1", b"annotated-1", 0)
    first = app.snapshot()
    assert first["schema_version"] == 1
    assert first["frame"]["width"] == 1024
    assert first["frame"]["captured_at"] == now
    assert app.frame(first["frame"]["id"]) == b"annotated-1"
    packet = replace(packet, sequence=2)
    app._encoded(packet, b"raw-2", b"annotated-2", 0)
    assert app.frame(first["frame"]["id"]) is None
    assert app.frame(app.snapshot()["frame"]["id"], raw=True) == b"raw-2"


def test_source_change_rejects_old_encoder_results_and_invalidates_readiness(app):
    from maplebot.frame_encoder import FramePacket

    packet = FramePacket(
        1, "1", app.image, app.image,
        {"captured_at": time.time(), "view_generation": app.view_generation}, 0,
    )
    app._encoded(packet, b"old", b"old", 0)
    assert app.snapshot()["frame"]["available"]
    app._command("reset_crop", {})
    app._encoded(packet, b"late-old", b"late-old", 0)
    assert not app.snapshot()["frame"]["available"]
    assert not app.snapshot()["readiness"]["preview"]["ready"]


def run_moving_capture(app, monkeypatch, failures, *, bursts=1):
    from types import SimpleNamespace

    from maplebot.capture import Capture

    image = app.image.copy()
    seen_alarms, waits = [], []
    stable_frames = 0

    class MovingCapture:
        attempts = 0

        def window(self, hwnd, calibration):
            seen_alarms.append(app.alarm.snapshot()["active"])
            self.attempts += 1
            if (self.attempts - 1) % (failures + 1) < failures:
                before = app.windows.window
                after = replace(before, client=before.client.translated(20, 10))
                positions = iter((before, after))
                capture = Capture.__new__(Capture)
                capture.windows = SimpleNamespace(get=lambda handle: next(positions))
                capture.grab = lambda region: image
                return capture.window(hwnd, calibration)
            return image, app.windows.window, app.region

        def close(self):
            pass

    def process(frame, now, policy_now):
        nonlocal stable_frames
        stable_frames += 1
        if stable_frames >= bursts:
            app.closed.set()
        return frame, {"stage_timing": {}, "state": "IDLE", "reason": "Stable frame"}

    monkeypatch.setattr("maplebot.runtime.Capture", lambda windows: MovingCapture())
    monkeypatch.setattr(app.closed, "wait", lambda seconds: waits.append(seconds) or False)
    monkeypatch.setattr(app, "_process", process)
    monkeypatch.setattr(app.encoder, "publish", lambda packet: None)
    app._run()
    return seen_alarms, waits


@pytest.mark.parametrize("mode", ["capture", "dry_run"])
def test_brief_window_motion_recovers_without_alarm_or_losing_saved_verification(
    app, monkeypatch, mode
):
    app.mode = mode
    app.probed.update(REQUIRED_PROBES)
    app.potter.enabled = True
    seen, waits = run_moving_capture(app, monkeypatch, failures=3)
    assert not any(seen)
    assert not app.alarm.snapshot()["active"]
    assert app.calibration.capture_verified
    assert app.calibration.controls_verified
    assert app.probed == REQUIRED_PROBES
    assert app.potter.enabled and not app.potter.live
    assert app.mode == mode
    assert len([seconds for seconds in waits if seconds >= 0.5]) >= 3


def test_window_motion_releases_live_input_without_automatically_resuming(app, monkeypatch):
    app.mode = "live"
    with app.controller.lock:
        app.controller.held["right"] = time.perf_counter() + 8
    run_moving_capture(app, monkeypatch, failures=1)
    assert app.controller.backend.events == [("right", False)]
    assert not app.controller.enabled
    assert app.mode == "capture"
    assert not app.alarm.snapshot()["active"]


def test_persistent_window_motion_alarms_only_after_five_failed_captures(app, monkeypatch):
    seen, waits = run_moving_capture(app, monkeypatch, failures=5)
    assert seen[:5] == [False] * 5
    assert seen[5] is True
    assert app.alarm.snapshot()["active"]
    assert "5" in app.stop_record.message
    assert app.calibration.capture_verified
    assert len([seconds for seconds in waits if seconds >= 0.5]) >= 4


def test_stable_capture_resets_the_window_motion_retry_budget(app, monkeypatch):
    seen, _ = run_moving_capture(app, monkeypatch, failures=3, bursts=2)
    assert len(seen) == 8
    assert not any(seen)


def test_transient_window_motion_keeps_source_identity_but_crop_change_invalidates_it(app):
    original = app.snapshot()["frame"]["source_id"]
    app._capture_moved(1)
    assert app.snapshot()["frame"]["source_id"] == original
    assert not app.snapshot()["frame"]["available"]
    app._command("reset_crop", {})
    assert app.snapshot()["frame"]["source_id"] != original


def test_backend_can_be_supplied_without_constructing_win32_input(monkeypatch, tmp_path):
    monkeypatch.setattr("maplebot.runtime.Windows", FakeWindows)

    def unavailable_native_backend():
        raise AssertionError("Default backend must not be constructed when an adapter is supplied")

    monkeypatch.setattr("maplebot.runtime.Win32Input", unavailable_native_backend)
    config = Config()
    config = replace(config, capture=replace(config.capture, data_dir=str(tmp_path)))
    backend = Backend()
    application = Application(config, input_backend=backend)
    try:
        assert application.controller.backend is backend
        assert application.controller.planner.config == config.timing
    finally:
        application.controller.close()


def test_capture_only_blocks_input_even_with_verified_capture_and_supplied_backend(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("maplebot.runtime.Windows", FakeWindows)

    def forbidden_native_backend():
        raise AssertionError("Capture-only must never construct an OS input backend")

    monkeypatch.setattr("maplebot.runtime.Win32Input", forbidden_native_backend)
    config = Config()
    config = replace(config, capture=replace(config.capture, data_dir=str(tmp_path)))
    backend = Backend()
    application = Application(config, input_backend=backend, capture_only=True)
    try:
        application.hwnd = 1
        application.calibration = Calibration(
            "MapleStory", 1024, 768, 96, Rect(0, 0, 1024, 768), True, True
        )
        assert not application._input_safe()
        assert application.snapshot()["capture_only"] is True
        for command in ("arm", "probe", "confirm_controls"):
            with pytest.raises(ValueError, match="Capture-only"):
                application._command(command, {"action": "attack"})
        with pytest.raises(RuntimeError):
            application.controller.enable()
        with pytest.raises(RuntimeError, match="Capture-only"):
            application.controller.backend.send("ctrl", True)
        assert application._command("dry_run", {})["mode"] == "dry_run"
        application._command("stop", {})
        application.mode = "live"
        _, status = application._process(np.zeros((100, 100, 3), dtype=np.uint8), 0.0)
        assert application.mode == "capture"
        assert status["capture_only"] is True
        assert backend.events == []
        assert application.snapshot()["capture_only"] is True
    finally:
        application.controller.close()


def test_potion_preview_is_independent_of_combat_and_global_stop_disables_it(app):
    from test_autopotter import hud

    app.image = hud()
    app.region = Rect(0, 0, 300, 100)
    app.windows.window = app.window = replace(app.window, client=app.region)
    app.calibration = Calibration("MapleStory", 300, 100, 96, app.region, True, False)
    frozen = app._command("freeze", {})
    app._command(
        "autopotter_calibrate",
        {
            "id": frozen["id"],
            "resource": "hp",
            "x": 10,
            "y": 30,
            "width": 104,
            "height": 16,
        },
    )
    with pytest.raises(ValueError, match="live screenshot"):
        app._command("autopotter_start", {})
    app._command("resume_view", {})
    assert app._command("autopotter_start", {})["enabled"]
    assert app.mode == "capture"
    app._process(hud(20), time.perf_counter())
    _, status = app._process(hud(20), time.perf_counter())
    assert status["autopotter"]["suggestion"] == "hp"
    assert not status["autopotter"]["input_sent"]
    assert app.controller.backend.events == []
    app.controller.stop("Emergency stop hotkey")
    app._process(hud(20), time.perf_counter())
    assert not app.potter.enabled
    app._command("autopotter_start", {})
    app._command("stop", {})
    assert not app.potter.enabled


def test_potion_preview_cannot_start_before_capture_verification(app):
    app.calibration.capture_verified = False
    with pytest.raises(ValueError, match="Verify capture"):
        app._command("autopotter_start", {})


def test_dry_run_auto_records_and_stop_flushes_clip(app):
    app.recorder.observe("00000000", b"png", {}, time.perf_counter())
    app._command("dry_run", {})
    path = app.recorder.path
    assert path is not None and "dry-run" in path.name
    app._command("stop", {})
    assert not app.recorder.active
    app.recorder.close()
    assert (path / "00000000.png").exists()
    assert "Operator stopped" in (path / "events.jsonl").read_text("utf-8")


def test_safe_stop_releases_before_one_clip_status_and_alarm(app, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        app.controller,
        "stop",
        lambda *args, **kwargs: calls.append("release"),
    )
    monkeypatch.setattr(
        app.encoder,
        "flush_through",
        lambda *args, **kwargs: calls.append("flush") or {"complete": True},
    )
    monkeypatch.setattr(
        app.recorder,
        "trigger",
        lambda *args, **kwargs: calls.append("clip") or tmp_path / "clip",
    )
    monkeypatch.setattr(
        app.alarm,
        "start",
        lambda incident_id: calls.append(("alarm", incident_id)),
    )

    first = app.safe_stop("CAPTURE_WORKER_FAILURE", "Injected capture failure")
    second = app.safe_stop("CAPTURE_WORKER_FAILURE", "Injected capture failure")

    assert first == second
    assert calls[:3] == ["release", "flush", "clip"]
    assert calls.count("release") == 2
    assert len([item for item in calls if isinstance(item, tuple)]) == 1
    assert app.snapshot()["stop"]["clip_path"] == str(tmp_path / "clip")
    assert len([item for item in app.history if item.get("id") == first.id]) == 1


def test_safe_stop_promotes_a_racing_silent_stop_without_a_second_incident(app, monkeypatch):
    starts = []
    monkeypatch.setattr(app.recorder, "trigger", lambda *args, **kwargs: app.data / "clip")
    monkeypatch.setattr(app.alarm, "start", starts.append)

    first = app.safe_stop("OPERATOR_STOP", "Operator stopped")
    second = app.safe_stop("CAPTURE_WORKER_EXIT", "Worker exited")

    assert first.id == second.id
    assert second.severity is StopSeverity.ALARM
    assert starts == [first.id]
    assert len([item for item in app.history if item.get("id") == first.id]) == 1


def test_new_encoded_frame_cannot_hide_an_active_alarm_stop(app):
    from maplebot.frame_encoder import FramePacket

    incident = app.safe_stop("CAPTURE_WORKER_EXIT", "Worker exited")
    packet = FramePacket(0, "00000000", app.image, app.image, {"state": "IDLE"}, 0.0)
    app._encoded(packet, b"raw", b"annotated", 1.0)

    status = app.snapshot()
    assert status["alarm"]["active"]
    assert status["stop"]["id"] == incident.id
    assert status["stop"]["code"] == "CAPTURE_WORKER_EXIT"
    app.acknowledge_stop()


def test_f8_watchdog_acknowledges_alarm_without_a_capture_worker(app, monkeypatch):
    app.safe_stop("CAPTURE_WORKER_EXIT", "Worker exited")
    assert app.worker is None
    monkeypatch.setattr(app.windows, "pressed", lambda key: True)

    deadline = time.monotonic() + 1
    while app.alarm.snapshot()["active"] and time.monotonic() < deadline:
        time.sleep(0.005)

    assert not app.alarm.snapshot()["active"]
    assert app.snapshot()["stop"]["acknowledged"]
    assert not app.controller.enabled


def test_acknowledge_silences_alarm_even_without_a_stop_banner(app):
    app.alarm.start("orphaned-audio")

    assert app.request("acknowledge", {"incident_id": "orphaned-audio"})["acknowledged"]
    assert not app.alarm.snapshot()["active"]


def test_stop_reason_registry_classifies_every_declared_safety_path():
    alarm = {
        "CAPTURE_WORKER_EXIT",
        "CAPTURE_WORKER_FAILURE",
        "INPUT_WATCHDOG_FAILURE",
        "INPUT_BACKEND_FAILURE",
        "FOCUS_LOSS",
        "CALIBRATION_INVALID",
        "PLAYER_UNCERTAIN",
        "DEBUGGER_TIMEOUT",
    }
    silent = {
        "EMERGENCY_STOP",
        "OPERATOR_STOP",
        "CAPTURE_ONLY_GUARD",
        "PROBE_COMPLETE",
        "CALIBRATION",
        "POLICY_STOP",
        "DRY_RUN_STOP",
    }
    alarm_codes = {
        code for code, reason in STOP_REASONS.items() if reason.severity is StopSeverity.ALARM
    }
    silent_codes = {
        code for code, reason in STOP_REASONS.items() if reason.severity is StopSeverity.SILENT
    }
    assert alarm_codes == alarm
    assert silent_codes == silent


def test_dead_worker_can_acknowledge_and_restart_directly(app, monkeypatch):
    active = {"value": False}
    monkeypatch.setattr(
        app.alarm, "start", lambda incident_id: active.update(value=True, incident_id=incident_id)
    )
    monkeypatch.setattr(app.alarm, "acknowledge", lambda: active.update(value=False))
    monkeypatch.setattr(app.alarm, "snapshot", lambda: {
        "active": active["value"], "incident_id": active.get("incident_id"),
    })
    monkeypatch.setattr(app, "_run", lambda: app.closed.wait(1))

    app.probed.add("jump")
    app.safe_stop("CAPTURE_WORKER_EXIT", "Injected fatal worker exit")
    assert app.request("acknowledge", {"incident_id": app.stop_record.id})["acknowledged"]
    restarted = app.request("restart_capture", {})

    assert restarted["restarted"] is True
    assert app.worker is not None and app.worker.is_alive()
    assert app.probed == set()
    assert app.calibration is not None and not app.calibration.capture_verified
    assert not app.controller.enabled
    assert app.request("restart_capture", {})["restarted"] is False


def test_capture_stage_timing_excludes_encoder_png_work(app, monkeypatch):
    monkeypatch.setattr(app.detector, "detect", lambda image, now: type("O", (), {
        "player": None, "monsters": [], "failures": [], "camera_shift": (0, 0),
        "camera_confidence": 1.0,
    })())
    monkeypatch.setattr("maplebot.runtime.annotate", lambda image, *args: image.copy())
    _, status = app._process(app.image, 10.0, 0.0)
    assert set(status["stage_timing"]) == {"perception_ms", "policy_ms", "annotation_ms"}
    assert "png_encode_ms" not in status["stage_timing"]


def test_teaching_name_tag_records_other_copies_as_decoys(app):
    tag = np.full((13, 60, 3), 40, dtype=np.uint8)
    for x in range(3, 56, 5):
        tag[2 : 2 + (x % 7) + 3, x : x + 2] = 255
        tag[6, x : x + 4] = 255
    frame = np.random.default_rng(5).integers(60, 200, (768, 1024, 3), dtype=np.uint8)
    frame[300:313, 400:460] = tag
    frame[740:753, 190:250] = tag
    app.frozen["f"] = (frame, app.window, app.region)
    result = app._command(
        "template", {"id": "f", "kind": "nametag", "x": 400, "y": 300, "width": 60, "height": 13}
    )
    meta = json.loads(Path(result["path"]).with_suffix(".json").read_text("utf-8"))
    # Positions are of the glyph crop: 2 px right, 1 px down from the drawn tag.
    assert meta["decoys"] == [[192, 741]]
    assert meta["frame"] == [1024, 768]
    assert app.detector.nametags[0].decoys == ((192, 741),)

@pytest.fixture
def potion_app(app):
    from test_autopotter import hud

    app.image = hud()
    app.region = Rect(0, 0, 300, 100)
    app.windows.window = app.window = replace(app.window, client=app.region)
    app.calibration = Calibration("MapleStory", 300, 100, 96, app.region, True, False)
    for resource, x in [("hp", 10), ("mp", 150)]:
        app.potter.calibrate(resource, hud(), Rect(x, 30, 104, 16))
    app.probed.update({"hp_potion", "mp_potion"})
    return app


def start_live_potions(app):
    from test_autopotter import hud

    app._command("autopotter_live", {})
    assert app.mode == "potion_wait"
    assert not app.controller.enabled
    assert app.controller.backend.events == []
    app.pending_at = 0
    app._process(hud(), time.perf_counter())
    assert app.mode == "potion_live"
    assert app.potter.live


def finish_live_potion(app, image):
    deadline = time.perf_counter() + 2
    while app.live_potion_ticket is not None:
        assert time.perf_counter() < deadline
        time.sleep(0.002)
        app._process(image, time.perf_counter())


def test_live_potions_prioritize_hp_apply_cooldown_then_send_mp(potion_app):
    from test_autopotter import hud

    app = potion_app
    start_live_potions(app)
    low = hud(20, 20)
    app._process(low, time.perf_counter())
    assert app.live_potion_ticket is None
    app._process(low, time.perf_counter())
    assert app.live_potion_ticket is not None
    finish_live_potion(app, low)
    assert app.controller.backend.events == [("insert", True), ("insert", False)]
    assert app.potter.snapshot()["input_sent"]
    assert not app.controller.enabled
    app._process(low, time.perf_counter())
    assert app.live_potion_ticket is None
    app.potter.last_suggestion = time.perf_counter() - app.potter.settings["cooldown"] - 1
    finish_image = hud(100, 20)
    app._process(finish_image, time.perf_counter())
    finish_live_potion(app, finish_image)
    assert app.controller.backend.events[-2:] == [("delete", True), ("delete", False)]
    assert app.mode == "potion_live"
    assert str(app.agent.state) == "IDLE"


@pytest.mark.parametrize(
    "blocker", ["capture_only", "unverified", "unprobed", "disabled", "unreadable"]
)
def test_live_potions_reject_missing_prerequisites(potion_app, blocker):
    app = potion_app
    if blocker == "capture_only":
        app.capture_only = True
    elif blocker == "unverified":
        app.calibration.capture_verified = False
    elif blocker == "unprobed":
        app.probed.clear()
    elif blocker == "disabled":
        app.potter.configure(hp_threshold=0, mp_threshold=0, cooldown=1.5)
    else:
        app.image[:] = 0
    with pytest.raises(ValueError):
        app._command("autopotter_live", {})
    assert app.controller.backend.events == []
    assert not app.potter.live


@pytest.mark.parametrize(
    "blocker", ["focus", "visibility", "verification", "stale", "death", "f8"]
)
def test_live_potions_stop_without_sending_on_unsafe_frames(potion_app, monkeypatch, blocker):
    from test_autopotter import hud

    app = potion_app
    start_live_potions(app)
    image = hud(20, 20)
    now = time.perf_counter()
    if blocker == "focus":
        app.windows.window = replace(app.window, focused=False)
    elif blocker == "visibility":
        app.windows.visible = False
    elif blocker == "verification":
        app.calibration.capture_verified = False
    elif blocker == "stale":
        now -= 1
    elif blocker == "death":
        image = hud(0, 20)
    else:
        monkeypatch.setattr(app.windows, "pressed", lambda key: True)
    app._process(image, now)
    assert app.mode == "capture"
    assert not app.potter.enabled
    assert app.live_potion_ticket is None
    assert app.controller.backend.events == []


def test_live_potions_switch_to_preview_and_disabled_threshold_never_sends(potion_app):
    from test_autopotter import hud

    app = potion_app
    app.potter.configure(hp_threshold=0, mp_threshold=25, cooldown=1.5)
    app.probed = {"mp_potion"}
    start_live_potions(app)
    app._process(hud(20, 100), time.perf_counter())
    app._process(hud(20, 100), time.perf_counter())
    assert app.controller.backend.events == []
    app._command("autopotter_start", {})
    app._process(hud(20, 20), time.perf_counter())
    _, status = app._process(hud(20, 20), time.perf_counter())
    assert status["autopotter"]["suggestion"] == "mp"
    assert status["autopotter"]["preview_only"]
    assert app.controller.backend.events == []


def test_stop_cancels_a_queued_live_potion_and_settings_stop_live_mode(potion_app):
    from test_autopotter import hud

    app = potion_app
    start_live_potions(app)
    app.controller.planner.config = replace(
        app.controller.planner.config, reaction_min_seconds=0.4, reaction_max_seconds=0.4
    )
    app._process(hud(20, 20), time.perf_counter())
    app._process(hud(20, 20), time.perf_counter())
    assert app.live_potion_ticket is not None
    app._command("autopotter_stop", {})
    time.sleep(0.05)
    assert app.controller.backend.events == []
    assert app.live_potion_ticket is None
    assert not app.potter.enabled
    start_live_potions(app)
    app._command("autopotter_settings", {"hp_threshold": 40, "mp_threshold": 20, "cooldown": 2})
    assert app.mode == "capture"
    assert not app.potter.enabled


def test_live_potion_countdown_sends_nothing_and_checks_focus_at_deadline(potion_app):
    from test_autopotter import hud

    app = potion_app
    app.windows.window = replace(app.window, focused=False)
    app._command("autopotter_live", {})
    app._process(hud(20, 20), time.perf_counter())
    assert app.mode == "potion_wait"
    assert app.controller.backend.events == []
    app.pending_at = 0
    app._process(hud(20, 20), time.perf_counter())
    assert app.mode == "capture"
    assert not app.potter.enabled
    assert app.controller.backend.events == []


def test_live_potion_backend_failure_stops_without_retry(potion_app, monkeypatch):
    from test_autopotter import hud

    app = potion_app
    start_live_potions(app)
    attempts = []

    def fail(key, down):
        attempts.append((key, down))
        if down:
            raise OSError("Input denied")

    monkeypatch.setattr(app.controller.backend, "send", fail)
    app._process(hud(20, 20), time.perf_counter())
    app._process(hud(20, 20), time.perf_counter())
    deadline = time.perf_counter() + 2
    while app.mode != "capture":
        assert time.perf_counter() < deadline
        time.sleep(0.002)
    app._process(hud(20, 20), time.perf_counter())
    assert [event for event in attempts if event[1]] == [("insert", True)]
    assert not app.potter.enabled
    assert not app.controller.enabled
    assert not app.controller.held


def test_confirmed_probes_restore_on_reattach_but_input_stays_unverified_and_disabled(app):
    from maplebot.runtime import ProbeState

    app.active_probe = ProbeState(1, app.controller.generation, "left", "awaiting_confirmation", "")
    assert app.confirm_probe({"id": 1, "generation": app.controller.generation})["confirmed"]
    app.calibration.save(app.data / "calibration.json")
    app._command("attach", {"hwnd": 1})
    assert app.probed == {"left"}
    assert app.snapshot()["probes"]["left"]["confirmed"]
    assert not app.calibration.capture_verified
    assert app.mode == "capture"
    assert not app.controller.enabled
    assert not app.potter.enabled
    assert app.controller.backend.events == []


def test_restarting_a_saved_probe_revokes_it_until_new_success(app):
    app.probed = {"left", "right"}
    app._save_probes()
    app.request_probe({"action": "left"})
    assert app.probed == {"right"}
    app._command("stop", {})
    app._restore_probes()
    assert app.probed == {"right"}


def test_transient_stops_preserve_confirmed_controls(app):
    app.probed = {"left", "right"}
    app._save_probes()
    app.safe_stop("FOCUS_LOSS", "Window lost focus")
    assert app.probed == {"left", "right"}
    assert not app.controller.enabled
    assert not app.potter.enabled


def test_hud_calibration_changes_only_invalidate_matching_potion(potion_app):
    app = potion_app
    app.probed.update({"left", "jump"})
    app._save_probes()
    hp = app.potter.bars["hp"]
    app.potter.bars["hp"] = replace(hp, box=Rect(11, 30, 104, 16))
    app._restore_probes()
    assert app.probed == {"left", "jump", "mp_potion"}
    app.config = replace(app.config, input=replace(app.config.input, jump="alt"))
    app._restore_probes()
    assert app.probed == {"left", "mp_potion"}


def test_fresh_application_restores_probes_without_arming(app, monkeypatch):
    app.probed = {"left", "jump"}
    app._save_probes()
    app.calibration.save(app.data / "calibration.json")
    restarted = Application(app.config, input_backend=Backend())
    monkeypatch.setattr(restarted.alarm.backend, "play", lambda path: None)
    monkeypatch.setattr(restarted.alarm.backend, "stop", lambda: None)
    monkeypatch.setattr(restarted.alarm.backend, "beep", lambda: None)
    try:
        assert restarted.probed == set()
        restarted._command("attach", {"hwnd": 1})
        assert restarted.probed == {"left", "jump"}
        assert not restarted.calibration.capture_verified
        assert not restarted.controller.enabled
        assert not restarted.potter.enabled
        assert restarted.mode == "capture"
        assert restarted.controller.backend.events == []
    finally:
        restarted.close()


def test_portal_loading_pauses_live_potions_then_requires_two_fresh_readings(potion_app):
    from test_autopotter import hud

    app = potion_app
    start_live_potions(app)
    loading = np.zeros_like(app.image)
    _, status = app._process(loading, time.perf_counter())
    assert app.mode == "potion_live"
    assert app.potter.enabled
    assert app.controller.backend.events == []
    assert not app.alarm.snapshot()["active"]
    assert "Waiting for HUD" in status["autopotter"]["reason"]
    app._process(hud(20, 100), time.perf_counter())
    assert app.controller.backend.events == []
    assert app.live_potion_ticket is None
    app._process(hud(20, 100), time.perf_counter())
    assert app.live_potion_ticket is not None
    finish_live_potion(app, hud(100, 100))
    assert app.controller.backend.events == [("insert", True), ("insert", False)]
    assert app.potion_hud_missing_since is None


def test_live_potions_alarm_after_hud_grace_expires(potion_app):
    app = potion_app
    start_live_potions(app)
    loading = np.zeros_like(app.image)
    app._process(loading, time.perf_counter())
    app.potion_hud_missing_since = time.perf_counter() - 5.1
    app._process(loading, time.perf_counter())
    assert app.mode == "capture"
    assert not app.potter.enabled
    assert app.alarm.snapshot()["active"]
    assert "5 seconds" in app.stop_record.message
    assert app.controller.backend.events == []


def test_hud_loading_cancels_queued_potion_without_alarm(potion_app):
    from test_autopotter import hud

    app = potion_app
    start_live_potions(app)
    app.controller.planner.config = replace(
        app.controller.planner.config, reaction_min_seconds=0.4, reaction_max_seconds=0.4
    )
    app._process(hud(20, 20), time.perf_counter())
    app._process(hud(20, 20), time.perf_counter())
    assert app.live_potion_ticket is not None
    app._process(np.zeros_like(app.image), time.perf_counter())
    time.sleep(0.05)
    app._process(np.zeros_like(app.image), time.perf_counter())
    assert app.mode == "potion_live"
    assert app.live_potion_ticket is None
    assert not app.controller.enabled
    assert app.controller.backend.events == []
    assert not app.alarm.snapshot()["active"]


@pytest.mark.parametrize("capture_only", [False, True])
def test_start_reconnects_saved_window_without_enabling_input(app, monkeypatch, capture_only):
    app.calibration.save(app.data / "calibration.json")
    app.probed = {"left", "jump"}
    app._save_probes()
    app.capture_only = capture_only
    monkeypatch.setattr(app.windows, "list", lambda: [app.windows.window], raising=False)
    monkeypatch.setattr(app, "start_capture_worker", lambda: False)
    app.start()
    assert app.hwnd == 1
    assert app.probed == {"left", "jump"}
    assert not app.calibration.capture_verified
    assert app.mode == "capture"
    assert not app.controller.enabled
    assert not app.potter.enabled
    assert app.controller.backend.events == []


@pytest.mark.parametrize("problem", ["missing", "duplicate", "resized", "wrong_title", "corrupt"])
def test_auto_reconnect_never_guesses_an_unmatched_or_ambiguous_window(app, monkeypatch, problem):
    app.calibration.save(app.data / "calibration.json")
    windows = [app.windows.window]
    if problem == "missing":
        windows = []
    elif problem == "duplicate":
        windows.append(replace(app.window, hwnd=2))
    elif problem == "resized":
        windows = [replace(app.window, client=Rect(0, 0, 1280, 720))]
    elif problem == "wrong_title":
        windows = [replace(app.window, title="Another game")]
    else:
        (app.data / "calibration.json").write_text("broken")
    monkeypatch.setattr(app.windows, "list", lambda: windows, raising=False)
    app.hwnd = None
    app.calibration = None
    assert not app.connect_saved_window()
    assert app.hwnd is None
    assert app.calibration is None
    assert app.controller.backend.events == []


@pytest.mark.parametrize("evidence", ["player", "hp", "mp"])
def test_recognition_verifies_capture_without_enabling_input(potion_app, monkeypatch, evidence):
    from test_autopotter import hud

    from maplebot.perception import Detection, Observation

    app = potion_app
    app.probed = {"left", "hp_potion", "mp_potion"}
    app._save_probes()
    app.calibration.capture_verified = False
    player = Detection("player", Rect(10, 20, 20, 30), 1.0) if evidence == "player" else None
    monkeypatch.setattr(app.detector, "detect", lambda image, now: Observation(player, []))
    image = np.zeros_like(app.image) if player else hud(75, 75)
    if evidence == "hp":
        app.potter.bars.pop("mp")
    elif evidence == "mp":
        app.potter.bars.pop("hp")
    app._process(image, time.perf_counter())
    assert app.calibration.capture_verified
    assert "left" in app.probed
    assert app.mode == "capture"
    assert not app.controller.enabled
    assert not app.potter.enabled
    assert app.controller.backend.events == []


@pytest.mark.parametrize(
    "problem", ["missing", "weak", "tracked", "stale", "covered", "title", "size", "frozen"]
)
def test_recognition_cannot_verify_uncertain_or_wrong_game_view(potion_app, monkeypatch, problem):
    from maplebot.perception import Detection, Observation

    app = potion_app
    app.calibration.capture_verified = False
    player = Detection("player", Rect(10, 20, 20, 30), 1.0)
    image = np.zeros_like(app.image)
    now = time.perf_counter()
    if problem == "missing":
        player = None
    elif problem == "weak":
        player = replace(player, confidence=0.6)
    elif problem == "tracked":
        player = replace(player, tracked=True)
    elif problem == "stale":
        now -= 1
    elif problem == "covered":
        app.windows.visible = False
    elif problem == "title":
        app.windows.window = replace(app.window, title="Other game")
    elif problem == "size":
        image = image[:, :-1]
    else:
        app.calibrating = True
    monkeypatch.setattr(app.detector, "detect", lambda image, now: Observation(player, []))
    app._process(image, now)
    assert not app.calibration.capture_verified
    assert not app.controller.enabled
    assert app.controller.backend.events == []


@pytest.mark.parametrize("requested", ["old", None, "unknown"])
def test_dashboard_acknowledgement_cannot_silence_a_different_incident(app, requested):
    first = app.safe_stop("FOCUS_LOSS", "First incident")
    app.acknowledge_stop()
    app._clear_stop_banner()
    current = app.safe_stop("FOCUS_LOSS", "Current incident")
    payload = {} if requested is None else {
        "incident_id": first.id if requested == "old" else requested,
    }
    result = app.request("acknowledge", payload)
    assert not result["acknowledged"]
    assert app.stop_record.id == current.id
    assert not app.stop_record.acknowledged
    assert app.alarm.snapshot()["active"]
    assert app.controller.backend.events == []
    assert app.request("acknowledge", {"incident_id": current.id})["acknowledged"]
    assert not app.alarm.snapshot()["active"]


def _arm_state(app):
    return (
        app.stop_record, app.alarm.snapshot(), app.mode, app.pending_at,
        app.stop_requested.is_set(), app.active_probe, frozenset(app.probed),
        app.controller.enabled, app.controller.stopped.is_set(),
    )


def test_arm_refuses_active_alarm_without_mutating_runtime_state(app):
    app.probed.update(REQUIRED_PROBES)
    app.safe_stop("FOCUS_LOSS", "Alarm incident")
    before = _arm_state(app)
    with pytest.raises(ValueError, match="Acknowledge the active alarm"):
        app._command("arm", {})
    assert _arm_state(app) == before
    assert app.controller.backend.events == []


def test_arm_rechecks_alarm_before_committing_countdown(app, monkeypatch):
    app.probed.update(REQUIRED_PROBES)
    real_get = app.windows.get
    incident = []

    def get(hwnd):
        if not incident:
            incident.append(app.safe_stop("FOCUS_LOSS", "Alarm during preparation"))
        return real_get(hwnd)

    monkeypatch.setattr(app.windows, "get", get)
    with pytest.raises(ValueError, match="Acknowledge the active alarm"):
        app._command("arm", {})
    assert app.mode != "pending_arm"
    assert app.alarm.snapshot()["active"]
    assert app.stop_record.id == incident[0].id and not app.stop_record.acknowledged
    assert app.controller.backend.events == []


def test_acknowledged_alarm_clears_banner_before_fresh_arm_countdown(app):
    app.probed.update(REQUIRED_PROBES)
    incident = app.safe_stop("FOCUS_LOSS", "Alarm incident")
    with pytest.raises(ValueError):
        app._command("arm", {})
    assert app.request("acknowledge", {"incident_id": incident.id})["acknowledged"]
    assert app.mode != "pending_arm" and not app.controller.enabled
    assert app.controller.backend.events == []
    started = time.perf_counter()
    result = app._command("arm", {})
    assert result["mode"] == "pending_arm"
    assert 2 < app.pending_at - started <= 3.5
    assert app.stop_record is None and "stop" not in app.status
    assert REQUIRED_PROBES <= app.probed
    assert not app.controller.enabled and app.controller.backend.events == []
