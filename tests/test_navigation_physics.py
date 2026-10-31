import json

import pytest

from tools.calibrate_navigation_physics import calibrate, observations
from tools.navigation_harness import main


def jump(start):
    def frame(t, y, surface):
        return {"capture_clock": start + t, "focused": True, "frame": f"{t}.png",
                "player": {"confidence": 1, "tracked": False},
                "position": {"area_id": "area", "feet": [100, y], "surface_id": surface,
                             "calibrated": True, "provisional": False},
                "input_timing": {"schedule": {"events": [{"action": "jump", "down": True}]}}}
    return [frame(0, 400, "floor"),
            *(frame(i / 20, 400 - 420 * i / 20 + 600 * (i / 20) ** 2, None)
              for i in range(1, 14)), frame(.8, 400, "floor")]


def write(root, name, rows):
    path = root / name / "decisions.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def test_fits_two_jumps_and_evaluates_held_out_frames(tmp_path):
    path = write(tmp_path, "clip", jump(0) + jump(10))
    original = path.read_bytes()
    result = calibrate(tmp_path)
    assert result["accepted_flights"] == 2
    assert result["parameters"] == {"gravity": 1200, "jump_speed": 420}
    assert result["constraints"]["jump_rise_px"]["median"] == 73.5
    assert all(c["holdout_frames"] >= 3 and c["holdout_rmse_px"] == 0
               for c in result["candidates"])
    assert result["unidentified"] == ["speed", "acceleration", "braking"]
    assert path.read_bytes() == original
    assert result["input_sent"] is result["native_acceptance"] is False


def test_overlapping_clips_are_not_independent_jumps(tmp_path):
    rows = jump(0)
    write(tmp_path, "a", rows)
    write(tmp_path, "b", rows)
    result = calibrate(tmp_path)
    assert result["accepted_flights"] == 1 and result["parameters"] == {}
    assert result["constraints"] == {}
    assert result["sources"][0]["sha256"] == result["sources"][1]["sha256"]


def test_conflicting_duplicates_and_tracked_players_break_flight(tmp_path):
    rows = jump(0)
    write(tmp_path, "a", rows)
    rows[5]["position"]["feet"][1] += 20
    rows[7]["player"]["tracked"] = True
    write(tmp_path, "b", rows)
    samples, _, conflicts = observations(tmp_path)
    assert conflicts == 2 and sum(s["feet"] is None for s in samples) == 2
    assert calibrate(tmp_path)["parameters"] == {}


def test_missing_focus_cannot_form_a_fit(tmp_path):
    rows = jump(0)
    for row in rows[3:7]:
        row["focused"] = False
    write(tmp_path, "a", rows)
    assert calibrate(tmp_path)["parameters"] == {}


def test_different_player_or_calibration_cannot_be_pooled(tmp_path):
    first, second = jump(0), jump(10)
    for row in second:
        row["player"]["template"] = "nametag:another-player"
    write(tmp_path, "a", first + second)
    result = calibrate(tmp_path)
    assert result["accepted_flights"] == 2
    assert result["parameters"] == result["constraints"] == {}


def test_insufficient_evidence_is_deterministic_and_has_no_parameters(tmp_path):
    write(tmp_path, "a", jump(0)[:4])
    result = calibrate(tmp_path)
    assert result == calibrate(tmp_path)
    assert result["parameters"] == {} and len(result["unidentified"]) == 5


def dispatch(clock, down=True, key="space"):
    return {"clock": clock, "finished_clock": clock + .002, "issued_at": 1800000000,
            "key": key, "down": down, "at_seconds": .025}


def test_absolute_events_are_deduplicated_and_aligned_to_capture_clock(tmp_path):
    rows = jump(100)
    event = dispatch(100.025)
    for row in rows:
        row["input_timing"]["events"] = [event]
    path = write(tmp_path, "a", rows)
    write(tmp_path, "b", rows)
    original = path.read_bytes()
    result = calibrate(tmp_path)["input_alignment"]
    assert result["unique_events"] == result["aligned_events"] == 1
    aligned = result["events"][0]
    assert aligned["before_clock"] == 100 and aligned["after_clock"] == 100.05
    assert aligned["observed_delta"] == pytest.approx([0, -19.5])
    assert path.read_bytes() == original


def test_equal_relative_offsets_are_distinct_and_wall_clock_is_not_used(tmp_path):
    rows = jump(100)
    events = [dispatch(100.025), dispatch(100.125, False)]
    events[1]["issued_at"] = 1  # A wall-clock correction cannot reorder monotonic events.
    rows[-1]["input_timing"]["events"] = events
    write(tmp_path, "a", rows)
    result = calibrate(tmp_path)["input_alignment"]
    assert result["unique_events"] == result["aligned_events"] == 2
    assert [e["clock"] for e in result["events"]] == [100.025, 100.125]


def test_retained_history_is_preferred_and_deduplicated_across_frames(tmp_path):
    rows = jump(100)
    history = [dispatch(100.025), dispatch(100.125, False)]
    for row in rows:
        row["input_timing"]["history"] = history
        row["input_timing"]["events"] = [history[-1]]
    write(tmp_path, "a", rows)
    result = calibrate(tmp_path)["input_alignment"]
    assert result["unique_events"] == result["aligned_events"] == 2


def history_row(sequences, limit=2, last=None):
    last = max(sequences, default=0) if last is None else last
    row = jump(100)[0]
    row["capture_clock"] = 100 + last
    row["input_timing"] = {
        "history": [dispatch(100 + seq / 100) | {"sequence": seq} for seq in sequences],
        "history_limit": limit, "history_last_sequence": last,
        "history_dropped": last - len(sequences)}
    return row


def coverage(root):
    return calibrate(root)["input_alignment"]["history_coverage"]


def test_evicted_events_already_saved_are_not_reported_missing(tmp_path):
    write(tmp_path, "a", [history_row([1, 2]), history_row([3, 4]), history_row([3, 4])])
    result = coverage(tmp_path)
    clip = result["clips"][0]
    assert result["status"] == "complete"
    assert clip["observed_events"] == 4 and clip["evictions_seen"] == 2
    assert clip["missing_ranges"] == [] and clip["missing_events"] == 0


def test_missing_prefix_and_between_snapshot_gap_are_reported_once(tmp_path):
    write(tmp_path, "a", [history_row([5, 6]), history_row([9, 10]), history_row([9, 10])])
    result = coverage(tmp_path)
    clip = result["clips"][0]
    assert result["status"] == "gaps"
    assert clip["missing_ranges"] == [[1, 4], [7, 8]] and clip["missing_events"] == 6
    assert clip["observed_events"] == 4


def test_empty_new_history_is_complete_but_legacy_history_is_unknown(tmp_path):
    write(tmp_path, "a", [history_row([])])
    assert coverage(tmp_path)["status"] == "complete"
    write(tmp_path, "b", jump(100))
    result = coverage(tmp_path)
    assert result["status"] == "unknown"
    assert result["clips"][1]["legacy_snapshots"] == len(jump(100))


@pytest.mark.parametrize("reset", [False, True])
def test_reset_or_conflicting_sequence_identity_is_unknown(tmp_path, reset):
    first, second = history_row([1, 2]), history_row([1] if reset else [1, 2])
    for event in second["input_timing"]["history"]:
        event["clock"] += 100
        event["finished_clock"] += 100
    second["capture_clock"] += 100
    write(tmp_path, "a", [first, second])
    clip = coverage(tmp_path)["clips"][0]
    assert clip["status"] == "unknown" and clip["ambiguous_lifetime"]
    assert clip["missing_ranges"] is clip["missing_events"] is None


@pytest.mark.parametrize("update", [
    {"history_limit": True}, {"history_dropped": -1}, {"history_last_sequence": 5},
    {"history": None}, {"history": [None, None]},
])
def test_invalid_history_metadata_cannot_claim_complete_coverage(tmp_path, update):
    row = history_row([1, 2])
    row["input_timing"].update(update)
    write(tmp_path, "a", [row])
    clip = coverage(tmp_path)["clips"][0]
    assert clip["status"] == "unknown" and clip["invalid_snapshots"] > 0


def test_huge_counter_uses_compact_missing_ranges(tmp_path):
    write(tmp_path, "a", [history_row([10 ** 12], limit=1)])
    clip = coverage(tmp_path)["clips"][0]
    assert clip["missing_ranges"] == [[1, 10 ** 12 - 1]]
    assert clip["missing_events"] == 10 ** 12 - 1


def test_backward_monotonic_clock_is_an_unknown_lifetime(tmp_path):
    row = history_row([1, 2])
    row["input_timing"]["history"][1].update(clock=90, finished_clock=90.002)
    write(tmp_path, "a", [row])
    clip = coverage(tmp_path)["clips"][0]
    assert clip["status"] == "unknown" and clip["ambiguous_lifetime"]
    assert clip["missing_ranges"] is None


def test_overlapping_clips_are_not_assumed_to_share_a_controller_lifetime(tmp_path):
    write(tmp_path, "a", [history_row([1, 2])])
    write(tmp_path, "b", [history_row([3, 4])])
    result = coverage(tmp_path)
    assert [clip["status"] for clip in result["clips"]] == ["complete", "gaps"]
    assert result["clips"][1]["missing_ranges"] == [[1, 2]]


def test_conflicting_event_copies_are_rejected(tmp_path):
    rows = jump(100)
    rows[0]["input_timing"]["events"] = [dispatch(100.025)]
    rows[1]["input_timing"]["events"] = [dispatch(100.025, False)]
    write(tmp_path, "a", rows)
    result = calibrate(tmp_path)["input_alignment"]
    assert result["conflicting_events"] == 1 and result["unique_events"] == 0


@pytest.mark.parametrize("update", [
    {"clock": float("nan")}, {"finished_clock": 0}, {"clock": -1},
    {"clock": True}, {"down": 1}, {"key": ""}, {"issued_at": float("inf")},
])
def test_malformed_absolute_events_cannot_align(tmp_path, update):
    rows = jump(100)
    rows[0]["input_timing"]["events"] = [dispatch(100.025) | update]
    write(tmp_path, "a", rows)
    result = calibrate(tmp_path)["input_alignment"]
    assert result["invalid_event_snapshots"] == 1 and result["unique_events"] == 0


def test_legacy_offsets_are_counted_but_never_upgraded_to_absolute_time(tmp_path):
    rows = jump(100)
    rows[0]["input_timing"]["events"] = [{"key": "space", "down": True, "at_seconds": .025}]
    write(tmp_path, "a", rows)
    result = calibrate(tmp_path)["input_alignment"]
    assert result["legacy_event_snapshots"] == 1 and result["events"] == []


@pytest.mark.parametrize("fault", ["gap", "invalid_observation", "different_player"])
def test_alignment_never_fills_missing_or_incompatible_motion(tmp_path, fault):
    rows = jump(100)
    clock = 101 if fault == "gap" else 100.025
    rows[-1]["input_timing"]["events"] = [dispatch(clock)]
    if fault == "invalid_observation":
        rows[1]["player"]["tracked"] = True
    elif fault == "different_player":
        rows[-1]["player"]["template"] = "nametag:other"
    write(tmp_path, "a", rows)
    result = calibrate(tmp_path)["input_alignment"]
    assert result["unique_events"] == 1 and result["aligned_events"] == 0
    assert result["events"][0]["observed_delta"] is None


@pytest.mark.parametrize("contradict", [False, True])
def test_harness_checks_height_constraint_and_reports_unidentified_fields(
        monkeypatch, tmp_path, contradict):
    calibration = {"schema_version": 1, "parameters": {}, "unidentified": ["gravity"],
                   "constraints": {"jump_rise_px": {"min": 10 if contradict else 78,
                                                    "max": 10 if contradict else 78,
                                                    "margin_px": 2 if contradict else 16}}}
    physics = tmp_path / "physics.json"
    physics.write_text(json.dumps(calibration), encoding="utf-8")
    output = tmp_path / "result.json"
    monkeypatch.setattr("sys.argv", ["harness", "--seeds", "1", "--physics", str(physics),
                                   "--output", str(output)])
    with pytest.raises(SystemExit) as done:
        main()
    assert done.value.code == (2 if contradict else 0)
    if contradict:
        assert not output.exists()
    else:
        report = json.loads(output.read_text("utf-8"))
        assert report["calibration"]["parameters"] == {}
        assert report["calibration"]["unidentified"] == ["gravity"]


def test_calibration_cli_refuses_to_overwrite_sources(monkeypatch, tmp_path):
    from tools.calibrate_navigation_physics import main as calibrate_main

    path = write(tmp_path, "a", jump(0))
    original = path.read_bytes()
    monkeypatch.setattr("sys.argv", ["calibrate", "--recordings", str(tmp_path),
                                   "--output", str(path)])
    with pytest.raises(SystemExit):
        calibrate_main()
    assert path.read_bytes() == original
