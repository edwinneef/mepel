from dataclasses import replace

import pytest
from test_navigation import fixture

from maplebot.decision import Action
from maplebot.navigation import Edge, Route, RouteMap, map_hash
from maplebot.navigation_executor import EdgeStep, Feedback, Navigator
from maplebot.scheduler import Arbiter


def setup():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    nav = Navigator(graph, graph.plan("floor", "ledge"), 0)
    return nav, Feedback(0, graph.fingerprint, (150, 400), "floor", True)


def takeoff(nav, f):
    for now in (0, .2, .4):
        assert nav.step(replace(f, now=now)).release
    motion = nav.step(replace(f, now=.6))
    assert [hold.action for hold in motion.holds] == ["right", "jump"]


def test_jump_requires_departure_and_settled_destination_not_predicted_elapsed_time():
    nav, f = setup()
    takeoff(nav, f)
    nav.step(replace(f, now=.8, feet=(220, 260), surface=None))
    for now in (1, 1.2, 1.4):
        motion = nav.step(replace(f, now=now, feet=(280, 300), surface="ledge"))
    assert nav.stage == "arrived" and motion.release
    assert nav.completed == 1


@pytest.mark.parametrize("changes", [
    {"age": .51}, {"motion_ok": False}, {"focused": False}, {"fingerprint": "edited"},
    {"feet": None}, {"feet": (590, 260)},
])
def test_feedback_failure_cancels_and_never_automatically_resumes(changes):
    nav, f = setup()
    takeoff(nav, f)
    assert nav.step(replace(f, now=.8, **changes)).release
    assert nav.stage == "stopped"
    assert nav.step(replace(f, now=1)).release and nav.stage == "stopped"


def test_edge_deadline_includes_retry_and_arrival_does_not_depend_on_key_completion():
    nav, f = setup()
    takeoff(nav, f)
    assert nav.step(replace(f, now=1.7)).release
    assert nav.retries == 1
    assert nav.step(replace(f, now=8.1)).release
    assert nav.stage == "stopped"


def test_potion_preempts_navigation_and_combat_cannot_share_the_lane():
    arbiter = Arbiter(.06)
    nav = Action("right", .1)
    assert arbiter.choose(sustain="hp", combat=None, navigation=nav).lane == "hp"
    arbiter.submitted(1, "hp")
    assert arbiter.choose(sustain=None, combat=None, navigation=nav).action is None
    arbiter.finished(1)
    assert arbiter.choose(sustain=None, combat=None, navigation=nav).lane == "navigation"
    assert arbiter.choose(sustain=None, combat=Action("attack", .1), navigation=nav).action is None


def test_rope_proximity_without_vertical_progress_cannot_confirm_grip():
    profile, _ = fixture()
    profile["ropes"] = [{"id": "rope", "start": {"x": 150, "y": 250},
                         "end": {"x": 150, "y": 400}}]
    profile["links"] = [{"id": key, "from": a, "to": b, "kind": "climb"}
                        for key, a, b in (("up", "floor", "rope"), ("back", "rope", "floor"))]
    evidence = {"area_id": profile["id"], "revision": 4, "map_hash": map_hash(profile),
                "edges": {key: {**link, "source": "session", "missing_checks": 0, "max_gap": .2,
                                "trace": trace}
                          for key, link, trace in (
                              ("up", profile["links"][0], [[150, 400], [150, 380], [150, 350]]),
                              ("back", profile["links"][1], [[150, 350], [150, 400]]))}}
    graph = RouteMap(profile, evidence)
    nav = Navigator(graph, graph.plan("floor", "rope"), 0)
    f = Feedback(0, graph.fingerprint, (150, 400), "floor", True)
    for now in (0, .2, .4):
        nav.step(replace(f, now=now))
    grab = nav.step(replace(f, now=.6))
    assert [hold.action for hold in grab.holds] == ["up", "jump"]
    for now in (.8, 1, 1.2):
        nav.step(replace(f, now=now, feet=(150, 380), surface=None))
    assert nav.active and nav.completed == 0
    assert nav.step(replace(f, now=1.4, motion_ok=False)).release
    assert nav.stage == "stopped"


def test_dropped_rope_grab_chord_is_repeated_from_the_launch_floor():
    profile, _ = fixture()
    profile["ropes"] = [{"id": "rope", "start": {"x": 150, "y": 250},
                         "end": {"x": 150, "y": 400}}]
    profile["links"] = [{"id": key, "from": a, "to": b, "kind": "climb"}
                        for key, a, b in (("up", "floor", "rope"), ("back", "rope", "floor"))]
    evidence = {"area_id": profile["id"], "revision": 4, "map_hash": map_hash(profile),
                "edges": {key: {**link, "source": "session", "missing_checks": 0, "max_gap": .2,
                                "trace": trace}
                          for key, link, trace in (
                              ("up", profile["links"][0], [[150, 400], [150, 380], [150, 350]]),
                              ("back", profile["links"][1], [[150, 350], [150, 400]]))}}
    graph = RouteMap(profile, evidence)
    nav = Navigator(graph, graph.plan("floor", "rope"), 0)
    f = Feedback(0, graph.fingerprint, (150, 400), "floor", True)
    for now in (0, .2, .4, .6):  # the .6 takeoff chord is lost behind a running walk pulse
        nav.step(replace(f, now=now))
    assert nav.stage == "flight"
    aligned = nav.step(replace(f, now=.8, feet=(158, 400)))
    assert [hold.action for hold in aligned.holds] == ["up", "jump"]
    offset = nav.step(replace(f, now=1, feet=(170, 400)))
    assert [hold.action for hold in offset.holds] == ["left", "up", "jump"]
    assert nav.step(replace(f, now=1.2, feet=(150, 380), surface=None)).vertical == "up"


def test_rope_to_platform_approaches_recorded_height_before_entering_its_corridor():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    graph.profile["ropes"] = [{"id": "rope", "start": {"x": 150, "y": 200},
                               "end": {"x": 150, "y": 400}}]
    graph.nodes["rope"] = graph.profile["ropes"][0]
    edge = Edge("off", "rope", "ledge", "climb", (150, 280), (280, 300),
                ((150, 280), (280, 300)), "saved")
    route = Route(profile["id"], 4, graph.fingerprint, "rope", "ledge", (edge,))
    nav = Navigator(graph, route, 0)
    nav.stage = "approach"
    f = Feedback(.1, graph.fingerprint, (150, 380), None, True)
    assert nav.step(f).vertical == "up" and nav.stage == "approach"
    assert nav.step(replace(f, now=.2, feet=(150, 330))).vertical == "up"
    assert nav.step(replace(f, now=.3, feet=(150, 280))).vertical == "down"
    assert nav.stage == "flight"

def test_marker_only_destination_never_counts_as_settled():
    nav, f = setup()
    takeoff(nav, f)
    for now in (1, 1.4, 1.8):
        nav.step(replace(f, now=now, feet=(280, 300), surface="ledge", marker_only=True))
    assert nav.completed == 0 and nav.stage == "flight"
    for now in (2, 2.4):
        nav.step(replace(f, now=now, feet=(280, 300), surface="ledge"))
    assert nav.stage == "arrived"


def edge_step(feet=(450, 400)):
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    return EdgeStep(graph, 0), Feedback(0, graph.fingerprint, feet, None, False)


def test_edge_step_walks_inward_on_the_marker_until_the_name_tag_returns():
    step, f = edge_step()
    assert [hold.action for hold in step.step(f).holds] == ["left"]
    assert [hold.action for hold in step.step(replace(f, now=.3, feet=(440, 400))).holds] == [
        "left"]
    assert step.step(replace(f, now=.6, feet=(430, 400), surface="floor",
                             motion_ok=True)).release
    assert step.stage == "arrived"
    left, f = edge_step((120, 400))
    assert [hold.action for hold in left.step(f).holds] == ["right"]


@pytest.mark.parametrize(("frames", "reason"), [
    ([(0, 300)], "not at a map edge"),
    ([(0, 450), (.8, 449), (1.6, 448)], "No inward movement"),
    ([(0, 450), (.3, 380)], "Left the map edge"),
    ([(0, 455 - 8 * i) for i in range(1)] + [(.5 * i, 455 - 8 * i) for i in range(1, 9)],
     "deadline"),
])
def test_edge_step_stops_without_progress_away_from_edges_or_after_its_deadline(frames, reason):
    step, f = edge_step()
    for now, x in frames:
        motion = step.step(replace(f, now=now, feet=(x, 400)))
    assert motion.release and step.stage == "stopped" and reason in step.reason


def test_edge_step_needs_a_fresh_marker_and_focus():
    for changes in ({"age": .6}, {"focused": False}, {"feet": None}, {"fingerprint": "x"}):
        step, f = edge_step()
        assert step.step(replace(f, **changes)).release and step.stage == "stopped"
