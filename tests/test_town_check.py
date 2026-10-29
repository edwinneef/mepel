import copy
import json

import pytest

from maplebot.navigation import map_hash
from tools import town_check as town


@pytest.fixture
def profile():
    def flat(key, x0, x1, y):
        return {"id": key, "name": key, "start": {"x": x0, "y": y},
                "end": {"x": x1, "y": y}}
    return {"id": "a" * 32, "revision": 1, "zones": [], "links": [],
            "boundary": {"x": 2800, "y": 200, "width": 1000, "height": 600},
            "platforms": [flat("floor", 2800, 3368, 574), flat("ledge", 3200, 3510, 334)],
            "ropes": [{"id": "ladder", "name": "Ladder to ledge", "start": {"x": 3291, "y": 334},
                       "end": {"x": 3291, "y": 574}}],
            "public_map": {"id": town.TOWN_ID, "world": {"x": [1, 0], "y": [1, 0]}}}


def status(profile):
    return {"session_id": "session", "mode": "capture", "focused": True, "capture_only": False,
            "frame": {"available": True, "age_ms": 10},
            "player": {"confidence": .99, "tracked": False,
                       "box": {"y": 510, "height": 64}},
            "position": {"area_id": profile["id"], "kind": "platform", "surface_id": "floor",
                         "feet": [3190, 574], "stale": False, "marker": [1, 2],
                         "canvas": {"x": 0}, "calibrated": True},
            "navigation": {"map": {"area_id": profile["id"], "revision": 1,
                                   "map_hash": map_hash(profile)}, "stage": "idle"},
            "readiness": {f"probe:{action}": {"ready": True}
                          for action in ("left", "right", "jump")}}


@pytest.mark.parametrize(("field", "value", "message"), [
    ("focused", False, "not focused"), ("session_id", "other", "session changed"),
    ("player", None, "not freshly"), ("player", {"confidence": .99, "tracked": True}, "freshly"),
    ("frame", {"available": True, "age_ms": 99999}, "stale"),
    ("frame", {"available": True, "age_ms": float("nan")}, "stale"),
    ("position", {"area_id": "other"}, "Wrong tracked map"),
    ("navigation", {"map": {"revision": 99}}, "revision/hash"),
])
def test_preflight_fails_closed(profile, field, value, message):
    sample = status(profile)
    sample[field] = value
    assert message in town.blocker(sample, profile, session="session")


@pytest.mark.parametrize("change", [
    {"stale": True}, {"provisional": True}, {"held": True}, {"marker": None},
    {"calibrated": False}, {"canvas": None}, {"kind": "unknown", "surface_id": None},
])
def test_missing_map_contact_or_minimap_never_uses_saved_labels(profile, change):
    sample = status(profile)
    sample["position"].update(change)
    assert town.blocker(sample, profile)


class Api:
    def __init__(self, profile, fail=False):
        self.value, self.calls, self.pending = status(profile), [], []
        self.fail = fail

    def status(self):
        if self.pending:
            self.value = self.pending.pop(0)
        return copy.deepcopy(self.value)

    def command(self, name, payload=None):
        self.calls.append((name, payload))
        if name == "probe":
            action = payload["action"]
            wait, moving, settled = (copy.deepcopy(self.value) for _ in range(3))
            wait["mode"], moving["mode"] = "probe_wait", "probe_queued"
            settled["mode"] = "probe_confirm"
            if action == "jump":
                moving["player"]["box"]["y"] -= 30
            else:
                settled["position"]["feet"][0] += -10 if action == "left" else 10
            if self.fail:
                moving["focused"] = False
            self.pending = [wait, moving, settled]
        if name == "nav_go":
            wait, moving, arrived = (copy.deepcopy(self.value) for _ in range(3))
            wait["mode"], moving["mode"] = "navigation_wait", "navigation"
            arrived["mode"] = "capture"
            arrived["navigation"]["stage"] = "arrived"
            arrived["position"]["surface_id"] = payload["target"]
            arrived["position"]["kind"] = "rope" if payload["target"] == "ladder" else "platform"
            self.pending = [wait, moving, arrived]
        if name in {"confirm_probe", "stop"}:
            self.value["mode"] = "capture"
            self.pending.clear()
        return {"id": 1, "generation": 2, "path": "saved-clip", "ok": True,
                "confirmed": name == "confirm_probe"}


@pytest.fixture
def run_check(monkeypatch):
    monkeypatch.setattr(town, "code_revision", lambda *_: "unchanged-code")
    ticks = [0.0]

    def sleep(seconds):
        ticks[0] += seconds

    def run(api, profile, output):
        return town.run(api, profile, output, clock=lambda: ticks[0], sleep=sleep)
    return run


def test_real_planner_requires_ladder_and_return_path(profile):
    assert town.ladder_target(profile, status(profile)) == "ledge"
    profile["ropes"] = []
    with pytest.raises(ValueError, match="No ladder round trip"):
        town.ladder_target(profile, status(profile))


def test_town_batch_records_walk_jump_and_ladder_up_and_down(profile, run_check, tmp_path):
    api = Api(profile)
    result = run_check(api, profile, tmp_path / "success")
    assert result["failure"] is None
    assert len(result["steps"]) == 6 and all(s["passed"] for s in result["steps"])
    assert all(s["clip"] == "saved-clip" for s in result["steps"])
    assert result["after"]["mode"] == "capture"
    assert api.calls[-1][0] == "stop"
    assert [p["target"] for n, p in api.calls if n == "nav_go"] == ["ledge", "ladder", "floor"]
    assert json.loads((tmp_path / "success/result.json").read_text())["movement_requested"]


def test_wrong_map_refusal_writes_evidence_without_any_command(profile, run_check, tmp_path):
    api = Api(profile)
    api.value["position"]["area_id"] = "other"
    result = run_check(api, profile, tmp_path / "refused")
    assert "Wrong tracked map" in result["failure"]
    assert not api.calls and not result["movement_requested"]
    assert (tmp_path / "refused/result.json").exists()


def test_first_failure_stops_and_unchanged_failure_cannot_repeat(profile, run_check, tmp_path):
    api = Api(profile, fail=True)
    result = run_check(api, profile, tmp_path / "failed")
    assert "not focused" in result["failure"]
    assert len(result["steps"]) == 1 and result["steps"][0]["clip"]
    assert api.calls[-1][0] == "stop"
    api = Api(profile)
    result = run_check(api, profile, tmp_path / "repeat")
    assert "Unchanged failed movement" in result["failure"]
    assert not api.calls


def test_empty_or_current_route_cannot_pass(profile):
    api = Api(profile)
    check = town.Check(api, profile)
    for target in (None, "floor"):
        with pytest.raises(RuntimeError, match="No route target|no-op"):
            check.route(target)
    assert not api.calls


def test_png_pair_wait_never_sends_input_or_accepts_a_stale_position(profile):
    api = Api(profile)
    stale = status(profile)
    stale["position"].update(stale=True, marker=None)
    api.pending = [stale, status(profile)]
    check = town.Check(api, profile, sleep=lambda _: None)
    assert check.status()["position"]["stale"] is False
    assert not api.calls


def test_png_pair_wait_still_refuses_focus_loss_and_persistent_staleness(profile):
    api = Api(profile)
    stale = status(profile)
    stale["position"].update(stale=True, marker=None)
    lost = status(profile)
    lost["focused"] = False
    api.pending = [stale, lost]
    check = town.Check(api, profile, sleep=lambda _: None)
    with pytest.raises(RuntimeError, match="not focused"):
        check.status()
    api.value = stale
    ticks = [0.0]
    check = town.Check(api, profile, clock=lambda: ticks[0],
                       sleep=lambda seconds: ticks.__setitem__(0, ticks[0] + seconds))
    with pytest.raises(RuntimeError, match="stale"):
        check.status()
    assert ticks[0] <= .28 and not api.calls


@pytest.mark.parametrize("change", ["focus", "map", "frame"])
def test_route_loss_stops_and_retains_failure_clip(profile, change):
    api = Api(profile)
    command = api.command

    def disrupt(name, payload=None):
        result = command(name, payload)
        if name == "nav_go":
            if change == "focus":
                api.pending[1]["focused"] = False
            elif change == "map":
                api.pending[1]["position"]["area_id"] = "other"
            else:
                api.pending[1]["frame"]["age_ms"] = 99999
        return result
    api.command = disrupt
    check = town.Check(api, profile, sleep=lambda _: None)
    with pytest.raises(RuntimeError):
        check.route("ledge")
    assert not check.rows[0]["passed"] and check.rows[0]["clip"] == "saved-clip"
    assert api.calls[-1][0] == "stop"


def test_rejected_confirmation_cannot_count_as_success(profile, run_check, tmp_path):
    api = Api(profile)
    command = api.command

    def refuse(name, payload=None):
        result = command(name, payload)
        if name == "confirm_probe":
            result["confirmed"] = False
        return result
    api.command = refuse
    result = run_check(api, profile, tmp_path / "confirmation-refused")
    assert "did not accept probe confirmation" in result["failure"]
    assert len(result["steps"]) == 1 and not result["steps"][0]["passed"]


def test_probe_rejection_still_clips_and_stops(profile, run_check, tmp_path):
    api = Api(profile)
    command = api.command

    def reject(name, payload=None):
        if name == "probe":
            raise RuntimeError("engine gate rejected probe")
        return command(name, payload)
    api.command = reject
    result = run_check(api, profile, tmp_path / "rejected")
    assert "engine gate" in result["failure"]
    assert result["movement_requested"]  # Request attempted; no accepted movement is assumed.
    assert api.calls[-1][0] == "stop"


def test_profile_selection_never_falls_back_to_another_map(profile, tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        town.profile_for_town(tmp_path)
    (tmp_path / "park.json").write_text(json.dumps(profile))
    assert town.profile_for_town(tmp_path) == profile
    (tmp_path / "park-copy.json").write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="exactly one"):
        town.profile_for_town(tmp_path)
