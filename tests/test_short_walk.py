import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_contracts import envelope, snapshot
from test_navigation import fixture
from test_runtime import app as _app

from maplebot.contracts import CommandGate
from maplebot.navigation import RouteMap, map_hash
from maplebot.navigation_executor import Feedback
from maplebot.short_walk import ShortWalk

app = _app


def setup():
    profile, evidence = fixture()
    profile["platforms"][0]["end"]["x"] = 560
    evidence["map_hash"] = map_hash(profile)
    graph = RouteMap(profile, evidence)
    walk = ShortWalk(graph, graph.plan("floor", "floor"), 0, (330, 400), -80)
    return walk, Feedback(0, graph.fingerprint, (330, 400), "floor", True)


def begin(walk, feedback):
    assert walk.step(feedback).release
    motion = walk.step(replace(feedback, now=.4))
    assert not motion.horizontal and not motion.vertical
    assert [(h.action, h.seconds) for h in motion.holds] == [("left", .08)]


def test_short_walk_pulses_then_releases_for_one_second_before_arrival():
    walk, f = setup()
    begin(walk, f)
    assert walk.step(replace(f, now=.6, feet=(300, 400))).holds
    for now in (.8, 1.2, 1.6):
        assert walk.step(replace(f, now=now, feet=(270, 400))).release
        assert walk.active
    assert walk.step(replace(f, now=1.9, feet=(270, 400))).release
    assert walk.stage == "arrived" and not walk.active
    assert walk.completed == 0  # This never certifies a platform-transition edge.


@pytest.mark.parametrize("change", [
    {"age": .51}, {"focused": False}, {"surface": "ledge"}, {"motion_ok": False},
    {"feet": None}, {"feet": (float("nan"), 400)}, {"fingerprint": "changed"},
    {"marker_only": True},
])
def test_lost_feedback_stops_without_retry(change):
    walk, f = setup()
    begin(walk, f)
    assert walk.step(replace(f, now=.6, **change)).release
    assert walk.stage == "stopped"
    assert walk.step(replace(f, now=.8)).release
    assert not walk.active


def test_moved_start_no_progress_and_departed_arrival_fail_closed():
    walk, f = setup()
    assert walk.step(replace(f, feet=(350, 400))).release
    assert walk.stage == "stopped"
    walk, f = setup()
    begin(walk, f)
    assert walk.step(replace(f, now=1.5)).release
    assert "no progress" in walk.reason
    walk, f = setup()
    begin(walk, f)
    walk.step(replace(f, now=.7, feet=(270, 400)))
    assert walk.step(replace(f, now=.9, feet=(210, 400))).release
    assert "no correction" in walk.reason


def test_arrival_needs_a_full_second_of_stable_feedback():
    walk, f = setup()
    begin(walk, f)
    walk.step(replace(f, now=.8, feet=(270, 400)))
    for now in (1.1, 1.5, 1.9):
        assert walk.step(replace(f, now=now, feet=(250, 400))).release
        assert walk.active
    walk.step(replace(f, now=2.2, feet=(250, 400)))
    assert walk.stage == "arrived"


def test_clock_budgets_and_bad_distances_or_edges_are_refused():
    walk, f = setup()
    begin(walk, f)
    assert walk.budget_blocker(3.4)
    assert walk.step(replace(f, now=3.5)).release and not walk.active
    for delta in (True, "80", 0, 40, 97, float("inf")):
        with pytest.raises(ValueError, match="48-96"):
            ShortWalk(walk.graph, walk.route, 0, (330, 400), delta)
    with pytest.raises(ValueError, match="stopping room"):
        ShortWalk(walk.graph, walk.route, 0, (170, 400), -80)


def prepare_runtime(app, monkeypatch):
    walk, _ = setup()
    nav = app.navigation
    nav.graph, nav.route = walk.graph, walk.route
    nav.feedback = Feedback(time.perf_counter(), walk.graph.fingerprint, (330, 400), "floor", True)
    app.position = SimpleNamespace(profile=walk.graph.profile, calibration={"saved": True},
                                   automatic=None)
    app.probed.update({"left", "right"})
    monkeypatch.setattr(nav, "refresh", lambda: None)
    return nav


def test_command_requires_optin_and_stop_cancels_without_any_input(app, monkeypatch):
    nav = prepare_runtime(app, monkeypatch)
    with pytest.raises(ValueError, match="opt-in"):
        app._command("nav_walk", {"dx": -80})
    app._command("nav_walk", {"dx": -80, "opt_in": True})
    assert isinstance(nav.agent, ShortWalk)
    assert nav.agent.target_x == 250 and app.mode == "navigation_wait"
    assert app.controller.backend.events == []
    app.request("stop", {})
    assert app.mode == "capture" and not nav.agent.active
    assert not app.controller.held and app.controller.backend.events == []


@pytest.mark.parametrize("gate", ["capture", "automatic", "controls", "poses", "calibration"])
def test_short_walk_preserves_start_gates(app, monkeypatch, gate):
    prepare_runtime(app, monkeypatch)
    if gate == "capture":
        app.capture_only = True
    elif gate == "automatic":
        app.position.automatic = {"version": 1}
    elif gate == "controls":
        app.probed.discard("left")
    elif gate == "poses":
        (app.areas.directory.parent / "recognition-coverage.json").write_text('{"verified": []}')
    else:
        app.position.calibration = None
    with pytest.raises(ValueError):
        app._command("nav_walk", {"dx": -80, "opt_in": True})
    assert app.mode == "capture" and not app.controller.enabled
    assert app.controller.backend.events == []


def test_short_walk_budget_stops_even_while_a_ticket_is_pending(app, monkeypatch):
    nav = prepare_runtime(app, monkeypatch)
    app._command("nav_walk", {"dx": -80, "opt_in": True})
    app.mode = "navigation"
    nav.ticket = 123
    nav.agent.moving_since = time.perf_counter() - 4
    nav.tick(None, time.perf_counter())
    assert app.mode == "capture" and not nav.agent.active
    assert not app.controller.held and app.alarm.snapshot()["active"]


def test_short_walk_cannot_recover_and_resume_after_recognition_loss(app, monkeypatch):
    nav = prepare_runtime(app, monkeypatch)
    app._command("nav_walk", {"dx": -80, "opt_in": True})
    app.mode = "navigation"
    nav._begin_recovery(nav.feedback)
    assert app.mode == "capture" and nav.recovery is None and not nav.agent.active
    assert not app.controller.held and app.alarm.snapshot()["active"]


def test_countdown_retains_point_target_and_refuses_a_changed_start(app, monkeypatch):
    nav = prepare_runtime(app, monkeypatch)
    app._command("nav_walk", {"dx": -80, "opt_in": True})
    app.pending_at = 0
    nav.feedback = replace(nav.feedback, now=time.perf_counter(), feet=(350, 400))
    nav.tick(None, time.perf_counter())
    assert isinstance(nav.agent, ShortWalk) and nav.agent.target_x == 250
    assert app.mode == "capture" and "starting position changed" in nav.agent.reason
    assert not app.controller.held and app.controller.backend.events == []


def test_walk_command_uses_versioned_fresh_frame_gate():
    status = snapshot()
    command = envelope(name="nav_walk", payload={"dx": -80, "opt_in": True})
    assert CommandGate().accept(command, status)[0] == "nav_walk"
    status["frame"]["age_ms"] = 2000
    with pytest.raises(ValueError, match="fresh matching frame"):
        CommandGate().accept(command, status)
