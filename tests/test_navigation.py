import copy

import pytest

from maplebot.navigation import (
    Edge,
    Route,
    RouteMap,
    map_hash,
    pose_gaps,
    problems,
    required_poses,
    surface_y,
)


def fixture():
    profile = {"id": "a" * 32, "revision": 4,
               "boundary": {"x": 0, "y": 0, "width": 600, "height": 500}, "zones": [],
               "platforms": [{"id": key, "name": key, "start": {"x": x, "y": y},
                              "end": {"x": x + 150, "y": y}}
                             for key, x, y in (("floor", 50, 400), ("ledge", 250, 300),
                                              ("island", 50, 200))],
               "ropes": [], "links": [
                   {"id": "up", "from": "floor", "to": "ledge", "kind": "jump"},
                   {"id": "back", "from": "ledge", "to": "floor", "kind": "drop"}]}
    evidence = {"area_id": profile["id"], "revision": 4, "map_hash": map_hash(profile),
                "edges": {key: {"from": a, "to": b, "kind": kind, "source": "session",
                                "missing_checks": 0, "max_gap": .2, "trace": trace}
                          for key, a, b, kind, trace in (
                              ("up", "floor", "ledge", "jump",
                               [[150, 400], [220, 260], [280, 300]]),
                              ("back", "ledge", "floor", "drop", [[280, 300], [150, 400]]))}}
    return profile, evidence


def test_routes_use_only_evidenced_round_trip_surfaces():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    assert [e.id for e in graph.plan("floor", "ledge").edges] == ["up"]
    assert graph.plan("floor", "floor").edges == ()
    with pytest.raises(ValueError, match="round-trip"):
        graph.plan("floor", "island")


def test_plan_checks_approach_from_actual_feet_before_sending_input():
    profile, evidence = fixture()
    profile['zones'] = [{'id': 'portal', 'kind': 'portal',
                         'rect': {'x': 85, 'y': 390, 'width': 5, 'height': 10}}]
    evidence['map_hash'] = map_hash(profile)
    graph = RouteMap(profile, evidence)
    assert graph.plan('floor', 'ledge', origin_feet=(150, 400)).edges
    with pytest.raises(ValueError, match='safe route'):
        graph.plan('floor', 'ledge', origin_feet=(40, 400))


@pytest.mark.parametrize("kind", ["avoid", "portal"])
def test_full_movement_trace_respects_zones_and_disables_stranded_destinations(kind):
    profile, evidence = fixture()
    profile["zones"] = [{"id": "blocked", "kind": kind,
                          "rect": {"x": 215, "y": 230, "width": 8, "height": 8}}]
    evidence["map_hash"] = map_hash(profile)
    graph = RouteMap(profile, evidence)
    assert "zone" in graph.disabled["up"]
    with pytest.raises(ValueError):
        graph.plan("floor", "ledge")


def test_revision_and_zone_edits_invalidate_old_evidence_and_routes():
    profile, evidence = fixture()
    route = RouteMap(profile, evidence).plan("floor", "ledge")
    changed = copy.deepcopy(profile)
    changed["revision"] += 1
    with pytest.raises(ValueError, match="revision"):
        RouteMap(changed, evidence)
    evidence["revision"], evidence["map_hash"] = changed["revision"], map_hash(changed)
    with pytest.raises(ValueError, match="Map changed"):
        RouteMap(changed, evidence).verify(route)


def test_missing_anchor_or_lost_observation_disables_edge_not_just_warning():
    profile, evidence = fixture()
    evidence["edges"]["back"]["missing_checks"] = 1
    graph = RouteMap(profile, evidence)
    assert "ledge" in graph.excluded
    with pytest.raises(ValueError):
        graph.plan("floor", "ledge")
    evidence["edges"]["back"]["missing_checks"] = 0
    evidence["edges"]["up"]["trace"][0] = [10, 400]
    graph = RouteMap(profile, evidence)
    assert "anchors" in graph.disabled["up"]


def test_boundary_player_footprint_is_checked_between_endpoints():
    profile, evidence = fixture()
    evidence["edges"]["up"]["trace"][1] = [590, 260]
    assert "boundary" in RouteMap(profile, evidence).disabled["up"]


def test_problems_list_unreachable_and_stranded_surfaces():
    flat = [{"id": key, "start": {"x": 0, "y": y}, "end": {"x": width, "y": y}}
            for key, y, width in (("floor", 600, 900), ("ledge", 400, 200), ("island", 300, 100))]
    links = [{"id": "l1", "from": "floor", "to": "ledge", "kind": "jump"}]
    assert problems(flat, [], links) == {
        "home": "floor", "unreachable": ["island"], "stranded": ["ledge"],
    }


def test_home_is_the_widest_floor_despite_sub_pixel_height_noise():
    floors = [{"id": key, "start": {"x": x, "y": y}, "end": {"x": x + width, "y": y}}
              for key, x, y, width in (("main", 298, 1510.2, 1343), ("side", 1934, 1510.3, 294),
                                       ("ledge", 0, 1490, 2000))]
    assert problems(floors, [], [])["home"] == "main"


def test_surface_height_follows_bends_and_straight_ends():
    bent = {"start": {"x": 0, "y": 640}, "end": {"x": 200, "y": 600},
            "points": [{"x": 0, "y": 640}, {"x": 40, "y": 600}, {"x": 200, "y": 600}]}
    assert surface_y(bent, 20) == 620 and surface_y(bent, 120) == 600
    straight = {"start": {"x": 0, "y": 600}, "end": {"x": 100, "y": 500}}
    assert surface_y(straight, 50) == 550


def test_anchors_on_a_sloped_platform_end_follow_its_bends():
    profile, evidence = fixture()
    floor = profile["platforms"][0]
    floor["points"] = [{"x": 50, "y": 440}, {"x": 90, "y": 400}, {"x": 200, "y": 400}]
    evidence["map_hash"] = map_hash(profile)
    graph = RouteMap(profile, evidence)
    assert graph.on_surface("floor", (60, 430)) and graph.on_surface("floor", (150, 400))
    assert not graph.on_surface("floor", (60, 400))


def test_routes_require_recognition_in_each_pose_they_show():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    up, down = graph.plan("floor", "ledge"), graph.plan("ledge", "floor")
    assert required_poses(up, set()) == {"walk/left", "walk/right", "air/right"}
    assert required_poses(down, set()) == {"walk/left", "walk/right", "air/any"}
    verified = {"walk/left", "walk/right", "air/left"}
    assert pose_gaps(required_poses(up, set()), verified) == ["air/right"]
    assert pose_gaps(required_poses(down, set()), verified) == []
    assert pose_gaps({"air/any", "climb/back"}, {"walk/left"}) == ["air/any", "climb/back"]


def test_jumping_onto_a_rope_needs_the_sideways_jump_and_the_climb():
    def climb(launch, landing, source="floor"):
        edge = Edge("c", source, "rope", "climb", launch, landing, (launch, landing), "session")
        return Route("a", 1, "f", source, "rope", (edge,))

    walking = {"walk/left", "walk/right"}
    assert required_poses(climb((100, 400), (130, 340)), set()) == walking | {
        "climb/back", "air/right"}
    assert required_poses(climb((100, 400), (102, 340)), set()) == walking | {
        "climb/back", "air/any"}
    assert required_poses(climb((100, 300), (100, 200), "rope"), {"rope"}) == walking | {
        "climb/back"}
