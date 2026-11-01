import time
from dataclasses import replace

import pytest
from test_runtime import app as _app

from maplebot.decision import Action, Decision, State
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation
from maplebot.reacquisition import RECOVERY_SECONDS, ConfirmedSprites, Reacquisition

app = _app
ME, OTHER = "nametag:me", "nametag:other"


def test_track_identity_needs_a_recent_name_and_spatial_continuity():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    assert identities.resolve("pose", box, 0, 80) is None
    identities.observe(ME, "pose", box, 0)
    assert identities.resolve("pose", box, .5, 80) == ME
    assert identities.resolve("climb", box, .6, 80) == ME  # an unseen pose continues the track
    assert identities.resolve("pose", box.translated(100, 0), .7, 80) is None
    assert identities.resolve("pose", box, .7 + RECOVERY_SECONDS, 80) is None
    assert identities.resolve("pose", box, -.1, 80) is None
    identities.observe(ME, None, box, 4.8)  # Fresh name alone renews its identity evidence.
    assert identities.resolve("climb", box, 5.2, 80) == ME


def test_sprite_seen_with_another_name_never_continues_the_track():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    identities.observe(OTHER, "theirs", box.translated(300, 0), 0)
    identities.observe(ME, "pose", box, .1)
    assert identities.resolve("theirs", box, .2, 80) is None
    assert identities.resolve("pose", box, .3, 80) == ME


def test_chain_follows_camera_scrolling():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    identities.observe(ME, "pose", box, 0)
    identities.translate(0, 120)  # the camera scrolled down after a climb
    assert identities.resolve("pose", box.translated(0, 120), .3, 80) == ME
    assert identities.resolve("pose", box, .4, 80) is None


def test_continuous_nearby_sprite_frames_carry_the_name_while_the_tag_is_hidden():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    identities.observe(ME, "pose", box, 0)
    for step in range(1, 13):  # 3.6 s of tag-hidden frames, each near the previous one
        box = box.translated(0, 4)
        assert identities.resolve("pose", box, step * .3, 80) == ME
    # A gap without any fresh evidence still expires, and a jump still breaks the chain.
    assert identities.resolve("pose", box, 3.6 + RECOVERY_SECONDS, 80) is None
    assert identities.resolve("pose", box.translated(100, 0), 3.7, 80) is None


def test_sprite_shared_by_different_names_is_never_an_identity_alias():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    identities.observe(ME, "pose", box, 0)
    identities.observe(OTHER, "pose", box, .1)
    assert identities.resolve("pose", box, .2, 80) is None
    identities.observe(ME, "pose", box, .3)
    assert identities.resolve("pose", box, .4, 80) is None


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


def test_live_dropout_resumes_with_a_fresh_independently_named_sprite(app, monkeypatch):
    frame, calls = drive(app, monkeypatch)
    process(app)
    frame["player"] = None
    process(app)
    frame["player"] = replace(player("pose"), identity=ME)
    process(app)
    assert app.controller.suspended and len(calls) == 1
    time.sleep(.16)
    process(app)
    assert not app.controller.suspended and len(calls) == 2


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


def test_weak_nearby_frames_keep_the_name_chain_through_foreground_cover():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    identities.observe(ME, "pose", box, 0)
    for step in range(1, 11):  # 3 s behind a log: tracked frames only, each near the last
        box = box.translated(-6, 0)
        identities.follow(box, step * .3, 80)
    assert identities.resolve("pose", box, 3.2, 80) == ME
    identities.follow(box.translated(200, 0), 3.3, 80)  # a far frame never moves the chain
    assert identities.resolve("pose", box.translated(200, 0), 3.4, 80) is None
    assert identities.resolve("pose", box, 3.2 + RECOVERY_SECONDS, 80) is None


def test_continuity_allowance_grows_with_elapsed_time_not_one_frame_jumps():
    identities = ConfirmedSprites()
    box = Rect(100, 100, 44, 64)
    identities.observe(ME, "pose", box, 0)
    # A look-alike 73 px away one frame later is too far to be the same, stationary player.
    assert identities.resolve("pose", box.translated(73, 0), .22, 80) is None
    assert identities.resolve("pose", box.translated(20, 0), .22, 80) == ME


def test_a_sprite_the_named_track_did_not_carry_pauses_instead_of_hijacking():
    r = Reacquisition()
    assert r.step(ME, 0).state == "ok"
    assert r.step("look-alike-sprite", .3).state == "pause"  # no carried name: maybe another
    assert r.step("look-alike-sprite", .6).state == "wait"
    assert r.step(ME, .9).state == "wait"
    assert r.step(ME, 1.1).state == "resume"
