import time
from dataclasses import replace

import pytest
from test_runtime import app as _app

from maplebot.decision import Action, Decision, State
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation
from maplebot.reacquisition import RECOVERY_SECONDS, Reacquisition

app = _app
ME, OTHER = "nametag:me", "nametag:other"


def test_pause_then_resume_on_two_spaced_fresh_frames_of_the_same_player():
    r = Reacquisition()
    assert r.step(None, 0).state == "pass"  # nothing confirmed: the policy decides as before
    assert r.step(ME, 0).state == "ok"
    assert r.step(None, .1).state == "pause"
    assert r.step("sprite", .2).state == "wait"  # a sprite match is not the confirmed tag
    assert r.step(ME, .3).state == "wait"
    assert r.step(ME, .4).state == "wait"  # spacing below 0.15 s
    assert r.step(ME, .5).state == "resume" and r.recovering
    r.resumed()
    assert not r.recovering and r.step(ME, .6).state == "ok"


@pytest.mark.parametrize(("identity", "reason"), [
    (None, "timed out"), (OTHER, "Different player")])
def test_recovery_stops_on_timeout_or_another_name_tag(identity, reason):
    r = Reacquisition()
    r.step(ME, 0)
    r.step(None, 1)
    now = 1 + (RECOVERY_SECONDS if identity is None else .5)
    step = r.step(identity, now)
    assert step.state == "stop" and reason in step.reason


def test_identity_change_without_a_gap_stops():
    r = Reacquisition()
    r.step(ME, 0)
    assert r.step(OTHER, .1).state == "stop"


def player(template=ME, tracked=False, confidence=1.0):
    return Detection("player", Rect(100, 100, 44, 64), confidence, template, tracked)


def drive(app, monkeypatch):
    """Live combat whose policy always wants to step right; returns its call count."""
    calls = []
    frame = {"player": player()}
    monkeypatch.setattr(app.detector, "detect", lambda image, now, **_: Observation(
        frame["player"], [], [], (0, 0), 1.0))

    def step(policy_input):
        calls.append(policy_input.now)
        return Decision(State.APPROACH, Action("right", 0.05), "test", None)

    monkeypatch.setattr(app.agent, "step_input", step)
    app.controller.enable()
    app.agent.start()
    app.mode = "live"
    return frame, calls


def process(app):
    return app._process(app.image, time.perf_counter())[1]


def test_live_dropout_suspends_keys_then_resumes_on_fresh_frames(app, monkeypatch):
    frame, calls = drive(app, monkeypatch)
    process(app)
    assert len(calls) == 1 and not app.controller.suspended
    frame["player"] = player("tracked", tracked=True, confidence=.62)
    status = process(app)
    assert app.controller.suspended and app.mode == "live" and len(calls) == 1
    assert "Recognition paused" in status["reason"]
    sent = list(app.controller.backend.events)
    frame["player"] = player()
    process(app)
    assert app.controller.suspended and len(calls) == 1
    assert app.controller.backend.events == sent or all(
        not down for _, down in app.controller.backend.events[len(sent):])  # releases only
    time.sleep(.16)
    process(app)
    assert not app.controller.suspended and app.mode == "live" and len(calls) == 2


def test_live_dropout_stops_after_two_seconds_without_the_player(app, monkeypatch):
    frame, calls = drive(app, monkeypatch)
    process(app)
    frame["player"] = None
    process(app)
    assert app.controller.suspended
    app.reacquisition.started -= RECOVERY_SECONDS
    process(app)
    assert app.mode == "capture" and app.stop_record.code == "PLAYER_UNCERTAIN"
    assert "timed out" in app.stop_record.message and len(calls) == 1


def test_another_name_tag_during_recovery_stops_at_once(app, monkeypatch):
    frame, calls = drive(app, monkeypatch)
    process(app)
    frame["player"] = None
    process(app)
    frame["player"] = player(OTHER)
    process(app)
    assert app.mode == "capture" and "Different player" in app.stop_record.message
    assert len(calls) == 1


def test_focus_loss_during_recovery_stops_input(app, monkeypatch):
    frame, calls = drive(app, monkeypatch)
    process(app)
    frame["player"] = None
    process(app)
    app.windows.window = replace(app.windows.window, focused=False)
    deadline = time.perf_counter() + 1
    while not app.controller.stopped.is_set():
        assert time.perf_counter() < deadline
        time.sleep(.005)
    frame["player"] = player()
    process(app)
    assert app.mode == "capture" and not app.controller.enabled and len(calls) == 1
