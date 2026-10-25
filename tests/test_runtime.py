import json
import time
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from maplebot.capture import Calibration
from maplebot.config import Config
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


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("maplebot.runtime.Windows", FakeWindows)
    monkeypatch.setattr("maplebot.runtime.Win32Input", Backend)
    config = Config()
    config = replace(config, capture=replace(config.capture, data_dir=str(tmp_path)))
    app = Application(config)
    monkeypatch.setattr(app.alarm.backend, "play_loop", lambda path: None)
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

    assert app.request("acknowledge", {})["acknowledged"]
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
    monkeypatch.setattr(app.alarm, "start", lambda incident_id: active.update(value=True))
    monkeypatch.setattr(app.alarm, "acknowledge", lambda: active.update(value=False))
    monkeypatch.setattr(app.alarm, "snapshot", lambda: {"active": active["value"]})
    monkeypatch.setattr(app, "_run", lambda: app.closed.wait(1))

    app.probed.add("jump")
    app.safe_stop("CAPTURE_WORKER_EXIT", "Injected fatal worker exit")
    assert app.request("acknowledge", {})["acknowledged"]
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
    "blocker", ["focus", "visibility", "verification", "stale", "hud", "death", "f8"]
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
    elif blocker == "hud":
        image[:] = 0
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
    monkeypatch.setattr(restarted.alarm.backend, "play_loop", lambda path: None)
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
