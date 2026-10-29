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


@pytest.mark.parametrize(("threshold", "confidence", "accepted"), [
    (.85, .875421, True), (.90, .875421, False), (.85, .849, False),
])
def test_player_recognition_uses_engine_threshold(profile, threshold, confidence, accepted):
    sample = status(profile)
    sample["player_threshold"] = threshold
    sample["player"]["confidence"] = confidence
    assert (town.blocker(sample, profile) is None) is accepted


@pytest.mark.parametrize("threshold", [float("nan"), .49, 1.01, True, "0.85"])
def test_invalid_player_threshold_refuses_movement(profile, threshold):
    sample = status(profile)
    sample["player_threshold"] = threshold
    assert "threshold is invalid" in town.blocker(sample, profile)


@pytest.mark.parametrize("change", [None, "focus", "map", "stale", "unsuspended", "timeout"])
def test_route_may_observe_engine_recovery_but_never_relaxes_other_gates(profile, change):
    sample = status(profile)
    sample["mode"] = "navigation"
    sample["player"]["tracked"] = True
    sample["navigation"]["recovery"] = {
        "active": True, "input_suspended": True, "remaining_seconds": 1.5,
        "marker_fresh": True, "map_hash": map_hash(profile)}
    if change == "focus":
        sample["focused"] = False
    elif change == "map":
        sample["position"]["area_id"] = "other"
    elif change == "stale":
        sample["frame"]["age_ms"] = 99999
    elif change == "unsuspended":
        sample["navigation"]["recovery"]["input_suspended"] = False
    elif change == "timeout":
        sample["navigation"]["recovery"]["remaining_seconds"] = 0
    result = town.blocker(sample, profile, settled=False, allow_recovery=True)
    assert (result is None) is (change is None)
    assert town.blocker(sample, profile, settled=False) is not None


def test_held_display_label_can_only_be_observed_with_paused_fresh_engine_marker(profile):
    sample = status(profile)
    sample["mode"] = "navigation"
    sample["player"]["tracked"] = True
    sample["position"].update(stale=True, held=True, marker=None, feet=None)
    sample["navigation"]["recovery"] = {
        "active": True, "input_suspended": True, "remaining_seconds": 1,
        "marker_fresh": True, "map_hash": map_hash(profile)}
    assert town.blocker(sample, profile, settled=False, allow_recovery=True) is None
    sample["navigation"]["recovery"]["marker_fresh"] = False
    assert town.blocker(sample, profile, settled=False, allow_recovery=True) is not None


def test_post_recovery_status_waits_for_publication_without_commands(profile):
    api = Api(profile)
    pending, published = status(profile), status(profile)
    pending["navigation"]["recovery"] = {"pending_publication": True}
    published["navigation"]["recovery"] = {"pending_publication": False}
    api.pending = [pending, published]
    check = town.Check(api, profile, sleep=lambda _: None)
    check.session = "session"
    result = check.status(allow_recovery=True)
    assert result["navigation"]["recovery"]["pending_publication"] is False
    assert not api.calls


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

    def run(api, profile, output, **kwargs):
        kwargs.setdefault("wall_clock", lambda: 1000 + ticks[0])
        return town.run(api, profile, output, clock=lambda: ticks[0], sleep=sleep, **kwargs)
    return run


class BundleApi(Api):
    def __init__(self, profile):
        super().__init__(profile)
        self.value["bindings"] = {"left": "left"}
        self.value["probes"] = {a: {"confirmed": True} for a in town.REUSED_CONTROLS}
        self.value["navigation"]["feedback"] = {
            "trusted": True, "motion_ok": True, "focused": True, "observed_at": 0}
        self.frames = 0

    def status(self):
        value = super().status()
        self.frames += 1
        value["navigation"]["feedback"]["observed_at"] = self.frames
        return value


def test_bundle_runs_only_three_routes_after_passive_feedback(profile, run_check, tmp_path):
    api = BundleApi(profile)
    bundle = town.session_plan(profile, api.value["bindings"])
    result = run_check(api, profile, tmp_path / "bundled", bundle=bundle)
    assert result["failure"] is None
    assert result["setup_seconds"] >= 2 and len(result["steps"]) == 3
    assert not any(name == "probe" for name, _ in api.calls)
    assert [p["target"] for n, p in api.calls if n == "nav_go"] == bundle["targets"]


@pytest.mark.parametrize("change", ["bundle", "bindings", "confirmation", "feedback", "frozen"])
def test_bundle_preflight_refuses_without_commands(profile, run_check, tmp_path, change):
    api = BundleApi(profile)
    bundle = town.session_plan(profile, api.value["bindings"])
    if change == "bundle":
        bundle["revision"] = "old-code"
    elif change == "bindings":
        api.value["bindings"]["left"] = "different"
    elif change == "confirmation":
        api.value["probes"]["up"]["confirmed"] = False
    elif change == "feedback":
        api.value["navigation"]["feedback"]["trusted"] = False
    else:
        api.status = lambda: copy.deepcopy(api.value)
    result = run_check(api, profile, tmp_path / change, bundle=bundle)
    assert result["failure"] and not result["movement_requested"] and not api.calls
    if change == "feedback":
        assert result["passive_feedback"][0]["navigation"]["feedback"]["trusted"] is False


def test_plan_cli_never_constructs_debugger(profile, monkeypatch, tmp_path, capsys):
    import sys

    monkeypatch.setattr(town, "ROOT", tmp_path)
    monkeypatch.setattr(town, "profile_for_town", lambda _: profile)
    monkeypatch.setattr(town, "Debugger", lambda: pytest.fail("Offline plan connected to engine"))
    (tmp_path / "config.toml").write_text("")
    monkeypatch.setattr(sys, "argv", ["town_check", "--plan"])
    town.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["targets"] == ["ledge", "ladder", "floor"]
    assert plan["stop_at_first_failure"] and plan["passive_seconds"] == 2


@pytest.mark.parametrize("flags", [["--plan", "--focus"], ["--check", "--focus"],
                                   ["--run", "--focus-click"]])
def test_focus_flags_require_explicit_mutating_run(flags, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["town_check", *flags])
    monkeypatch.setattr(town, "Debugger", lambda: pytest.fail("Invalid flags connected to engine"))
    with pytest.raises(SystemExit) as error:
        town.main()
    assert error.value.code == 2


def test_unfocused_default_never_requests_focus(profile, run_check, tmp_path):
    api = Api(profile)
    api.value["focused"] = False
    result = run_check(api, profile, tmp_path / "default")
    assert "not focused" in result["failure"]
    assert not api.calls and not result["focus_requested"]


@pytest.mark.parametrize("allow_click", [False, True])
def test_opted_in_focus_runs_once_before_normal_bundle_checks(
        profile, run_check, tmp_path, allow_click):
    api = BundleApi(profile)
    api.value["focused"] = False
    command = api.command

    def focus(name, payload=None):
        if name == "focus_game":
            api.calls.append((name, payload))
            api.value["focused"] = True
            api.value["frame"].update(id="focused:1", captured_at=1001)
            return {"focused": True}
        return command(name, payload)

    api.command = focus
    bundle = town.session_plan(profile, api.value["bindings"])
    result = run_check(api, profile, tmp_path / "focus", bundle=bundle,
                       focus=True, focus_click=allow_click)
    assert result["failure"] is None
    assert api.calls[0] == ("focus_game", {"click_fallback": allow_click})
    assert sum(name == "focus_game" for name, _ in api.calls) == 1
    assert [p["target"] for n, p in api.calls if n == "nav_go"] == bundle["targets"]


def test_declined_focus_stops_without_movement_or_retry(profile, run_check, tmp_path):
    api = Api(profile)
    api.value["focused"] = False
    result = run_check(api, profile, tmp_path / "declined", focus=True, focus_click=True)
    assert "focus request failed" in result["failure"]
    assert api.calls == [("focus_game", {"click_fallback": True})]
    assert not result["movement_requested"]


def test_focus_option_never_recovers_focus_during_a_route(profile, run_check, tmp_path):
    api = BundleApi(profile)
    command = api.command

    def lose_focus(name, payload=None):
        response = command(name, payload)
        if name == "nav_go":
            api.pending[1]["focused"] = False
        return response

    api.command = lose_focus
    bundle = town.session_plan(profile, api.value["bindings"])
    result = run_check(api, profile, tmp_path / "lost", bundle=bundle,
                       focus=True, focus_click=True)
    assert "not focused" in result["failure"]
    assert not any(name == "focus_game" for name, _ in api.calls)
    assert len(result["steps"]) == 1 and api.calls[-1][0] == "stop"


@pytest.mark.parametrize("cached_focused", [False, True])
def test_focus_waits_for_capture_after_handoff_before_bundle_readiness(
        profile, run_check, tmp_path, cached_focused):
    api = BundleApi(profile)
    api.value["focused"] = False
    api.value["frame"].update(id="old:1", captured_at=999)
    command = api.command

    def focus(name, payload=None):
        if name == "focus_game":
            api.calls.append((name, payload))
            cached, focused = copy.deepcopy(api.value), copy.deepcopy(api.value)
            cached["focused"] = cached_focused
            focused["focused"] = True
            focused["frame"].update(id="new:2", captured_at=1001)
            api.pending = [cached, cached, focused]
            return {"focused": True}
        return command(name, payload)

    api.command = focus
    bundle = town.session_plan(profile, api.value["bindings"])
    result = run_check(api, profile, tmp_path / "handoff", bundle=bundle,
                       focus=True, focus_click=True)
    assert result["failure"] is None
    assert [s["frame"]["id"] for s in result["focus_samples"]] == ["old:1", "old:1", "new:2"]
    assert result["setup_seconds"] >= 2.1
    assert sum(name == "focus_game" for name, _ in api.calls) == 1
    assert [p["target"] for n, p in api.calls if n == "nav_go"] == bundle["targets"]


@pytest.mark.parametrize("change", ["unchanged", "same-id", "missing-time", "nan-time"])
def test_focus_timeout_preserves_samples_without_refocus_or_movement(
        profile, run_check, tmp_path, change):
    api = Api(profile)
    api.value["focused"] = False
    api.value["frame"].update(id="old:1", captured_at=999)

    def focus(name, payload=None):
        api.calls.append((name, payload))
        api.value["focused"] = True
        if change == "same-id":
            api.value["frame"]["captured_at"] = 1001
        elif change in {"missing-time", "nan-time"}:
            api.value["frame"].update(id="new:2", captured_at=None if change == "missing-time"
                                      else float("nan"))
        return {"focused": True}

    api.command = focus
    result = run_check(api, profile, tmp_path / change, focus=True, focus_click=True)
    assert "No new capture after focus handoff" in result["failure"]
    assert town.FOCUS_FRAME_SECONDS <= result["setup_seconds"] <= town.FOCUS_FRAME_SECONDS + .1
    assert result["focus_samples"] and not result["movement_requested"]
    assert api.calls == [("focus_game", {"click_fallback": True})]


@pytest.mark.parametrize(("change", "message"), [
    ("focus", "not focused"), ("map", "Wrong tracked map"),
    ("player", "not freshly recognized"), ("frame", "stale"),
    ("session", "session changed"), ("alarm", "Active alarm"), ("mode", "remain input-capable"),
])
def test_post_focus_capture_still_requires_every_readiness_gate(
        profile, run_check, tmp_path, change, message):
    api = Api(profile)
    api.value["focused"] = False

    def focus(name, payload=None):
        api.calls.append((name, payload))
        api.value["focused"] = change != "focus"
        api.value["frame"].update(id="new:2", captured_at=1001)
        if change == "map":
            api.value["position"]["area_id"] = "other"
        elif change == "player":
            api.value["player"] = None
        elif change == "frame":
            api.value["frame"]["age_ms"] = 99999
        elif change == "session":
            api.value["session_id"] = "other"
        elif change == "alarm":
            api.value["alarm"] = {"active": True}
        elif change == "mode":
            api.value["mode"] = "navigation"
        return {"focused": True}

    api.command = focus
    result = run_check(api, profile, tmp_path / change, focus=True, focus_click=True)
    assert message in result["failure"]
    assert not result["movement_requested"]
    assert api.calls == [("focus_game", {"click_fallback": True})]


def test_bundle_stops_on_first_route_failure_and_refuses_unchanged_repeat(
        profile, run_check, tmp_path):
    api = BundleApi(profile)
    bundle = town.session_plan(profile, api.value["bindings"])
    command = api.command

    def fail_first_route(name, payload=None):
        result = command(name, payload)
        if name == "nav_go":
            api.pending[1]["focused"] = False
        return result

    api.command = fail_first_route
    result = run_check(api, profile, tmp_path / "failed", bundle=bundle)
    assert "not focused" in result["failure"] and len(result["steps"]) == 1
    assert result["steps"][0]["clip"] and api.calls[-1][0] == "stop"
    api = BundleApi(profile)
    result = run_check(api, profile, tmp_path / "repeat", bundle=bundle)
    assert "Unchanged failed movement" in result["failure"] and not api.calls


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
    stale["position"].update(stale=True, marker=None, held=True)
    stale["frame"]["age_ms"] = 510
    api.pending = [stale, status(profile)]
    check = town.Check(api, profile, sleep=lambda _: None)
    assert check.status()["position"]["stale"] is False
    assert not api.calls


def test_png_pair_wait_still_refuses_focus_loss_and_persistent_staleness(profile):
    api = Api(profile)
    stale = status(profile)
    stale["position"].update(stale=True, marker=None)
    stale["frame"]["age_ms"] = 510
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
    assert ticks[0] <= .83 and not api.calls


def test_held_surface_without_a_current_map_match_fails_immediately(profile):
    api = Api(profile)
    api.value["position"].update(stale=True, held=True, marker=None)
    slept = []
    check = town.Check(api, profile, sleep=lambda seconds: slept.append(seconds))
    with pytest.raises(RuntimeError, match="stale"):
        check.status()
    assert not slept and not api.calls


def test_waits_for_contact_after_known_map_motion_without_accepting_held_label(profile):
    api = Api(profile)
    moving = status(profile)
    moving["position"].update(stale=True, held=True, marker=None,
                               map="Player marker on the taught map")
    api.pending = [moving, status(profile)]
    slept = []
    check = town.Check(api, profile, sleep=lambda seconds: slept.append(seconds))
    assert check.status()["position"]["stale"] is False
    assert slept and not api.calls


def test_next_step_waits_for_settled_grip_instead_of_starting_from_unknown(profile):
    api = Api(profile)
    moving, settled = status(profile), status(profile)
    moving["position"].update(kind="unknown", surface_id=None,
                               map="Player marker on the taught map")
    settled["position"].update(kind="rope", surface_id="ladder")
    api.pending = [moving, settled]
    check = town.Check(api, profile, sleep=lambda _: None)
    assert check.status(settled=True, allow_rope=True)["position"]["kind"] == "rope"
    assert not api.calls


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
