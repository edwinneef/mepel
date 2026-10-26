import time
from dataclasses import replace

import numpy as np
import pytest

from maplebot.capture import Calibration
from maplebot.config import Config
from maplebot.geometry import Rect
from maplebot.runtime import REQUIRED_PROBES, Application, ProbeState
from maplebot.windows import Window


class FakeWindows:
    def __init__(self):
        self.window = Window(1, "MapleStory", Rect(0, 0, 300, 100), True, 96)

    def get(self, hwnd):
        return self.window

    def unobscured(self, hwnd, region):
        return True

    def pressed(self, key):
        return False

    def outranks_us(self, hwnd):
        return getattr(self, "elevated", False)


class Backend:
    def __init__(self):
        self.events = []

    def send(self, key, down):
        self.events.append((key, down))


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("maplebot.runtime.Windows", FakeWindows)
    config = replace(Config(), capture=replace(Config().capture, data_dir=str(tmp_path)))
    app = Application(config, input_backend=Backend())
    app.hwnd = 1
    app.calibration = Calibration("MapleStory", 300, 100, 96, Rect(0, 0, 300, 100), True, False)
    app.window = app.windows.window
    app.region = app.window.client
    app.image = np.zeros((100, 300, 3), dtype=np.uint8)
    yield app
    app.controller.close()


def test_up_probe_is_guarded_generation_bound_and_manual(app):
    started = app.request_probe({"action": "up"})

    assert started["instruction"] == "stand away from portals and ropes"
    assert app.active_probe is not None and app.active_probe.phase == "countdown"
    assert app.snapshot()["probes"]["up"]["confirmed"] is False
    with pytest.raises(ValueError, match="already active"):
        app.request_probe({"action": "down"})

    active = replace(app.active_probe, phase="awaiting_confirmation")
    app.active_probe = active
    stale = app.confirm_probe({"id": active.id + 1, "generation": active.generation})
    assert stale["confirmed"] is False
    assert app.confirm_probe({"id": active.id, "generation": active.generation}) == {
        "confirmed": True,
        "action": "up",
    }
    assert "up" in app.probed
    repeated = app.confirm_probe({"id": active.id, "generation": active.generation})
    assert repeated["confirmed"] is False
    assert app.controller.backend.events == []


def test_stop_cancels_probe_and_arm_requires_only_five_manual_permissions(app):
    started = app.request_probe({"action": "left"})
    app.safe_stop("OPERATOR_STOP", "Operator stopped")

    assert app.confirm_probe(started)["confirmed"] is False
    assert app.snapshot()["probes"]["left"]["status"] == "cancelled"
    app.probed.update(REQUIRED_PROBES)
    assert app.snapshot()["probes"]["hp_potion"]["required"] is False
    assert app.snapshot()["required_probes"] == sorted(REQUIRED_PROBES)
    app._command("arm", {})
    assert app.mode == "pending_arm"


@pytest.mark.parametrize(
    ("blocker", "message"),
    [
        ("focus", "Click the actual game window"),
        ("visibility", "covered by another window"),
        ("verification", "Confirm capture"),
    ],
)
def test_probe_reports_the_failed_guard_without_a_capture_crash(app, monkeypatch, blocker, message):
    from maplebot.perception import Detection, Observation

    app.request_probe({"action": "left"})
    app.pending_at = 0
    observation = Observation(Detection("player", Rect(10, 20, 20, 30), 1.0), [])
    monkeypatch.setattr(app.detector, "detect", lambda image, now: observation)
    if blocker == "focus":
        app.windows.window = replace(app.windows.window, focused=False)
    elif blocker == "visibility":
        monkeypatch.setattr(app.windows, "unobscured", lambda *args: False)
    else:
        app.calibration.capture_verified = False

    app._process(app.image, time.perf_counter())

    assert app.probe_results["left"]["status"] == "cancelled"
    assert message in app.probe_results["left"]["reason"]
    assert app.stop_record.code == "PROBE_COMPLETE"
    assert not app.alarm.snapshot()["active"]
    assert app.controller.backend.events == []


def test_probe_cannot_start_behind_an_unacknowledged_alarm(app, monkeypatch):
    monkeypatch.setattr(app.alarm, "snapshot", lambda: {"active": True})

    with pytest.raises(ValueError, match="Acknowledge"):
        app.request_probe({"action": "left"})

    assert app.active_probe is None
    assert app.controller.backend.events == []


def test_completed_probe_can_be_confirmed_after_returning_to_dashboard(app, monkeypatch):
    from maplebot.perception import Detection, Observation

    observation = Observation(Detection("player", Rect(10, 20, 20, 30), 1.0), [])
    monkeypatch.setattr(app.detector, "detect", lambda image, now: observation)
    app.request_probe({"action": "left"})
    app.pending_at = 0
    app._process(app.image, time.perf_counter())
    deadline = time.perf_counter() + 2
    while app.controller.enabled:
        assert time.perf_counter() < deadline
        time.sleep(0.002)
    app.windows.window = replace(app.windows.window, focused=False)
    app._process(app.image, time.perf_counter())

    active = app.active_probe
    assert active is not None and active.phase == "awaiting_confirmation"
    assert app.controller.backend.events == [("left", True), ("left", False)]
    assert not app.alarm.snapshot()["active"]
    assert app.confirm_probe({"id": active.id, "generation": active.generation})["confirmed"]


def test_potion_probe_refuses_full_bar_then_confirms_only_fresh_matching_gain(app, tmp_path):
    from test_autopotter import hud

    for resource, x in (("hp", 10), ("mp", 150)):
        app.potter.calibrate(resource, hud(), Rect(x, 30, 104, 16))
    app.image = hud(100, 40)
    with pytest.raises(ValueError, match="HP is full"):
        app.request_probe({"action": "hp_potion"})
    assert app.controller.backend.events == []

    app.image = hud(40, 40)
    started = app.request_probe({"action": "hp_potion"})
    active = app.active_probe
    assert active is not None and active.baseline_percent == pytest.approx(40, abs=2)
    app.sequence = 5
    app.active_probe = replace(
        active,
        phase="awaiting_effect",
        pressed_sequence=5,
        pressed_at=time.perf_counter() - 0.1,
        deadline=time.perf_counter() + 1,
    )
    app._advance_potion_probe(hud(40, 70), time.perf_counter())
    assert app.active_probe is not None
    app.sequence = 6
    app._advance_potion_probe(hud(42, 70), time.perf_counter())
    assert "hp_potion" in app.probed
    assert "mp_potion" not in app.probed
    assert started["id"] > 0


def test_potion_timeout_does_not_retry_or_grant_permission(app):
    active = ProbeState(
        1,
        app.controller.generation,
        "mp_potion",
        "awaiting_effect",
        "",
        resource="mp",
        baseline_percent=40,
        pressed_sequence=1,
        pressed_at=0,
        deadline=0.1,
    )
    app.active_probe = active
    app._advance_potion_probe(app.image, 0.1)

    assert "mp_potion" not in app.probed
    assert app.snapshot()["probes"]["mp_potion"]["status"] == "failed"
    assert app.controller.backend.events == []
