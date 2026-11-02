import json

import pytest

from maplebot.farming import CHECKPOINT_STOP
from tools.farming_check import (
    checked_circuit,
    circuit_progress,
    combat_progress,
    rotation_blocker,
    run,
)


class Api:
    def __init__(self, *, finish=True):
        self.calls = []
        self.finish = finish
        self.running = False

    def status(self):
        return {"session_id": "s", "mode": "live" if self.running else "capture",
                "focused": True, "position": {"area_id": "island", "surface_id": "a",
                                               "feet": [0, 0]},
                "navigation": {"map": {"nodes": [
                    {"id": "a", "kind": "platform"}, {"id": "b", "kind": "platform"}],
                    "edges": [{"from": "a", "to": "b", "proven": True}]}},
                "player": {"confidence": 1},
                "autopotter": {"readings": {r: {"percent": 80, "confidence": 1}
                                           for r in ("hp", "mp")}}}

    def command(self, name, payload=None):
        self.calls.append((name, payload))
        self.running = name == "arm" and not self.finish


def test_session_uses_no_pet_and_always_stops(tmp_path):
    api = Api()
    result = run(api, tmp_path / "run", area="island")
    assert api.calls[0][1]["farming"] == {
        "session_minutes": 15, "pet_recovery": False, "no_consumables": True}
    assert api.calls[-1][0] == "stop"
    assert result["outcome"] == "failure"
    assert result["error"] == "Current combat evidence unavailable"
    assert json.loads((tmp_path / "run/result.json").read_text())["after"]["mode"] == "capture"


def test_consumables_sustain_with_potions_instead_of_stopping_and_exclude_checkpoints(tmp_path):
    api = Api()
    run(api, tmp_path / "run", area="island", consumables=True)
    assert api.calls[0][1]["farming"]["no_consumables"] is False
    assert api.calls[0][1]["farming"]["pet_recovery"] is False
    with pytest.raises(ValueError, match="Checkpoints run without consumables"):
        run(Api(), tmp_path / "other", area="island", consumables=True, checkpoint_seconds=5)


class CircuitApi(Api):
    def __init__(self, **change):
        super().__init__()
        self.route = {"id": "loop", "revision": 2, "area_id": "island", "loop": True,
                      "stops": ["a", "b"]} | change
        self.valid = True

    def command(self, name, payload=None):
        if name == "farm_route_list":
            self.calls.append((name, payload))
            return {"routes": [self.route]}
        if name == "farm_route_validate":
            self.calls.append((name, payload))
            return {"valid": self.valid, "errors": ["Map geometry changed"]}
        return super().command(name, payload)


@pytest.mark.parametrize("change,message", [
    ({"revision": 3}, "changed"), ({"loop": False}, "looping"),
    ({"area_id": "elsewhere"}, "this map"),
])
def test_saved_circuit_refusals_never_arm(change, message):
    api = CircuitApi(**change)
    with pytest.raises(ValueError, match=message):
        checked_circuit(api, "island", {"id": "loop", "revision": 2})
    assert not any(name == "arm" for name, _ in api.calls)


def test_changed_geometry_refuses_and_verified_revision_reaches_arm(tmp_path):
    api = CircuitApi()
    api.valid = False
    with pytest.raises(ValueError, match="geometry"):
        checked_circuit(api, "island", {"id": "loop", "revision": 2})
    api.valid = True
    run(api, tmp_path / "run", area="island", consumables=True,
        circuit={"id": "loop", "revision": 2})
    arm = next(payload for name, payload in api.calls if name == "arm")
    assert arm["circuit"] == {"id": "loop", "revision": 2}
    assert arm["farming"]["no_consumables"] is False
    assert api.calls[-1][0] == "stop"


def test_circuit_progress_needs_new_combat_after_an_observed_arrival():
    first = {"mode": "live", "position": {"surface_id": "a"},
             "combat_evidence": {"events": events()}}
    travel = {"mode": "navigation", "position": {"surface_id": None}}
    arrived = {"mode": "live", "position": {"surface_id": "b"},
               "combat_evidence": {"events": events()}}
    assert not circuit_progress([first, travel, arrived], ["a", "b"])["combat_after_arrival"]
    arrived["combat_evidence"]["events"] += events(2, 2)
    assert circuit_progress([first, travel, arrived], ["a", "b"])["combat_after_arrival"]


def test_timeout_stops_and_records_failure(tmp_path):
    api = Api(finish=False)
    ticks = iter([0, 911, 912])
    result = run(api, tmp_path / "run", area="island", clock=lambda: next(ticks))
    assert "deadline" in result["error"]
    assert api.calls[-1][0] == "stop"


def test_wrong_map_sends_no_commands(tmp_path):
    api = Api()
    with pytest.raises(RuntimeError, match="Wrong map"):
        run(api, tmp_path / "run", area="wrong")
    assert api.calls == []


def events(acquisition=1, ticket=1, result="attack completed"):
    return [{"kind": "decision", "action": "attack", "ticket": ticket,
             "acquisition": acquisition},
            {"kind": "input_outcome", "action": "attack", "ticket": ticket, "result": result}]


def test_progress_requires_completed_attacks_on_separate_acquisitions():
    sample = {"combat_evidence": {"events": events() + events(ticket=2)}}
    assert not combat_progress([sample, sample])["repeated_combat"]
    sample["combat_evidence"]["events"] += events(2, 3, "attack canceled")
    assert not combat_progress([sample])["repeated_combat"]
    sample["combat_evidence"]["events"] += events(2, 4)
    progress = combat_progress([sample, sample])
    assert progress["repeated_combat"] and progress["completed_attacks"] == 3
    assert progress["hits_confirmed"] is None and progress["kills_confirmed"] is None


class SessionApi(Api):
    def __init__(self, stop, *, combat=True, lost_focus=False, session="s"):
        super().__init__()
        self.now = 0
        self.armed = False
        self.polls = 0
        self.stop_record = stop
        self.combat = combat
        self.lost_focus = lost_focus
        self.session = session

    def command(self, name, payload=None):
        self.calls.append((name, payload))
        if name == "arm":
            self.armed = True
        if name == "stop":
            self.armed = False

    def status(self):
        sample = super().status()
        sample["readiness"] = {"combat": {"ready": True}}
        sample.pop("navigation")  # A continuous floor does not require navigation routes.
        if self.armed:
            self.polls += 1
            self.now = self.polls * 31
            sample.update(session_id=self.session, mode="live" if self.polls == 1 else "capture",
                          focused=not self.lost_focus,
                          combat_evidence={"run": 1, "session_id": "s", "activity": "combat",
                                           "events": events() + events(2, 2)
                                           if self.combat else []})
            if self.polls > 1:
                sample["stop"] = self.stop_record
        return sample


@pytest.mark.parametrize(("message", "combat", "expected"), [
    ("Farming session limit reached; restart manually", True, "functional_success"),
    ("Farming session limit reached; restart manually", False, "failure"),
    ("HP low; no consumables available, stopped", True, "safe_stop"),
    ("MP low; no consumables available, stopped", False, "safe_stop"),
    ("Farming HP unreadable; stopped", True, "failure"),
    ("Farming made no combat progress for 15 seconds; inspect saved clip", False, "failure"),
    ("", True, "failure"),
])
def test_session_outcomes_are_distinct(tmp_path, message, combat, expected):
    api = SessionApi({"code": "FARMING_STOP", "message": message}, combat=combat)
    result = run(api, tmp_path / "run", area="island", single_platform=True,
                 session_minutes=1, clock=lambda: api.now, sleep=lambda _: None)
    assert result["outcome"] == expected
    assert api.calls[0][1]["farming"]["single_platform"] is True


@pytest.mark.parametrize("move,expected", [(False, "failure"), (True, "functional_success")])
def test_circuit_expiry_requires_travel_and_combat_then_confirms_release(tmp_path, move, expected):
    class LoopApi(CircuitApi):
        now = 0
        polls = 0
        armed = False

        def command(self, name, payload=None):
            if name in {"arm", "stop"}:
                self.armed = name == "arm"
            return super().command(name, payload)

        def status(self):
            sample = super().status()
            sample["input_state"] = {"enabled": self.armed, "held_keys": []}
            if self.armed:
                self.polls += 1
                self.now = (20, 30, 40, 62)[self.polls - 1]
                sample["mode"] = ("live", "navigation" if move else "live",
                                  "live", "capture")[self.polls - 1]
                sample["position"]["surface_id"] = "b" if move and self.polls >= 3 else "a"
                sample["combat_evidence"] = {"run": 1, "session_id": "s", "activity": "combat",
                    "events": events() + (events(2, 2) if self.polls >= 3 else [])}
                if self.polls == 4:
                    sample["stop"] = {"code": "FARMING_STOP",
                                      "message": "Farming session limit reached; restart manually"}
            return sample

    api = LoopApi()
    result = run(api, tmp_path / "run", area="island", session_minutes=1, consumables=True,
                 circuit={"id": "loop", "revision": 2}, clock=lambda: api.now, sleep=lambda _: None)
    assert result["outcome"] == expected
    assert result["full_session_passed"] is move
    assert api.calls[-1][0] == "stop"
    assert result["after"]["input_state"] == {"enabled": False, "held_keys": []}
    assert api.calls[-1][0] == "stop"
    assert result["after"]["mode"] == "capture"


@pytest.mark.parametrize("problem", ["focus", "session"])
def test_session_failure_stops_immediately(tmp_path, problem):
    api = SessionApi({}, lost_focus=problem == "focus",
                     session="new" if problem == "session" else "s")
    result = run(api, tmp_path / "run", area="island", single_platform=True,
                 session_minutes=1, clock=lambda: api.now, sleep=lambda _: None)
    assert result["outcome"] == "failure" and result["error"]
    assert api.polls == 1 and api.calls[-1][0] == "stop"


@pytest.mark.parametrize("problem", ["capture_only", "readiness", "navigation", "shutdown"])
def test_single_platform_never_passes_unsafe_start_or_shutdown(tmp_path, problem):
    class UnsafeApi(SessionApi):
        def status(self):
            sample = super().status()
            if problem == "capture_only":
                sample["capture_only"] = True
            elif problem == "readiness":
                sample["readiness"]["combat"]["ready"] = False
            elif problem == "navigation" and self.armed:
                sample["mode"] = "navigation"
            elif problem == "shutdown" and self.calls and self.calls[-1][0] == "stop":
                sample["mode"] = "live"
            return sample

    api = UnsafeApi({"code": "FARMING_STOP",
                     "message": "Farming session limit reached; restart manually"})
    if problem in {"capture_only", "readiness"}:
        with pytest.raises(RuntimeError):
            run(api, tmp_path / "run", area="island", single_platform=True)
        assert api.calls == []
    else:
        result = run(api, tmp_path / "run", area="island", single_platform=True,
                     session_minutes=1, clock=lambda: api.now, sleep=lambda _: None)
        assert result["outcome"] == "failure"
        assert api.calls[-1][0] == "stop"


class CheckpointApi(SessionApi):
    def __init__(self, *, problem=None):
        super().__init__({"code": "FARMING_STOP", "message": CHECKPOINT_STOP})
        self.problem = problem

    def status(self):
        sample = super().status()
        sample.update(farming_checkpoint_available=self.problem != "old-engine",
                      frame={"source_id": "view"}, code_revision={"runtime.py": "hash"},
                      input_state={"enabled": False, "held_keys": []})
        if self.armed:
            self.now = self.polls * (1 if self.problem == "early" else 5)
            if self.problem == "source":
                sample["frame"]["source_id"] = "new-view"
            if self.problem == "code":
                sample["code_revision"] = {"runtime.py": "new"}
            if self.problem == "no-attacks":
                sample["combat_evidence"]["events"] = []
            if self.problem == "timeout":
                sample["mode"] = "live"
        elif self.polls and self.problem == "held-key":
            sample["input_state"]["held_keys"] = ["ctrl"]
        return sample


def test_short_checkpoint_requires_attacks_but_is_never_a_full_session_pass(tmp_path):
    api = CheckpointApi()
    result = run(api, tmp_path / "run", area="island", single_platform=True,
                 checkpoint_seconds=10, clock=lambda: api.now, sleep=lambda _: None)
    assert result["outcome"] == "checkpoint_success"
    assert result["full_session_passed"] is False
    assert api.calls[0][1]["farming"]["checkpoint_seconds"] == 10
    assert api.calls[0][1]["farming"]["no_consumables"] is True
    assert api.calls[-1][0] == "stop"


@pytest.mark.parametrize("problem", [
    "early", "source", "code", "no-attacks", "held-key", "timeout"])
def test_checkpoint_refuses_missing_or_changed_evidence_and_releases(tmp_path, problem):
    api = CheckpointApi(problem=problem)
    result = run(api, tmp_path / "run", area="island", single_platform=True,
                 checkpoint_seconds=10, clock=lambda: api.now, sleep=lambda _: None)
    assert result["outcome"] == "failure"
    assert result["full_session_passed"] is False
    assert api.calls[-1][0] == "stop"
    assert (tmp_path / "run/failure/summary.json").is_file()


def test_checkpoint_requires_installed_engine_support_before_arm(tmp_path):
    api = CheckpointApi(problem="old-engine")
    with pytest.raises(RuntimeError, match="lacks bounded"):
        run(api, tmp_path / "run", area="island", single_platform=True,
            checkpoint_seconds=10)
    assert not api.calls


@pytest.mark.parametrize("percent", [49, None])
def test_existing_health_policy_is_checked_before_arming_from_safe_staging(tmp_path, percent):
    api = CheckpointApi()
    status = api.status
    def low_health():
        sample = status()
        sample["autopotter"]["readings"]["hp"]["percent"] = percent
        return sample
    api.status = low_health
    with pytest.raises(RuntimeError, match="No farming started"):
        run(api, tmp_path / "run", area="island", single_platform=True,
            checkpoint_seconds=10)
    assert not api.calls


@pytest.mark.parametrize("stale", [True, False])
def test_rotation_preflight_refuses_stale_or_disconnected_origin_without_commands(tmp_path, stale):
    class Blocked(Api):
        def status(self):
            status = super().status()
            status["position"]["stale"] = stale
            status["navigation"]["map"]["edges"] = []
            return status

    api = Blocked()
    with pytest.raises(RuntimeError, match="fresh mapped|No rotation route"):
        run(api, tmp_path / "run", area="island")
    assert api.calls == []


def test_rotation_preflight_names_a_rope_without_commands(tmp_path):
    class Rope(Api):
        def status(self):
            status = super().status()
            status["position"]["kind"] = "rope"
            return status

    api = Rope()
    with pytest.raises(RuntimeError, match="You're on a rope; stand on a platform"):
        run(api, tmp_path / "run", area="island")
    assert api.calls == []


def test_rotation_preflight_waits_through_a_brief_recognition_gap(tmp_path):
    class Gap(Api):
        reads = 0

        def status(self):
            status = super().status()
            self.reads += 1
            if self.reads == 1:
                status["position"] |= {"stale": True, "held": True, "feet": None}
            return status

    api = Gap()
    run(api, tmp_path / "run", area="island", session_minutes=5)
    assert api.reads > 1 and api.calls[0][0] == "arm"


def test_rotation_connectivity_uses_computed_edges_but_not_unrotatable_platforms():
    # Operator rule (2026-11-02): computed moves count; a platform the engine marks as
    # outside the rotation round trip is still no destination.
    status = Api().status()
    graph = status["navigation"]["map"]
    graph["nodes"].append({"id": "upper", "kind": "platform", "unproven": True})
    graph["edges"] = [{"from": "a", "to": "upper", "proven": False},
                      {"from": "upper", "to": "a", "proven": False}]
    assert "No rotation route" in rotation_blocker(status)
    graph["edges"].append({"from": "upper", "to": "b", "proven": False})
    assert rotation_blocker(status) is None


def test_existing_evidence_directory_rejected_before_commands(tmp_path):
    api = Api()
    output = tmp_path / "existing"
    output.mkdir()
    (output / "result.json").write_text("preserve")
    with pytest.raises(FileExistsError):
        run(api, output, area="island")
    assert api.calls == []
    assert (output / "result.json").read_text() == "preserve"


def test_enemy_acceptance_does_not_start_without_fresh_enemy(tmp_path):
    api = Api()
    with pytest.raises(RuntimeError, match="No fresh same-platform enemy"):
        run(api, tmp_path / "run", area="island", require_enemy=True)
    assert api.calls == []


def test_enemy_ready_snapshot_is_followed_by_arm(tmp_path):
    class EnemyApi(Api):
        def status(self):
            sample = super().status()
            sample["player"]["box"] = {"y": 100, "height": 40}
            sample["monsters"] = [{"confidence": 1, "box": {"y": 110, "height": 30}}]
            return sample

    api = EnemyApi()
    run(api, tmp_path / "run", area="island", require_enemy=True)
    assert api.calls[0][0] == "arm"
    assert api.calls[-1][0] == "stop"


def test_learn_moves_is_accepted_and_changes_nothing(tmp_path):
    status = Api().status()
    graph = status["navigation"]["map"]
    graph["edges"] = [{"from": "a", "to": "b", "proven": False}]
    assert rotation_blocker(status) is None  # a computed move suffices
    assert rotation_blocker(status, learn_moves=True) is None
    graph["edges"] = [{"from": "a", "to": "a", "proven": False},
                      {"from": "b", "to": "a", "proven": False}]
    assert "No rotation route" in rotation_blocker(status, learn_moves=True)

    class Unproven(Api):
        def status(self):
            status = super().status()
            status["navigation"]["map"]["edges"][0]["proven"] = False
            return status

    api = Unproven()
    run(api, tmp_path / "run", area="island", session_minutes=5, learn_moves=True)
    assert api.calls[0][1]["farming"]["learn_moves"] is True
    assert api.calls[-1][0] == "stop"
    with pytest.raises(ValueError, match="learn_moves needs platform rotation"):
        run(Api(), tmp_path / "other", area="island", single_platform=True, learn_moves=True)


def test_recovery_thresholds_follow_the_potion_thresholds(tmp_path):
    api = Api()
    base = api.status
    api.status = lambda: {**base(), "autopotter": {**base()["autopotter"],
                                                    "settings": {"hp_threshold": 40.0, "mp_threshold": 0}}}
    run(api, tmp_path / "run", area="island")
    farming = api.calls[0][1]["farming"]
    assert farming["hp_threshold"] == 40.0 and farming["mp_threshold"] == 1
