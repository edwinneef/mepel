import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_navigation_runtime import preview
from test_runtime import app as _app

from maplebot import navigation_runtime
from maplebot.geometry import Rect
from maplebot.input_timing import KeyHold
from maplebot.navigation_executor import Feedback, Motion, Navigator
from maplebot.perception import Detection, Observation

app = _app


@pytest.fixture
def route(app, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(navigation_runtime, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    nav = preview(app)
    nav.agent = Navigator(nav.graph, nav.route, now[0])
    nav.agent.stage = "flight"
    nav.feedback = Feedback(now[0], nav.graph.fingerprint, (150, 400), "floor", True)
    nav.identity = "nametag:operator"
    app.position = SimpleNamespace(profile=nav.graph.profile,
                                   tracker=SimpleNamespace(transform=SimpleNamespace(
                                       to_area=lambda x, y: (x, y))))
    path = app.areas.directory / f"{nav.graph.profile['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nav.graph.profile), encoding="utf-8")
    app.mode = "navigation"
    app.controller.enable()

    def observe(*, tracked=False, confidence=1, identity="nametag:operator:tag-only"):
        now[0] += .2
        player = Detection("player", Rect(145, 380, 10, 20), confidence, identity, tracked)
        observation = Observation(player, [], camera_shift=(0, 0), camera_confidence=1)
        nav.observe(SimpleNamespace(dot=(150, 400)), observation,
                    {"surface_id": "floor"}, now[0])

    return app, nav, now, observe


def test_recognition_flicker_releases_then_requires_fresh_same_identity_pairs(route):
    app, nav, _, observe = route
    app.controller.refresh_movement("right", .25)
    started, edge_started = nav.agent.started, nav.agent.edge_started
    observe(tracked=True, confidence=.82522)
    assert nav.recovery and app.controller.suspended and not app.controller.held
    assert app._input_block_reason() is None  # Only the physical watchdog can pass while paused.
    assert app.controller.submit_sequence((KeyHold("jump", .02),)).startswith("blocked")
    observe()
    observe()
    assert nav.recovery and app.controller.suspended
    observe()
    assert nav.recovery is None and not app.controller.suspended
    assert nav.agent.started == started and nav.agent.edge_started == edge_started
    assert app.controller.backend.events == [("right", True), ("right", False)]
    assert nav.recovery_log[-1]["result"] == "resumed"


@pytest.mark.parametrize("failure", ["timeout", "stale", "view", "identity", "map"])
def test_recovery_stops_without_resuming_after_hard_failure(route, failure):
    app, nav, now, observe = route
    observe(tracked=True, confidence=.82522)
    if failure == "timeout":
        now[0] += 2
    elif failure == "stale":
        now[0] += .51
    elif failure == "view":
        app.view_generation += 1
    elif failure == "map":
        nav.feedback = replace(nav.feedback, fingerprint="changed")
    else:
        observe(identity="nametag:someone-else")
    nav.tick(None, now[0])
    assert app.mode == "capture" and not app.controller.enabled
    assert not app.controller.held and not app.controller.resume()


def test_operator_stop_cannot_be_undone_by_recognition_returning(route):
    app, nav, _, observe = route
    observe(tracked=True, confidence=.82522)
    app.safe_stop("OPERATOR_STOP", "Operator stopped recovery")
    for _ in range(4):
        observe()
    assert nav.recovery is None and app.mode == "capture" and not app.controller.enabled
    assert app.controller.backend.events == []


def test_fresh_sprite_without_name_corroboration_does_not_resume_name_recovery(route):
    app, nav, _, observe = route
    observe(tracked=True, confidence=.82522)
    for _ in range(4):
        observe(identity="fresh:pose", confidence=.95)
    assert nav.recovery and app.controller.suspended and not app.controller.held
    assert not any(e["result"] == "resumed" for e in nav.recovery_log)


def test_focus_loss_stops_the_watchdog_during_recovery(route):
    app, _, _, observe = route
    observe(tracked=True, confidence=.82522)
    app.windows.window = replace(app.windows.window, focused=False)
    assert app.controller.stopped.wait(.2)
    deadline = time.monotonic() + .3
    while app.mode != "capture" and time.monotonic() < deadline:
        time.sleep(.001)  # Stop releases keys before its notification finishes.
    assert app.mode == "capture" and not app.controller.enabled


def test_repeated_horizontal_intent_keeps_a_single_key_down(route, monkeypatch):
    app, nav, now, _ = route
    monkeypatch.setattr(nav.agent, "step", lambda f: Motion(horizontal="right"))
    for _ in range(8):
        now[0] += .1
        nav.feedback = replace(nav.feedback, now=now[0])
        nav.tick(None, now[0])
    assert app.controller.backend.events == [("right", True)]
    nav._release()
    assert app.controller.backend.events == [("right", True), ("right", False)]


def test_jump_then_climb_keeps_the_vertical_lease(route, monkeypatch):
    app, nav, now, _ = route
    monkeypatch.setattr(nav.agent, "step", lambda f: Motion(vertical="up"))
    for _ in range(4):
        now[0] += .1
        nav.feedback = replace(nav.feedback, now=now[0])
        nav.tick(None, now[0])
    assert app.controller.backend.events == [("up", True)]
    nav._release()
    assert app.controller.backend.events == [("up", True), ("up", False)]


def test_up_is_not_released_when_the_jump_ticket_completes(route, monkeypatch):
    app, nav, now, _ = route
    motions = [Motion((KeyHold("jump", .02),), vertical="up"), Motion(vertical="up")]
    monkeypatch.setattr(nav.agent, "step", lambda f: motions.pop(0))
    nav.tick(None, now[0])
    deadline = time.monotonic() + 1
    outcomes = []
    while not outcomes:
        assert time.monotonic() < deadline
        outcomes = app.controller.poll_outcomes()
        time.sleep(.001)
    for outcome in outcomes:
        app.arbiter.finished(outcome.ticket)
    now[0] += .1
    nav.feedback = replace(nav.feedback, now=now[0])
    nav.tick(None, now[0])
    assert ("up", False) not in app.controller.backend.events
    assert app.controller.backend.events.count(("up", True)) == 1


def test_drop_rides_the_marker_through_a_name_tag_dropout(route):
    # Live (SHG III fh130->fh53): the tag blurred mid-fall, recovery paused the drop and
    # then stopped on a 0.51 s frame gap.
    app, nav, now, observe = route
    nav.agent = Navigator(nav.graph, nav.graph.plan("ledge", "floor"), now[0])
    nav.agent.stage, nav.agent.edge_started = "flight", now[0]
    observe(tracked=True, confidence=.82522)
    assert nav.recovery is None and not app.controller.suspended
    assert nav.trusted() and app.mode == "navigation"
    nav.agent.edge_started = now[0] - 8  # Past the drop's marker-only budget.
    observe(tracked=True, confidence=.82522)
    assert nav.recovery and app.controller.suspended


def test_missing_vertical_lease_is_a_stop_not_a_recognition_recovery(route):
    app, nav, _, observe = route
    nav.lease = app.controller.start_vertical_lease("up")
    app.controller.release_vertical_lease(nav.lease)
    observe(tracked=True, confidence=.82522)
    assert nav.recovery is None and app.mode == "capture"
    assert not app.controller.enabled


def test_rope_grab_chords_pass_the_keyboard_controller(route):
    # Batch 9: a step submitted beside a held Up lease raised "Only a navigation jump may
    # preserve directional holds" in the controller and stopped the capture worker.
    app, nav, now, _ = route
    for holds in ((KeyHold("right", .12), KeyHold("up", .12)), (KeyHold("up", .12),)):
        submitted = app.controller.submit_sequence(holds)  # the runtime's holds-only path
        assert isinstance(submitted, (int, str))
    with pytest.raises(ValueError, match="Only a navigation jump"):
        app.controller.submit_sequence((KeyHold("right", .12),), preserve_movement=True)
