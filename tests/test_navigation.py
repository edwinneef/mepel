import copy

import pytest

from maplebot.navigation import RouteMap, map_hash


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
