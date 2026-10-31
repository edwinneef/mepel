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
