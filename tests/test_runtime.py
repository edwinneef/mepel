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
from maplebot.runtime import Application
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
    monkeypatch.setattr(app.agent, "step", lambda observation, now: type("D", (), {
        "state": "LIVE", "reason": "test", "target": None, "action": __import__("maplebot.decision", fromlist=["Action"]).Action("right", 0.25)
    })())
    app._process(app.image, time.perf_counter())
    deadline = time.perf_counter() + 1
    while not backend.down:
        assert time.perf_counter() < deadline
        time.sleep(0.002)
    app._process(app.image, time.perf_counter())
    assert app.mode == "live"
    assert backend.down


def test_controls_cannot_be_confirmed_without_session_probes(app):
    with pytest.raises(ValueError, match="all four"):
        app._command("confirm_controls", {})


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
