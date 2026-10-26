from dataclasses import replace

import pytest
from test_navigation import fixture

from maplebot.decision import Action
from maplebot.navigation import RouteMap, map_hash
from maplebot.navigation_executor import Feedback, Navigator
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
    assert nav.step(replace(f, now=.6)).vertical == "up"
    for now in (.8, 1, 1.2):
        nav.step(replace(f, now=now, feet=(150, 380), surface=None))
    assert nav.active and nav.completed == 0
    assert nav.step(replace(f, now=1.4, motion_ok=False)).release
    assert nav.stage == "stopped"
