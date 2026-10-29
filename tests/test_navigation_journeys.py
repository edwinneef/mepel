import json
from pathlib import Path

import pytest

from maplebot.meowdb import load_source
from maplebot.navigation import RouteMap
from maplebot.public_map import layout
from tools.navigation_check import all_routes
from tools.navigation_journeys import expand


def graph():
    source, _ = load_source(Path(__file__).parent / "fixtures" / "meowdb-42.json")
    profile = {"id": "a" * 32, "revision": 1, "links": [], "public_map": {"id": 42},
               **layout(source, {"x": (1, 0), "y": (1, 0)}, (16, 16))}
    return RouteMap.computed(profile)


def test_all_classic_platform_pairs_have_bounded_legs():
    g = graph()
    status = {"position": {"surface_id": g.home}, "navigation": {"map": g.snapshot()}}
    result = expand(g.profile, g.snapshot(), g.home, all_routes(status))
    assert len({(j["origin"], j["target"]) for j in result["journeys"]}) == 342
    assert any(len(j["legs"]) > 1 for j in result["journeys"])
    assert all(1 <= n <= 8 for j in result["journeys"] for n in j["edge_counts"])
    assert all(j["legs"][-1] == j["target"] for j in result["journeys"])
    assert all(t in {p["id"] for p in g.profile["platforms"]} for t in result["targets"])


def test_changed_map_or_disabled_edges_cannot_be_bypassed():
    g = graph()
    s = g.snapshot()
    target = next(p["id"] for p in g.profile["platforms"] if p["id"] != g.home)
    with pytest.raises(ValueError, match="differs"):
        expand(g.profile, {**s, "map_hash": "changed"}, g.home, [target])
    s["edges"] = [e for e in s["edges"] if e["from"] != g.home]
    with pytest.raises(ValueError, match="reachable|safe bounded"):
        expand(g.profile, s, g.home, [target])


def test_planner_prefers_nearby_transitions_over_a_cross_map_approach():
    from tools.navigation_replay import simulate

    g = graph()
    route = g.plan("fh193", "fh97")
    assert len(route.edges) == 6  # Four edges previously hid a >1000px approach.
    assert simulate(g, route, fps=3)["stage"] == "arrived"


def test_batch_stops_before_input_if_pinned_map_changes(tmp_path):
    from test_navigation_check import Api

    from tools.navigation_check import run

    api = Api()
    result = run(api, tmp_path / "out", limit=2, chosen=["ledge", "top"],
                 coverage={"map_hash": "original"}, sleep=lambda _: None)
    assert result["failure"] == "Map changed during coverage batch"
    assert not any(name == "nav_go" for name, _ in api.calls)
    saved = json.loads((tmp_path / "out/result.json").read_text())
    assert saved["coverage"]["map_hash"] == "original"
