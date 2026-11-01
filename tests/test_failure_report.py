import json

import pytest

from tools.failure_report import classify, clip_summary, navigation_diagnosis, run, summarize


def saved_failure(tmp_path, reason="Click the actual game window before the countdown ends"):
    clip = tmp_path / "clip"
    clip.mkdir()
    records = [
        {"sequence": 1, "captured_at": 10, "mode": "pending_arm", "focused": True,
         "latency_ms": 40, "frame": "1.png"},
        {"sequence": 2, "captured_at": 13, "mode": "live", "focused": True,
         "latency_ms": 450, "stage_timing": {"perception_ms": 410}, "frame": "2.png"},
        {"sequence": 3, "captured_at": 17, "mode": "capture", "focused": False,
         "latency_ms": 50, "frame": "3.png"},
    ]
    (clip / "decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), "utf-8")
    stop = {"id": "failure", "code": "FOCUS_LOSS", "severity": "ALARM",
            "message": reason, "clip_path": str(clip)}
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"error": reason, "seconds": 7,
                                "samples": [{"stop": stop}], "after": {"stop": stop}}), "utf-8")
    return path, clip


def test_saved_report_separates_countdown_from_active_time_and_preserves_sources(tmp_path):
    path, clip = saved_failure(tmp_path)
    before = {p: p.read_bytes() for p in (path, clip / "decisions.jsonl")}
    report = run(path, tmp_path / "report")
    assert report["input_sent"] is False and report["native_acceptance"] is False
    assert report["reported_run_seconds"] == 7
    assert report["clips"][0]["observed_active_seconds"] == 4
    assert report["clips"][0]["slowest_frames"][0]["sequence"] == 2
    assert report["clips"][0]["largest_frame_gaps"][0]["gap_ms"] == 4000
    assert not report["clips"][0]["foreground_owner_recorded"]
    assert len(report["stops"]) == 1
    assert {p: p.read_bytes() for p in before} == before


def test_stale_feedback_is_not_diagnosed_as_operator_focus_loss(tmp_path):
    path, _ = saved_failure(tmp_path, "Target focus lost: Navigation fused position is stale")
    assert summarize(path)["category"] == "navigation"
    assert classify("Player recognition failed")[0] == "perception"
    assert classify("Farming HP unreadable; stopped")[0] == "health"


def test_active_time_excludes_previous_activity_in_recorder_pre_roll(tmp_path):
    _, clip = saved_failure(tmp_path)
    assert clip_summary(clip, since=15, until=16)["observed_active_seconds"] == 1


def test_report_retains_refusal_stage_and_foreground_owner_after_stop(tmp_path):
    path, _ = saved_failure(tmp_path)
    value = json.loads(path.read_text())
    value["after"]["input_refusal"] = {
        "processing": {"sequence": 7, "stage": "perception"},
        "window": {"foreground": {"hwnd": 42, "pid": 5}},
    }
    value["after"]["input_state"] = {"enabled": False, "held_keys": []}
    path.write_text(json.dumps(value))
    report = summarize(path)
    assert report["input_refusal"]["processing"]["stage"] == "perception"
    assert report["input_refusal"]["window"]["foreground"]["pid"] == 5
    assert report["input_state"]["held_keys"] == []


def test_missing_clip_is_explicit_and_requested_replay_fails_without_losing_report(tmp_path):
    path = tmp_path / "result.json"
    path.write_text('{"error":"focus lost"}', "utf-8")
    report = run(path, tmp_path / "report", replay_policy=True)
    assert report["policy_replays"][0]["error"] == "No recorded clip path in check result"
    assert (tmp_path / "report/summary.json").is_file()


def test_report_never_writes_into_clip_or_overwrites_previous_report(tmp_path):
    path, clip = saved_failure(tmp_path)
    with pytest.raises(ValueError, match="outside source recordings"):
        run(path, clip / "analysis")
    assert not (clip / "analysis").exists()
    output = tmp_path / "report"
    run(path, output)
    with pytest.raises(FileExistsError):
        run(path, output)


def test_policy_replay_uses_saved_decisions_without_loading_detector(tmp_path, monkeypatch):
    from test_replay import policy_record

    from maplebot.config import Config

    def no_detector(*args, **kwargs):
        raise AssertionError("Policy replay must not initialize the sprite catalog")
    monkeypatch.setattr("maplebot.replay.TemplateDetector", no_detector)
    path, clip = saved_failure(tmp_path)
    config = Config()
    record = policy_record(config, 0, 0)
    record["captured_at"] = 10
    record["decision"]["reason"] = "Old policy reason"
    (clip / "decisions.jsonl").write_text(json.dumps(record) + "\n", "utf-8")
    monkeypatch.setattr(Config, "load", lambda _: config)
    report = run(path, tmp_path / "report", replay_policy=True)
    assert report["policy_replays"][0]["differences"] == 1
    assert report["policy_replays"][0]["comparison_only"] is True


@pytest.mark.parametrize(("reason", "symptoms"), [
    ("Rope grip not observed", ["rope_grip"]),
    ("Navigation fused position is stale", ["observation_freshness", "identity_localization"]),
    ("Departure not observed; retry budget exhausted", ["trajectory_corridor", "execution_budget"]),
    ("Unexpected result", ["unknown"]),
])
def test_taxonomy_distinguishes_symptoms_without_guessing_input_or_physics(reason, symptoms):
    diagnosis = navigation_diagnosis(reason, {})
    assert diagnosis["symptoms"] == symptoms
    assert diagnosis["causal_attribution"] == "unknown"
    assert diagnosis["recorded_reason"] == reason
    assert diagnosis["stage"] is None and diagnosis["input_state"] is None


def test_taxonomy_retains_recorded_phase_refusal_and_contradictory_evidence():
    state = {"navigation": {"stage": "grip", "edge": "rope-1",
                            "feedback": {"age_ms": 700},
                            "last_input_refusal": {"reason": "input deadline expired"}},
             "input_state": {"last_ticket": {"status": "complete"}}}
    diagnosis = navigation_diagnosis("Rope grip failed with stale feedback", state)
    assert diagnosis["symptoms"] == ["observation_freshness", "rope_grip", "input_refusal"]
    assert diagnosis["input_refusal"] == state["navigation"]["last_input_refusal"]
    assert diagnosis["input_state"] == state["input_state"]
    assert diagnosis["edge"] == "rope-1" and diagnosis["stage"] == "grip"
    assert diagnosis["causal_attribution"] == "unknown"


def test_route_handoff_is_navigation_context_without_asserting_displacement_cause():
    reason = "Origin no longer matches the previewed route"
    assert classify(reason)[0] == "navigation"
    diagnosis = navigation_diagnosis(reason, {})
    assert diagnosis["symptoms"] == ["map_context"]
    assert diagnosis["causal_attribution"] == "unknown"
