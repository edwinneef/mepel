import copy
import json

import pytest

from maplebot.config import RecordingConfig
from maplebot.keyboard import ActionOutcome
from maplebot.potion_evidence import PotionEvidence, PotionFrame
from maplebot.recorder import SessionRecorder


def frame(clock, percent=20, *, sequence=None, source=(0, 0), confidence=1,
          safe=True, focused=True):
    sequence = round(clock * 100) if sequence is None else sequence
    return PotionFrame(f"{sequence:08d}", f"png:{sequence}".encode(), {
        "sequence": sequence, "captured_at": 1000 + clock,
        "potion_evidence_safe": safe, "focused": focused,
        "autopotter": {"readings": {
            resource: {"percent": percent, "confidence": confidence} for resource in ("hp", "mp")
        }},
    }, clock, source)


def outcome(ticket=1, resource="hp", result="completed", *, started=1.11, finished=1.2):
    return ActionOutcome(ticket, 7, f"{resource}_potion", f"{resource}_potion {result}",
                         1.1, started, finished)


@pytest.fixture
def collector():
    saved = []
    evidence = PotionEvidence("session", lambda record, frames: saved.append((record, frames)))
    evidence.observe(frame(1))
    evidence.queued(1, "hp", 1.1, (0, 0))
    return evidence, saved


def test_completion_needs_a_confident_frame_captured_after_actual_key_completion(collector):
    evidence, saved = collector
    evidence.outcome(outcome())
    assert evidence.snapshot()["records"][-1]["status"] == "awaiting_observation"
    evidence.observe(frame(1.19, 70))
    evidence.observe(frame(1.21, 70, confidence=.89))
    evidence.observe(frame(1.22, 70, focused=False))
    evidence.observe(frame(1.23, 70, safe=False))
    assert evidence.snapshot()["records"][-1]["after"] is None
    evidence.observe(frame(1.3, 70))
    record, frames = saved[-1]
    assert record["status"] == "observed_bar_gain"
    assert record["before"]["percent"] == 20 and record["after"]["percent"] == 70
    assert record["outcome"]["generation"] == 7
    assert frames[0].stem + ".png" == record["after"]["frame"]
    assert "not proof" in record["note"]
    evidence.outcome(outcome())  # A retained old outcome is not a second potion.
    assert len(saved) == 3 and len(evidence.snapshot()["records"]) == 1
    snapshot = evidence.snapshot()
    snapshot["records"][0]["status"] = "changed"
    assert evidence.snapshot()["records"][0]["status"] == "observed_bar_gain"


@pytest.mark.parametrize("percent,expected", [(20, "no_observed_gain"),
                                             (None, "observation_unavailable")])
def test_timeout_retains_in_window_sample_instead_of_a_late_gain(collector, percent, expected):
    evidence, saved = collector
    evidence.outcome(outcome())
    evidence.observe(frame(2, percent))
    evidence.observe(frame(3.21, 90))
    record, frames = saved[-1]
    assert record["status"] == expected
    assert record["after"] is None if percent is None else record["after"]["percent"] == 20
    assert len(frames) == (0 if percent is None else 1)


@pytest.mark.parametrize("baseline_clock,started", [(0, 1.11), (1, 1.7)])
def test_stale_baseline_or_delayed_input_cannot_prove_gain(baseline_clock, started):
    evidence = PotionEvidence("session", lambda *args: None)
    evidence.observe(frame(baseline_clock))
    evidence.queued(1, "hp", 1.1, (0, 0))
    evidence.outcome(outcome(started=started, finished=started + .1))
    evidence.observe(frame(started + .2, 90))
    record = evidence.snapshot()["records"][0]
    assert not record["baseline_usable"]
    assert record["status"] == "baseline_unavailable"


def test_cancelled_and_wrong_ticket_outcomes_cannot_claim_recovery(collector):
    evidence, saved = collector
    evidence.outcome(outcome(ticket=99))
    evidence.outcome(outcome(resource="mp"))
    assert len(saved) == 1
    evidence.outcome(outcome(result="interrupted"))
    evidence.observe(frame(1.3, 90))
    assert saved[-1][0]["status"] == "input_not_completed"
    assert saved[-1][0]["after"] is None


def test_same_resource_supersedes_but_hp_and_mp_observations_remain_independent(collector):
    evidence, saved = collector
    evidence.outcome(outcome())
    evidence.observe(frame(1.3, 20))
    evidence.queued(2, "mp", 1.31, (0, 0))
    evidence.queued(3, "hp", 1.32, (0, 0))
    assert evidence.snapshot()["records"][0]["status"] == "superseded"
    assert saved[-2][1][0].clock == 1.3
    assert set(evidence.pending) == {2, 3}
    evidence.close()
    assert all(r["status"] != "queued" for r in evidence.snapshot()["records"])


def test_source_change_and_missing_outcome_are_incomplete_not_potion_failures(collector):
    evidence, _ = collector
    evidence.observe(frame(1.3, source=(1, 0)))
    assert evidence.snapshot()["records"][0]["status"] == "source_changed"
    evidence.queued(2, "mp", 1.4, (1, 0))
    evidence.observe(frame(6.5, source=(1, 0)))
    assert evidence.snapshot()["records"][-1]["status"] == "outcome_unavailable"


def test_history_is_bounded_and_auto_recording_off_disables_capture():
    evidence = PotionEvidence("session", lambda *args: None)
    for ticket in range(50):
        evidence.queued(ticket, "hp", 1.1, (0, 0))
    assert len(evidence.snapshot()["records"]) == 32 and len(evidence.pending) == 1
    disabled = PotionEvidence("session", lambda *args: pytest.fail("Recording disabled"),
                              enabled=False)
    disabled.queued(1, "hp", 1.1, (0, 0))
    disabled.outcome(outcome())
    disabled.observe(frame(1.3, 90))
    assert disabled.snapshot() == {"enabled": False, "records": []}


def test_paired_frames_and_decisions_survive_normal_recorder_stop(tmp_path):
    recorder = SessionRecorder(tmp_path, RecordingConfig(keyframe_seconds=0), fps=4)
    evidence = PotionEvidence("session", recorder.save_potion)
    before, after = frame(1), frame(1.3, 90)
    try:
        normal = recorder.start("combat")
        recorder.observe(before.stem, before.raw, before.status, before.clock)
        evidence.observe(before)
        evidence.queued(1, "hp", 1.1, (0, 0))
        evidence.outcome(outcome())
        recorder.stop()
        evidence.observe(after)
        record = copy.deepcopy(evidence.snapshot()["records"][0])
    finally:
        evidence.close()
        recorder.close()
    path = tmp_path / record["recording"]
    assert path != normal
    for sample in (before, after):
        assert (path / f"{sample.stem}.png").read_bytes() == sample.raw
    rows = [json.loads(line) for line in (path / "decisions.jsonl").read_text().splitlines()]
    assert [(row["frame"], row["captured_at"]) for row in rows] == [
        (f"{sample.stem}.png", sample.status["captured_at"]) for sample in (before, after)
    ]
    lines = (path / "potion-evidence.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["status"] for r in records] == [
        "queued", "awaiting_observation", "observed_bar_gain",
    ]
    assert not recorder.active


def test_potion_pruning_preserves_active_combat_and_pending_potion_writes(tmp_path):
    recorder = SessionRecorder(tmp_path, RecordingConfig(max_total_mb=1), fps=4)
    evidence = PotionEvidence("session", recorder.save_potion)
    try:
        normal = recorder.start("combat")
        (normal / "large.png").write_bytes(b"x" * (2 * 1024 * 1024))
        evidence.observe(frame(1))
        evidence.queued(1, "hp", 1.1, (0, 0))
        evidence.queued(2, "mp", 1.1, (0, 0))
        assert len(recorder.potion_paths) == 2
    finally:
        evidence.close()
        recorder.close()
    assert (normal / "large.png").exists()
    for record in evidence.snapshot()["records"]:
        path = tmp_path / record["recording"]
        assert (path / record["before"]["frame"]).exists()
        rows = (path / "potion-evidence.jsonl").read_text().splitlines()
        assert json.loads(rows[-1])["status"] == "capture_ended"
    assert not recorder.potion_paths
