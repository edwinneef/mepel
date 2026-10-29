import json

import pytest

from tools.navigation_check import readiness, run, targets


def status(**overrides):
    value = {"mode": "capture", "focused": True, "capture_only": False,
             "position": {"area_id": "a", "surface_id": "floor"},
             "navigation": {"stage": "idle", "reason": "", "blocker": None,
                            "map": {"proven_edges": 0, "nodes": [
                                {"id": "floor", "kind": "platform", "excluded": False},
                                {"id": "ledge", "kind": "platform", "excluded": False},
                                {"id": "top", "kind": "platform", "excluded": False},
                                {"id": "far", "kind": "platform", "excluded": True},
                                {"id": "rope", "kind": "rope", "excluded": False}]}},
             "stop": None}
    value.update(overrides)
    return value


class Api:
    """Arrives at each target, except the ones listed in `fail`."""

    def __init__(self, fail=()):
        self.value, self.fail, self.calls, self.moving = status(), set(fail), [], 0

    def status(self):
        if self.moving:
            self.moving -= 1
            if not self.moving:
                target = self.calls[-1][1]["target"]
                nav = self.value["navigation"]
                if target in self.fail:
                    self.value.update(mode="capture", stop={"message": "Navigation fused "
                                      "feedback is stale or uncertain", "clip_path": "c"})
                    nav.update(stage="stopped", reason="Navigation fused feedback is stale")
                else:
                    self.value["mode"] = "capture"
                    self.value["position"]["surface_id"] = target
                    nav["stage"] = "arrived"
                    nav["map"]["proven_edges"] += 1
        return json.loads(json.dumps(self.value))

    def command(self, name, payload=None):
        self.calls.append((name, payload or {}))
        if name == "nav_go":
            assert payload["opt_in"] is True
            self.value["mode"], self.moving = "navigation", 3
        return {}


def test_readiness_and_targets_skip_ropes_unreachable_and_current():
    assert readiness(status()) is None
    assert readiness(status(focused=False)) == "Focus MapleStory"
    assert "Capture-only" in readiness(status(capture_only=True))
    assert targets(status()) == ["ledge", "top"]


def test_run_visits_each_target_and_records_proofs(tmp_path):
    api = Api()
    result = run(api, tmp_path / "out", limit=5, sleep=lambda s: None)
    assert [r["outcome"] for r in result["routes"]] == ["arrived", "arrived"]
    assert result["failure"] is None and result["proven_after"] == 2
    assert api.calls[-1][0] == "stop"
    saved = json.loads((tmp_path / "out" / "result.json").read_text())
    assert saved["arrived"] == 2


def test_run_stops_the_batch_at_the_first_failure(tmp_path):
    api = Api(fail={"ledge"})
    result = run(api, tmp_path / "out", limit=5, sleep=lambda s: None)
    assert [r["target"] for r in result["routes"]] == ["ledge"]
    assert result["failure"].startswith("Navigation fused feedback")
    assert result["routes"][0]["after"]["stop"]["clip_path"] == "c"
    assert [c for c, _ in api.calls].count("nav_go") == 1


def test_run_refuses_when_not_ready_and_waits_for_a_known_platform(tmp_path):
    api = Api()
    api.value["focused"] = False
    with pytest.raises(RuntimeError, match="Focus"):
        run(api, tmp_path / "a", limit=1)
    api.value["focused"] = True
    api.value["position"]["surface_id"] = None
    ticks = iter(range(100))
    result = run(api, tmp_path / "b", limit=1, clock=lambda: next(ticks), sleep=lambda s: None)
    assert result["failure"] == "not ready: platform unknown"


def test_all_routes_covers_every_ordered_platform_pair():
    from tools.navigation_check import all_routes
    route = ["floor", *all_routes(status())]
    pairs = set(zip(route, route[1:], strict=False))
    nodes = ("floor", "ledge", "top")
    assert {(a, b) for a in nodes for b in nodes if a != b} <= pairs
    assert len(route) == len(nodes) * (len(nodes) - 1) + 1
    assert not any(a == b for a, b in pairs)
