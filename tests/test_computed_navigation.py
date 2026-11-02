import json
import time

import pytest
from test_runtime import app as _app

from maplebot.decision import Action, Decision, State
from maplebot.geometry import Rect
from maplebot.move_proofs import MoveProofs
from maplebot.navigation import RouteMap, map_hash
from maplebot.navigation_executor import Feedback, Navigator
from maplebot.perception import Detection, Observation
from maplebot.rotation import Rotation, routable

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


def test_trusted_route_leaves_a_one_way_platform_over_proven_moves_only():
    graph = RouteMap.computed(imported(), {"m_ledge_floor"})
    assert routable(graph) == ["floor"]
    route = graph.plan("ledge", "floor", trusted_only=True)
    assert [e.id for e in route.edges] == ["m_ledge_floor"]
    with pytest.raises(ValueError, match="proven moves"):
        graph.plan("floor", "ledge", trusted_only=True)


def test_clear_one_way_platform_rotates_to_a_routable_platform(app):
    nav = app.navigation
    nav.graph = RouteMap.computed(imported(), {"m_ledge_floor"})
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (300, 340), "ledge", True)
    app.probed.update({"left", "right", "jump", "down"})
    app.mode, app.rotating, app.rotation = "live", True, Rotation(1)
    app.controller.enable()
    search = Decision(State.SEARCH, Action(), "Waiting for a fresh confident same-platform target")
    observation = Observation(Detection("player", Rect(500, 300, 40, 60), .95), [])
    now = time.perf_counter()
    assert app._rotate(search, observation, now) is None
    assert "moving to floor" in app._rotate(search, observation, now + 1)
    assert (nav.route.origin, nav.route.target) == ("ledge", "floor")


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
    edge = nav.graph.edges["m_floor_ledge"]
    shape = {"from": "floor", "to": "ledge", "kind": "jump",
             "trace": [list(point) for point in edge.trace]}
    assert nav.pending_proofs == [("a" * 32, fingerprint, "m_floor_ledge", shape)]
    assert nav.proofs.load("a" * 32, fingerprint) == set()
    app.controller.stop("Offline route complete", notify=False)
    nav.cancel("Offline route complete")
    assert not nav.pending_proofs
    assert nav.proofs.load("a" * 32, fingerprint) == {"m_floor_ledge"}
    assert nav.proofs.geometry("a" * 32, fingerprint) == {"m_floor_ledge": shape}
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


def test_refresh_reuses_generated_moves_until_the_map_changes(app, monkeypatch):
    import maplebot.navigation_runtime as runtime
    profile = imported()
    app.position = type("Position", (), {"profile": profile})()
    areas = app.areas
    app.areas = type("Areas", (), {"load": lambda self, area_id: {"profile": profile},
                                   "directory": areas.directory})()
    generated = []

    def generate(value):
        generated.append(value["revision"])
        return runtime_generate(value)

    runtime_generate = runtime.generate
    monkeypatch.setattr(runtime, "generate", generate)
    nav = app.navigation
    nav.refresh()
    nav.refresh()
    assert generated == [2]  # nav_go refreshes right before its frame-freshness check
    nav.failed.add("m_floor_ledge")
    nav.refresh()
    assert "m_floor_ledge" not in nav.graph.edges and generated == [2]
    profile["revision"] = 3
    nav.refresh()
    assert generated == [2, 3]


def test_proven_moves_keep_the_geometry_they_succeeded_with(tmp_path):
    graph = RouteMap.computed(imported())
    edge = graph.edges["m_ledge_floor"]
    shape = {"from": "ledge", "to": "floor", "kind": edge.kind,
             "trace": [[300.0, 340.0], [300.0, 400.0]]}
    proofs = MoveProofs(tmp_path)
    proofs.record("a" * 32, "m", "m_ledge_floor", shape)
    proofs.record("a" * 32, "m", "m_floor_ledge")  # legacy: no recorded geometry
    stored = MoveProofs(tmp_path).geometry("a" * 32, "m")
    assert stored == {"m_ledge_floor": shape}
    kept = RouteMap.computed(imported(), {"m_ledge_floor", "m_floor_ledge"},
                             proven_geometry=stored)
    assert kept.edges["m_ledge_floor"].trace == ((300.0, 340.0), (300.0, 400.0))
    # A proof without geometry proves nothing once geometry is tracked.
    assert kept.proven == {"m_ledge_floor"}
    # A proven move the generator no longer proposes is still available.
    gone = [m for m in __import__("maplebot.moves", fromlist=["generate"]).generate(imported())
            if m.id != "m_ledge_floor"]
    assert "m_ledge_floor" in RouteMap.computed(imported(), {"m_ledge_floor"}, moves=gone,
                                                proven_geometry=stored).edges
