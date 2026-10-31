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
