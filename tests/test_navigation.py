import copy
import json

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


def teaching_evidence(tmp_path, *, older=True, stretch=1.0, checks=0.0, log_offset=0.0):
    """Teach a small map, save its log (times scaled by stretch) and build its evidence.

    checks adds a readable position check at that interval between kept samples;
    log_offset leaves the check log on another clock.
    """
    from dataclasses import asdict

    from test_map_teacher import fix, tag

    from maplebot.localization import MinimapTransform
    from maplebot.map_teacher import MapTeacher
    from maplebot.navigation_evidence import build_evidence

    def walk(path, start):
        teacher = MapTeacher(MinimapTransform(16, 0, 16, 0))
        for index, (x, y, feet) in enumerate(path):
            teacher.add(fix(x, y), tag(feet), (0, 0), start + index * 0.2)
        return teacher

    def write_log(name, teacher):
        rows = [{"t": s.t * stretch, "kind": s.kind, "sample_dot": list(s.dot)}
                for s in teacher.samples]
        rows += [{**row, "t": row["t"] * stretch + log_offset} for row in teacher.log]
        if checks:
            first, last = rows[0]["t"], rows[-1]["t"]
            rows += [{"t": first + k * checks, "dot": [0, 0], "reason": "Player marker"}
                     for k in range(1, int((last - first) / checks))]
        (tmp_path / "teaching" / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), "utf-8")

    path = [(x, 40, 600) for x in range(10, 31)]
    path += [(30, y, 600 - 16 * (40 - y)) for y in range(39, 31, -1)]
    path += [(x, 32, 472) for x in range(30, 46)]
    path += [(45 + step, 32 + 2 * step, 472 + 32 * step) for step in range(1, 5)]
    path += [(x, 40, 600) for x in range(53, 61)]
    new = walk(path, 100)
    (tmp_path / "teaching").mkdir(parents=True)
    (tmp_path / "drafts").mkdir()
    if older:
        write_log("a-1.jsonl", walk(path[:30], 0))
    write_log("a-2.jsonl", new)
    (tmp_path / "drafts" / "a.json").write_text(
        json.dumps({"teacher": new.checkpoint()}), "utf-8")
    profile = {"id": "a", "revision": 1, "zones": [], **new.geometry(),
               "minimap_calibration": {"transform": asdict(new.transform)}}
    return profile, build_evidence(profile, tmp_path)["edges"]


def test_evidence_matches_a_newer_session_log_beside_older_logs(tmp_path):
    profile, edges = teaching_evidence(tmp_path)
    assert {(e["from"], e["to"]) for e in edges.values()} == {
        (link["from"], link["to"]) for link in profile["links"]}
    assert {e["source"] for e in edges.values()} == {"a-2.jsonl"}


def test_moves_without_aligned_position_checks_prove_nothing(tmp_path):
    _, aligned = teaching_evidence(tmp_path / "aligned", older=False)
    _, shifted = teaching_evidence(tmp_path / "shifted", older=False, log_offset=-500)
    assert aligned and shifted == {}


def test_sparse_samples_are_continuous_only_when_checks_fill_the_gaps(tmp_path):
    _, sparse = teaching_evidence(tmp_path / "sparse", older=False, stretch=6)
    _, checked = teaching_evidence(tmp_path / "checked", older=False, stretch=6, checks=.5)
    assert sparse.keys() == checked.keys() and sparse
    assert all(edge["max_gap"] > 1 for edge in sparse.values())
    assert all(edge["max_gap"] <= .5 + 1e-9 and edge["missing_checks"] == 0
               for edge in checked.values())


def test_anchors_on_a_sloped_platform_end_follow_its_bends():
    profile, evidence = fixture()
    floor = profile["platforms"][0]
    floor["points"] = [{"x": 50, "y": 440}, {"x": 90, "y": 400}, {"x": 200, "y": 400}]
    evidence["map_hash"] = map_hash(profile)
    graph = RouteMap(profile, evidence)
    assert graph.on_surface("floor", (60, 430)) and graph.on_surface("floor", (150, 400))
    assert not graph.on_surface("floor", (60, 400))
