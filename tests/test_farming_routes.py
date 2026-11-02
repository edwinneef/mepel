import copy

import pytest
from test_navigation import fixture

from maplebot.farming_routes import FarmingRouteStore, compile_route, draft
from maplebot.navigation import RouteMap
from maplebot.rotation import CircuitRotation


def example():
    profile, evidence = fixture()
    return {"version": 1, "revision": 0, "id": "circuit", "name": "Two levels",
            "area_id": profile["id"], "map_hash": evidence["map_hash"],
            "stops": ["floor", "ledge"], "loop": True}


def test_store_roundtrip_conflict_and_isolation(tmp_path):
    untouched = tmp_path / "map.json"
    untouched.write_text("preserve")
    store = FarmingRouteStore(tmp_path)
    saved = store.save(example())
    assert saved["revision"] == 1
    assert store.load("circuit") == saved
    second = example() | {"id": "second"}
    store.save(second)
    assert len(store.list(saved["area_id"])["routes"]) == 2
    with pytest.raises(ValueError, match="elsewhere"):
        store.save(example())
    assert untouched.read_text() == "preserve"
    assert store.save(saved)["revision"] == 2


@pytest.mark.parametrize("change", [
    {"id": "../map"}, {"revision": True}, {"revision": -1}, {"version": 9},
    {"stops": ["floor", {}]}, {"stops": ["floor", "floor"]}, {"loop": "yes"},
    {"stops": ["floor", "ledge", "floor"]}, {"teleport": True},
    {"name": ""}, {"name": "x" * 64001},
])
def test_malformed_imports_cannot_be_saved(change):
    with pytest.raises(ValueError):
        draft(example() | change)


def test_compile_checks_return_leg_actual_graph_and_stale_map():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    value = example()
    assert compile_route(value, graph)["valid"]
    assert len(compile_route(value, graph)["legs"]) == 2
    graph.edges.pop("back")
    assert not compile_route(value, graph)["valid"]
    assert any("ledge to floor" in error for error in compile_route(value, graph)["errors"])
    assert not compile_route(value | {"map_hash": "0" * 64}, graph)["valid"]
    assert not compile_route(value | {"stops": ["floor", "absent"]}, graph)["valid"]


def test_compile_transit_is_not_a_farming_stop():
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    route = example()
    before = copy.deepcopy(route)
    assert compile_route(route, graph)["legs"][0]["edges"][0]["kind"] == "jump"
    assert route == before


def test_circuit_three_stops_arrival_clear_loop_and_miss():
    rotation = CircuitRotation(1, example() | {"stops": ["a", "b", "c"]})
    def step(now, surface, searching=True):
        return rotation.step(now, searching=searching, surface=surface,
                             platforms=["a", "b", "c", "transit"], visible={"c": 99})
    assert step(0, "a") is None
    assert step(1, "a") == "b"
    assert step(2, "transit") == "b"  # Miss never advances to c.
    assert rotation.index == 1
    assert step(3, None) is None
    rotation.arrived("b", 4)
    assert step(4, "b", False) is None
    assert step(5, "b") is None
    assert step(6, "b") == "c"
    assert step(7, "c") is None
    assert step(8, "c") == "a"
    assert rotation.index == 0


def test_finite_circuit_finishes_only_after_final_clear():
    rotation = CircuitRotation(1, example() | {"loop": False})
    args = {"platforms": ["floor", "ledge"], "visible": {}, "searching": True}
    assert rotation.step(0, surface="floor", **args) is None
    assert rotation.step(1, surface="floor", **args) == "ledge"
    assert not rotation.complete
    rotation.arrived("ledge", 2)
    assert rotation.step(2, surface="ledge", **args) is None
    assert rotation.step(3, surface="ledge", **args) is None
    assert rotation.complete


def test_excluded_connection_cannot_appear_in_compiled_or_runtime_graph():
    from maplebot.farming_routes import restrict_graph
    profile, evidence = fixture()
    graph = RouteMap(profile, evidence)
    value = example() | {"disabled_edges": ["up"]}
    assert not compile_route(value, graph)["valid"]
    restricted = restrict_graph(value, graph)
    assert "up" not in restricted.edges
    assert "up" in graph.edges
    with pytest.raises(ValueError):
        restricted.plan("floor", "ledge", trusted_only=True)
