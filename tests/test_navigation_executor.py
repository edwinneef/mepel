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
    assert nav.step(replace(f, now=8.7)).release  # 8 s after the first takeoff at 0.6
    assert nav.stage == "stopped" and "Edge deadline" in nav.reason


def test_launch_approach_has_its_own_budget_and_arrives_within_one_marker_step():
    # Live (Southperry ladder): a walk plus a stepped stop used up a shared 8 s edge clock,
    # and 16 px marker steps skipped the 12 px launch window.
    nav, f = setup()
    for now in (0, .2, .4):
        nav.step(replace(f, now=now, feet=(52, 400)))
    for now, x in ((2.5, 70), (5, 90), (7.5, 110), (8.4, 134)):
        nav.step(replace(f, now=now, feet=(x, 400)))
        assert nav.stage == "approach"
    holds = []
    for now in (8.6, 8.8, 9.0, 9.2):
        holds = [h.action for h in nav.step(replace(f, now=now, feet=(134, 400))).holds]
        if holds:
            break
    assert holds == ["right", "jump"] and nav.stage == "flight"


def test_launch_approach_stops_without_progress_or_past_its_budget():
    nav, f = setup()
    for now in (0, .2, .4):
        nav.step(replace(f, now=now, feet=(52, 400)))
    for now in (.5, 2, 3.6):
        nav.step(replace(f, now=now, feet=(52, 400)))
    assert nav.stage == "stopped" and "No progress toward the launch" in nav.reason
    nav, f = setup()
    for now in (0, .2, .4):
        nav.step(replace(f, now=now, feet=(52, 400)))
    for now, x in ((2.5, 61), (5, 70), (7.5, 79), (10, 88)):  # progress, but too slowly
        nav.step(replace(f, now=now, feet=(x, 400)))
    assert nav.stage == "stopped" and "Approach deadline exhausted" in nav.reason


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
    assert grab.vertical == "up" and [hold.action for hold in grab.holds] == ["jump"]
    for now in (.8, 1, 1.2):
        nav.step(replace(f, now=now, feet=(150, 380), surface=None))
    assert nav.active and nav.completed == 0
    assert nav.step(replace(f, now=1.4, motion_ok=False)).release
    assert nav.stage == "stopped"


def test_rope_grab_aligns_before_jumping_and_ignores_delayed_launch_feedback():
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
    f = Feedback(0, graph.fingerprint, (136, 400), "floor", True)
    for now in (0, .2, .4):
        nav.step(replace(f, now=now))
    alignment = nav.step(replace(f, now=.6))
    assert nav.stage == "approach" and alignment.vertical is None
    assert [hold.action for hold in alignment.holds] == ["right"]
    # A short tap may not move the coarse minimap marker. Settle and tap again.
    assert nav.step(replace(f, now=.8)).release
    realign = nav.step(replace(f, now=1.2))
    assert [hold.action for hold in realign.holds] == ["right"]
    assert nav.stage == "approach" and realign.vertical is None
    assert nav.step(replace(f, now=1.4, feet=(150, 400))).release
    grab = nav.step(replace(f, now=1.8, feet=(150, 400)))
    assert nav.stage == "flight"
    assert grab.vertical == "up" and [hold.action for hold in grab.holds] == ["jump"]
    for now, feet, surface in ((2.0, (150, 400), "floor"),
                               (2.2, (170, 330), None), (2.4, (182, 330), None)):
        motion = nav.step(replace(f, now=now, feet=feet, surface=surface))
        assert motion.vertical == "up" and not motion.holds
        assert motion.horizontal is None


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


def test_stationary_landing_restarts_settling_after_marker_only_gap():
    nav, f = setup()
    takeoff(nav, f)
    landing = replace(f, feet=(280, 300), surface="ledge")
    nav.step(replace(landing, now=1))
    nav.step(replace(landing, now=1.2, marker_only=True))
    assert nav.settle_since is None and nav.stage == "flight"
    for now in (1.4, 1.6):
        nav.step(replace(landing, now=now))
        assert nav.stage == "flight"
    motion = nav.step(replace(landing, now=1.8))
    assert nav.stage == "arrived" and motion.release


def test_knockback_along_the_destination_platform_settles_instead_of_failing():
    nav, f = setup()
    takeoff(nav, f)
    landing = replace(f, feet=(280, 300), surface="ledge")
    nav.step(replace(landing, now=1))
    knocked = replace(landing, feet=(360, 296))  # a monster hit pushed it 80 px along the ledge
    for now in (1.2, 1.4, 1.6):
        motion = nav.step(replace(knocked, now=now))
        assert motion.release and nav.stage != "stopped"
    nav.step(replace(knocked, now=1.8))
    assert nav.stage == "arrived"


def test_leaving_the_corridor_onto_another_surface_still_fails():
    nav, f = setup()
    takeoff(nav, f)
    nav.step(replace(f, feet=(280, 300), surface="ledge", now=1))
    nav.step(replace(f, feet=(420, 400), surface="floor", now=1.2))
    assert nav.stage == "stopped" and "corridor" in nav.reason


def test_lost_destination_evidence_releases_instead_of_steering_to_landing():
    nav, f = setup()
    takeoff(nav, f)
    landing = replace(f, feet=(280, 300), surface="ledge")
    nav.step(replace(landing, now=1))
    motion = nav.step(replace(landing, feet=(310, 286), surface=None, now=1.2))
    assert motion.release and not motion.holds and motion.horizontal is None
    assert nav.completed == 0 and nav.settle_since is None
    for now in (1.4, 1.6):
        nav.step(replace(landing, now=now))
        assert nav.completed == 0
    assert nav.step(replace(landing, now=1.8)).release
    assert nav.stage == "arrived"


def test_lost_destination_evidence_does_not_relax_corridor_or_deadline():
    for feet, now, reason in [((360, 300), 1.2, "corridor"),
                              ((310, 286), 8.7, "deadline")]:
        nav, f = setup()
        takeoff(nav, f)
        nav.step(replace(f, feet=(280, 300), surface="ledge", now=1))
        motion = nav.step(replace(f, feet=feet, surface=None, now=now))
        assert motion.release and nav.stage == "stopped" and reason in nav.reason


@pytest.mark.parametrize(("launch", "landing", "heights", "direction"), [
    (342.1, 312.1, (438.76, 360.02, 328.52, 312.77), "up"),
    (312.1, 342.1, (250, 296.35, 328.52, 344.27), "down"),
])
def test_rope_launch_height_overshoot_keeps_the_route_direction(
        launch, landing, heights, direction):
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    graph.profile["ropes"] = [{"id": "rope", "start": {"x": 150, "y": 200},
                               "end": {"x": 150, "y": 450}}]
    graph.nodes["rope"] = graph.profile["ropes"][0]
    edge = Edge("off", "rope", "ledge", "climb", (150, launch), (150, landing),
                ((150, launch), (150, landing)), "saved")
    route = Route(profile["id"], 4, graph.fingerprint, "rope", "ledge", (edge,))
    nav = Navigator(graph, route, 0)
    nav.stage = "approach"
    for i, y in enumerate(heights):
        motion = nav.step(Feedback(.2 * (i + 1), graph.fingerprint, (150, y), None, True))
        assert motion.vertical == direction or motion.release
        assert not motion.holds
    assert nav.stage == "flight"


@pytest.mark.parametrize(("y", "climbing"), [(345.2, False), (343, False), (352, True)])
def test_ladder_exit_one_marker_step_short_releases_instead_of_climbing_on(y, climbing):
    # Live (SHG III rope3): the marker read 2.2 px below the exit for 1.2 s; holding "up"
    # walked the player off the ladder top and out of the recorded corridor.
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    graph.profile["ropes"] = [{"id": "rope", "start": {"x": 150, "y": 200},
                               "end": {"x": 150, "y": 450}}]
    graph.nodes["rope"] = graph.profile["ropes"][0]
    edge = Edge("off", "rope", "ledge", "climb", (150, 373), (150, 343),
                ((150, 373), (150, 343)), "saved")
    nav = Navigator(graph, Route(profile["id"], 4, graph.fingerprint, "rope", "ledge",
                                 (edge,)), 0)
    nav.stage, nav.departed, nav.takeoff_at = "flight", True, 0
    motion = nav.step(Feedback(.2, graph.fingerprint, (150, y), None, True))
    assert (motion.vertical == "up") is climbing and motion.release is not climbing


def test_rope_approach_brakes_before_takeoff_instead_of_jumping_with_horizontal_motion():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    graph.profile["ropes"] = [{"id": "rope", "start": {"x": 250, "y": 250},
                               "end": {"x": 250, "y": 400}}]
    graph.nodes["rope"] = graph.profile["ropes"][0]
    edge = Edge("up", "floor", "rope", "climb", (250, 400), (250, 350),
                ((250, 400), (250, 350)), "saved")
    route = Route(profile["id"], 4, graph.fingerprint, "floor", "rope", (edge,))
    nav = Navigator(graph, route, 0)
    nav.stage = "approach"
    f = Feedback(.2, graph.fingerprint, (207, 400), "floor", True)
    # Recorded pre-launch distance: 43 pixels, past the floor's end: step from rest.
    assert nav.step(f).release and nav.step(replace(f, now=.4)).release
    step = nav.step(replace(f, now=.55))
    assert step.horizontal is None and [h.action for h in step.holds] == ["right"]
    assert step.holds[0].seconds == nav.pulse
    for now, x in ((.6, 240), (.7, 250), (.9, 250)):
        assert nav.step(replace(f, now=now, feet=(x, 400))).release
        assert nav.stage == "approach"
    takeoff = nav.step(replace(f, now=1.1, feet=(250, 400)))
    assert nav.stage == "flight" and takeoff.vertical == "up"
    assert takeoff.horizontal is None and [h.action for h in takeoff.holds] == ["jump"]


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


def test_coasting_past_the_launch_on_the_source_platform_is_not_a_takeoff():
    nav, f = setup()
    takeoff(nav, f)
    # The jump never happened: the marker slid 22 px along the floor.
    for now in (.8, 1.0, 1.2):
        nav.step(replace(f, now=now, feet=(172, 400)))
    assert not nav.departed
    assert nav.step(replace(f, now=1.7, feet=(172, 400))).release
    assert nav.retries == 1 and nav.stage == "settle_origin"


def test_falling_back_onto_the_launch_platform_releases_keys_then_retries_once():
    # Live: knocked back off the landing onto the launch platform, the steer toward the
    # landing walked off its end.
    nav, f = setup()
    for attempt in (0, 3):
        for now in (0, .2, .4):
            nav.step(replace(f, now=attempt + now))
        assert nav.step(replace(f, now=attempt + .6)).holds
        nav.step(replace(f, now=attempt + .8, feet=(220, 260), surface=None))
        assert nav.departed
        for now in (1.7, 1.9):
            motion = nav.step(replace(f, now=attempt + now, feet=(120, 390), surface=None))
            assert motion.release and not motion.horizontal and not motion.holds
            assert "Back on the launch platform" in nav.reason
        nav.step(replace(f, now=attempt + 2.1, feet=(120, 390), surface=None))
        f = replace(f, feet=(150, 400))
    assert nav.stage == "stopped" and "retry budget exhausted" in nav.reason


def test_a_down_jump_hop_near_the_launch_platform_is_not_a_fall_back():
    # Live (SHG III fh130->fh53): the hop peaked within the launch platform's 16 px
    # tolerance and was judged "back on the launch platform" 0.6 s into the drop.
    nav, f = setup()
    takeoff(nav, f)
    nav.step(replace(f, now=.8, feet=(150, 386), surface=None))
    assert nav.departed
    nav.step(replace(f, now=1.0, feet=(150, 392), surface=None))
    assert "launch platform" not in nav.reason and nav.retries == 0


def test_knocked_off_the_origin_settles_then_replans_from_the_new_surface():
    # Live: a snail knocked the player off a settled landing before the next route began.
    nav, f = setup()
    ledge = replace(f, feet=(280, 300), surface="ledge")
    for now in (0, .2, .4):
        assert nav.step(replace(ledge, now=now)).release
        assert nav.stage == "settle_origin" and "replan" in nav.reason
    assert nav.replans == 1 and nav.route.edges == ()
    for now in (.6, .8, 1.0):
        nav.step(replace(ledge, now=now))
    assert nav.stage == "arrived"
    nav, f = setup()
    assert nav.step(replace(f, feet=(100, 200), surface="island")).release
    assert nav.stage == "stopped" and "Origin no longer matches" in nav.reason


def test_jump_takes_off_only_after_braking_at_the_launch():
    nav, f = setup()
    for now in (0, .2, .4):
        nav.step(replace(f, now=now))
    assert nav.stage == "approach"
    assert nav.step(replace(f, now=.5, feet=(52, 400))).horizontal == "right"
    # Arriving at the launch straight from a walk: brake first, keys released.
    assert nav.step(replace(f, now=.6, feet=(158, 400))).release
    assert nav.stage == "approach" and "Braking at jump launch" in nav.reason
    assert nav.step(replace(f, now=.8, feet=(158, 400))).release
    motion = nav.step(replace(f, now=.95, feet=(158, 400)))
    assert [hold.action for hold in motion.holds] == ["right", "jump"]


def test_launch_with_a_zone_within_braking_distance_is_reached_from_rest():
    # Live (Southperry): braking at a jump launch slid the player into a portal zone.
    profile, evidence = fixture()
    profile["zones"] = [{"id": "portal", "kind": "portal",
                         "rect": {"x": 70, "y": 390, "width": 5, "height": 10}}]
    evidence["map_hash"] = map_hash(profile)
    graph = RouteMap(profile, evidence)
    nav = Navigator(graph, graph.plan("floor", "ledge"), 0)
    f = Feedback(0, graph.fingerprint, (190, 400), "floor", True)
    for now in (0, .2, .4):
        nav.step(replace(f, now=now))
    step = nav.step(replace(f, now=.5))  # 100 px of floor remain, but the portal is closer
    assert step.horizontal is None and "edge launch" in nav.reason


def test_launch_near_a_platform_end_is_reached_from_rest_in_short_steps():
    # Live: a walk braked by the marker 24 px before an end and slid off the platform.
    nav, f = setup()  # The launch at 150 has 50 px of floor past it.
    for now in (0, .2, .4):
        nav.step(replace(f, now=now, feet=(52, 400)))
    assert nav.step(replace(f, now=.5, feet=(52, 400))).horizontal == "right"
    for now in (.6, .8):
        assert nav.step(replace(f, now=now, feet=(110, 400))).release
        assert "Braking before an edge launch" in nav.reason
    step = nav.step(replace(f, now=.95, feet=(110, 400)))
    assert step.horizontal is None and [h.action for h in step.holds] == ["right"]
    assert step.holds[0].seconds == nav.pulse  # 40 px short: a full pulse
    for now in (1.0, 1.2):  # settle after each step
        assert nav.step(replace(f, now=now, feet=(124, 400))).release
    step = nav.step(replace(f, now=1.35, feet=(124, 400)))
    # Live: 0.06 s taps moved below the 16 px marker resolution and never arrived.
    assert [h.action for h in step.holds] == ["right"] and step.holds[0].seconds == nav.pulse
    for now in (1.4, 1.6):
        nav.step(replace(f, now=now, feet=(145, 400)))
    motion = nav.step(replace(f, now=1.75, feet=(145, 400)))
    assert [hold.action for hold in motion.holds] == ["right", "jump"]
    # Walking toward the launch away from the end needs no stop: overshooting stays on it.
    nav, f = setup()
    for now in (0, .2, .4):
        nav.step(replace(f, now=now, feet=(190, 400)))
    assert nav.step(replace(f, now=.5, feet=(190, 400))).horizontal == "left"


def _end_launch_profile():
    def flat(key, x0, x1, y):
        return {"id": key, "name": key, "start": {"x": x0, "y": y}, "end": {"x": x1, "y": y}}

    # Tree Dungeon fh315 (Level 8) and fh320 (Level 9 right), flattened.
    return {"id": "b" * 32, "revision": 1, "zones": [], "links": [],
            "boundary": {"x": 0, "y": 700, "width": 1200, "height": 600},
            "platforms": [flat("src", 600, 850, 1025), flat("dst", 794, 965, 972)],
            "ropes": [], "public_map": {"id": 1, "sha256": "c" * 64,
                                        "world": {"x": [1, 0], "y": [1, 0]}}}


def _approach(graph, start: float, step_px: float) -> float | None:
    """Drive the navigator with a coarse live model; the takeoff x, or None if it fell.

    Live (Tree Dungeon, 2026-11-02): one-pulse steps from rest moved 16-48 px, released
    walks ran on about 60 px, frames came every 0.17 s and the marker moved in 16 px steps.
    """
    nav = Navigator(graph, graph.plan("src", "dst"), 0)
    x, now, walking = float(start), 0.0, None
    for _ in range(400):
        if not 600 <= x <= 850:
            return None
        feet = (16 * round(x / 16), 1025.0)
        motion = nav.step(Feedback(now, graph.fingerprint, feet, "src", True))
        if any(hold.action == "jump" for hold in motion.holds):
            return x
        assert nav.stage in {"settle_origin", "approach"}, nav.reason
        sign = lambda key: 1 if key == "right" else -1  # noqa: E731
        if motion.horizontal:
            x += sign(motion.horizontal) * 137 * .17
            walking = motion.horizontal
        else:
            if walking:
                x += sign(walking) * 60
                walking = None
            for hold in motion.holds:
                if hold.action in {"left", "right"}:
                    x += sign(hold.action) * (step_px if hold.seconds >= nav.pulse else 5)
        now += .17
    raise AssertionError(f"no takeoff from {start}: {nav.reason}")


@pytest.mark.parametrize("step_px", [16, 32, 48])
def test_end_launches_are_reached_without_sliding_off_the_platform(step_px):
    from maplebot.moves import TAKEOFF_INSET_PX, generate

    profile = _end_launch_profile()
    graph = RouteMap.computed(profile)
    launch = graph.edges["m_src_dst"].launch[0]
    assert launch == 850 - TAKEOFF_INSET_PX
    for start in range(610, 846, 9):
        takeoff = _approach(graph, start, step_px)
        assert takeoff is not None, f"slid off from {start} with {step_px} px steps"
        assert abs(takeoff - launch) <= 16 + 8, (start, takeoff)
    # The same model reproduces batch 2: a launch 24 px from the end slides off.
    old = [m if m.id != "m_src_dst" else replace(
        m, trace=((826.0, 1025.0), (848.0, 932.0), (870.0, 972.0))) for m in generate(profile)]
    near = RouteMap.computed(profile, moves=old)
    if step_px == 48:
        assert any(_approach(near, start, step_px) is None for start in range(610, 846, 9))


def test_sliding_off_the_launch_end_onto_a_drops_target_completes_the_drop():
    # Live (Tree Dungeon batch 5): a step toward the proven fh315 -> fh308 drop launch slid
    # off fh315's end and landed on fh308, the drop's target, and stopped as a lost launch.
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    nav = Navigator(graph, graph.plan("ledge", "floor"), 0)
    f = Feedback(0, graph.fingerprint, (330, 300), "ledge", True)
    for now in (0, .2, .4):
        nav.step(replace(f, now=now))
    assert nav.stage == "approach"
    nav.step(replace(f, now=.6, feet=(200, 400), surface="floor"))
    assert nav.stage == "flight" and "Slid off" in nav.reason
    for now in (.8, 1.0, 1.2):
        motion = nav.step(replace(f, now=now, feet=(200, 400), surface="floor"))
    assert nav.stage == "arrived" and motion.release and nav.completed == 1
    # Sliding onto some other platform is still a lost launch.
    nav = Navigator(graph, graph.plan("ledge", "floor"), 0)
    for now in (0, .2, .4):
        nav.step(replace(f, now=now))
    nav.step(replace(f, now=.6, feet=(100, 200), surface="island"))
    assert nav.stage == "stopped"
