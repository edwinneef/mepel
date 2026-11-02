import time
from dataclasses import replace

import pytest
from test_keyboard import controller as _controller
from test_navigation import fixture
from test_runtime import app as _app

from maplebot.decision import Action, Decision, State
from maplebot.geometry import Rect
from maplebot.navigation import RouteMap
from maplebot.navigation_executor import Feedback
from maplebot.perception import Detection, Observation
from maplebot.rotation import Rotation, routable, unproven_neighbours, visible_by_surface

app, controller = _app, _controller
PLAYER = Detection("player", Rect(500, 300, 40, 60), .95)


def monster(x: int, feet: int, *, confidence: float = .95, tracked: bool = False) -> Detection:
    return Detection("monster", Rect(x - 20, feet - 40, 40, 40), confidence, "", tracked)


def test_waits_for_the_clear_time_then_prefers_visible_monsters():
    rotation = Rotation(4)
    args = {"searching": True, "surface": "a", "platforms": ["a", "b", "c"]}
    assert rotation.step(0, **args, visible={}) is None
    assert rotation.step(3.9, **args, visible={"c": 2}) is None
    assert rotation.step(4, **args, visible={"c": 2}) == "c"
    assert rotation.clear_since is None


def test_fighting_or_an_unknown_platform_restarts_the_clear_timer():
    rotation = Rotation(4)
    args = {"platforms": ["a", "b"], "visible": {}}
    rotation.step(0, searching=True, surface="a", **args)
    rotation.step(3, searching=False, surface="a", **args)
    assert rotation.step(5, searching=True, surface="a", **args) is None
    rotation.step(6, searching=True, surface=None, **args)
    assert rotation.clear_since is None and "unknown" in rotation.reason


def test_without_visible_monsters_it_visits_the_platform_left_longest_ago():
    rotation = Rotation(1)
    platforms = ["a", "b", "c"]
    assert rotation.step(0, searching=True, surface="a", platforms=platforms, visible={}) is None
    assert rotation.step(1, searching=True, surface="a", platforms=platforms, visible={}) == "b"
    rotation.arrived("b", 5)
    rotation.step(5, searching=True, surface="b", platforms=platforms, visible={})
    assert rotation.step(6, searching=True, surface="b", platforms=platforms, visible={}) == "c"
    rotation.arrived("c", 9)
    rotation.step(9, searching=True, surface="c", platforms=platforms, visible={})
    assert rotation.step(10, searching=True, surface="c", platforms=platforms, visible={}) == "a"


def test_equally_unvisited_platforms_prefer_the_shortest_route():
    rotation = Rotation(1)
    args = {"searching": True, "surface": "a", "platforms": ["a", "b", "c"], "visible": {}}
    rotation.step(0, **args, edges={"b": 6, "c": 1})
    assert rotation.step(1, **args, edges={"b": 6, "c": 1}) == "c"


def test_a_single_routable_platform_never_moves():
    rotation = Rotation(1)
    for now in range(5):
        assert rotation.step(now, searching=True, surface="a", platforms=["a"], visible={}) is None


def test_visible_monsters_are_placed_on_routable_platforms_only():
    graph = RouteMap(*fixture())
    assert routable(graph) == ["floor", "ledge"]
    # Player stands on floor (y=400) at screen x=520; ledge is 100 px higher.
    counts = visible_by_surface(graph, (120, 400), PLAYER, [
        monster(720, 260), monster(640, 260, tracked=True), monster(700, 260, confidence=.5),
        monster(560, 360), monster(520, 160)], .9)
    assert counts == {"ledge": 1, "floor": 1}


def preview(app, mode="live"):
    profile, evidence = fixture()
    nav = app.navigation
    nav.graph = RouteMap(profile, evidence)
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400),
                            "floor", True)
    app.probed.update({"left", "right", "jump"})
    app.mode, app.rotating = mode, True
    app.rotation = Rotation(1)
    return nav


SEARCH = Decision(State.SEARCH, Action(), "Waiting for a fresh confident same-platform target")


def test_clear_platform_hands_off_to_navigation_and_arrival_resumes_combat(app):
    nav = preview(app)
    app.controller.enable()
    now = time.perf_counter()
    observation = Observation(PLAYER, [])
    assert app._rotate(SEARCH, observation, now) is None
    assert "moving to ledge" in app._rotate(SEARCH, observation, now + 1)
    assert app.mode == "navigation" and nav.resume_combat
    assert (nav.route.origin, nav.route.target) == ("floor", "ledge")
    nav.agent.stage = "arrived"
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (280, 300),
                            "ledge", True)
    nav.tick(None, time.perf_counter())
    assert app.mode == "live" and app.agent.state == State.SEARCH
    assert not nav.resume_combat and app.rotation.visited["ledge"]


def test_route_failure_during_rotation_stops_instead_of_resuming(app):
    nav = preview(app)
    app.controller.enable()
    now = time.perf_counter()
    app._rotate(SEARCH, Observation(PLAYER, []), now)
    app._rotate(SEARCH, Observation(PLAYER, []), now + 1)
    nav.agent.stop("Edge deadline exhausted; no blind retry")
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (200, 350), None, True)
    nav.tick(None, time.perf_counter())
    assert app.mode == "capture" and not app.rotating and not nav.resume_combat


def test_refused_route_stops_safely(app):
    nav = preview(app)
    app.probed.discard("jump")
    now = time.perf_counter()
    app._rotate(SEARCH, Observation(PLAYER, []), now)
    reason = app._rotate(SEARCH, Observation(PLAYER, []), now + 1)
    assert reason.startswith("Rotation: Verify navigation controls")
    assert app.mode == "capture" and nav.agent is None


def test_dry_run_only_reports_the_intended_move(app):
    nav = preview(app, "dry_run")
    now = time.perf_counter()
    app._rotate(SEARCH, Observation(PLAYER, []), now)
    assert "would move to ledge" in app._rotate(SEARCH, Observation(PLAYER, []), now + 1)
    assert app.mode == "dry_run" and nav.agent is None
    assert app.controller.backend.events == []


def test_rotation_needs_two_round_trip_platforms(app):
    with pytest.raises(ValueError, match="saved map"):
        app._prepare_rotation(True)
    app._prepare_rotation(False)
    assert not app.rotating


def test_destinations_beyond_the_route_budget_are_never_chosen(app, monkeypatch):
    nav = preview(app)
    app.controller.enable()

    def plan(origin, target, **_):
        raise ValueError("No evidenced safe route within the eight-edge budget")

    monkeypatch.setattr(nav.graph, "plan", plan)
    now = time.perf_counter()
    app._rotate(SEARCH, Observation(PLAYER, []), now)
    assert app._rotate(SEARCH, Observation(PLAYER, []), now + 1) is None
    assert app.mode == "live" and "No other routable platform" in app.rotation.reason


def test_unproven_neighbours_are_one_move_platforms_outside_the_round_trip_map():
    profile, evidence = fixture()
    assert unproven_neighbours(RouteMap(profile, evidence, proven=set()), "floor") == {
        "ledge": "up"}
    assert unproven_neighbours(RouteMap(profile, evidence), "floor") == {}


def test_unproven_neighbours_skip_falls_that_leave_the_visible_play_area():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence, proven=set())
    up = graph.edges["up"]
    # Launch at y=400; a trace dipping 100 px is still tried, 101 px is not.
    graph.edges["up"] = replace(up, trace=((150, 400), (180, 500), (280, 300)))
    assert unproven_neighbours(graph, "floor") == {"ledge": "up"}
    graph.edges["up"] = replace(up, trace=((150, 400), (180, 501), (280, 300)))
    assert unproven_neighbours(graph, "floor") == {}


def test_a_clear_platform_tries_an_unproven_neighbour_without_routable_platforms():
    rotation = Rotation(1)
    explore = {"b": "a-to-b"}
    assert rotation.step(0, searching=True, surface="a", platforms=["a"], visible={},
                         explore=explore) is None
    assert rotation.step(1, searching=True, surface="a", platforms=["a"], visible={},
                         explore=explore) == "b"
    assert "trying a new move to b" in rotation.reason


def learning(app, enabled):
    nav = preview(app)
    profile, evidence = fixture()
    nav.graph = RouteMap(profile, evidence, proven=set())
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400),
                            "floor", True)
    app.learning_moves = enabled
    app.controller.enable()
    return nav


def test_learning_farm_tries_one_unproven_move_with_proven_only_replans(app):
    nav = learning(app, True)
    now = time.perf_counter()
    assert app._rotate(SEARCH, Observation(PLAYER, []), now) is None
    assert "trying a new move to ledge" in app._rotate(SEARCH, Observation(PLAYER, []), now + 1)
    assert app.mode == "navigation" and nav.resume_combat
    assert [edge.id for edge in nav.route.edges] == ["up"] and nav.agent.trusted_only


def test_without_learning_an_unproven_move_is_never_tried(app):
    nav = learning(app, False)
    now = time.perf_counter()
    app._rotate(SEARCH, Observation(PLAYER, []), now)
    assert app._rotate(SEARCH, Observation(PLAYER, []), now + 1) is None
    assert app.mode == "live" and nav.agent is None
