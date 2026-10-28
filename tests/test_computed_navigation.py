import json

import pytest
from test_runtime import app as _app

from maplebot.move_proofs import MoveProofs
from maplebot.navigation import RouteMap, map_hash
from maplebot.navigation_executor import Navigator
from maplebot.rotation import routable

app = _app


def imported():
    def flat(key, x0, x1, y):
        return {"id": key, "name": key, "start": {"x": x0, "y": y}, "end": {"x": x1, "y": y}}

    return {"id": "a" * 32, "revision": 2, "zones": [], "links": [],
            "boundary": {"x": 0, "y": 100, "width": 700, "height": 400},
            "platforms": [flat("floor", 50, 550, 400), flat("ledge", 250, 400, 340)],
            "ropes": [], "public_map": {"id": 1, "sha256": "c" * 64,
                                        "world": {"x": [1, 0], "y": [1, 0]}}}


def test_computed_moves_route_under_supervision_and_rotation_needs_proofs():
    graph = RouteMap.computed(imported())
    route = graph.plan("floor", "ledge")
    assert [(e.source, e.target, e.kind) for e in route.edges] == [("floor", "ledge", "jump")]
    assert graph.fingerprint == map_hash(imported())  # computed links never change the map
    assert routable(graph) == ["floor"]  # nothing proven: rotation stays home
    with pytest.raises(ValueError, match="proven moves"):
        graph.plan("floor", "ledge", trusted_only=True)
    both = {e.id for e in graph.edges.values()}
    proven = RouteMap.computed(imported(), both)
    assert routable(proven) == ["floor", "ledge"]
    assert proven.plan("floor", "ledge", trusted_only=True).edges[0].evidence == "proven"
    assert "m_floor_ledge" not in RouteMap.computed(imported(), failed={"m_floor_ledge"}).edges


def test_proofs_survive_restart_and_reset_when_the_map_changes(tmp_path):
    proofs = MoveProofs(tmp_path)
    proofs.record("a" * 32, "old", "m_floor_ledge")
    assert MoveProofs(tmp_path).load("a" * 32, "old") == {"m_floor_ledge"}
    assert MoveProofs(tmp_path).load("a" * 32, "new") == set()
    proofs.record("a" * 32, "new", "m_ledge_floor")
    saved = json.loads((tmp_path / "proofs" / f"{'a' * 32}.json").read_text("utf-8"))
    assert saved["map_hash"] == "new" and list(saved["moves"]) == ["m_ledge_floor"]
    with pytest.raises(ValueError, match="area ID"):
        proofs.load("../x", "new")


def test_runtime_proves_settled_moves_and_switches_off_failed_ones(app):
    nav = app.navigation
    nav.graph = RouteMap.computed(imported())
    route = nav.graph.plan("floor", "ledge")
    nav.agent = Navigator(nav.graph, route, 1.0)
    nav.counted = 0
    nav.agent.completed, nav.agent.index = 1, 1  # the navigator settled on the ledge
    nav._learn()
    fingerprint = nav.graph.fingerprint
    assert nav.proofs.load("a" * 32, fingerprint) == {"m_floor_ledge"}
    assert "m_floor_ledge" in nav.graph.proven
    back = nav.graph.plan("ledge", "floor")
    nav.agent = Navigator(nav.graph, back, 2.0)
    nav.counted = 0
    nav.agent.stop("Movement departed the recorded corridor")
    nav._learn()
    assert nav.failed == {back.edges[0].id}
    nav.agent = Navigator(nav.graph, back, 3.0)
    nav.agent.stop("Fresh fused position, map revision or focus lost")
    nav.failed.clear()
    nav._learn()
    assert nav.failed == set()  # a lost reading is not the move's fault


def test_a_map_without_public_data_must_be_imported_before_navigation(app):
    profile = {key: value for key, value in imported().items() if key != "public_map"}
    app.position = type("Position", (), {"profile": profile})()
    app.areas = type("Areas", (), {"load": lambda self, area_id: {"profile": profile}})()
    with pytest.raises(ValueError, match="Import this map first: maplebot import-map"):
        app.navigation.refresh()
