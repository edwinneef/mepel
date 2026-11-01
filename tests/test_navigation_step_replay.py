import json
from dataclasses import replace

import pytest
from test_navigation_executor import setup

from maplebot.navigation_replay import recorded_step, replay


def write(tmp_path, records):
    (tmp_path / "decisions.jsonl").write_text("\n".join(
        json.dumps({"sequence": i, "navigation_step": r}, allow_nan=False)
        for i, r in enumerate(records)), encoding="utf-8")


@pytest.mark.parametrize("fault", [{}, {"focused": False}, {"age": 1},
                                  {"fingerprint": "changed"}, {"feet": None},
                                  {"motion_ok": False}])
def test_roundtrip_release_and_failures(tmp_path, fault):
    nav, feedback = setup()
    records = []
    for now in (0, .2, .4, .6):
        _, row = recorded_step(nav, replace(feedback, now=now))
        records.append(row)
    _, row = recorded_step(nav, replace(feedback, now=.8, **fault))
    records.append(row)
    write(tmp_path, records)
    assert replay(tmp_path)["differences"] == []
    if fault:
        assert nav.stage == "stopped" and row["motion"]["release"]


def test_detects_changed_motion_and_state(tmp_path):
    nav, feedback = setup()
    _, row = recorded_step(nav, feedback)
    row["motion"]["release"] = False
    row["after"]["state"]["stage"] = "arrived"
    write(tmp_path, [row])
    assert replay(tmp_path)["differences"][0]["fields"] == ["motion", "state"]


def test_legacy_recording_is_not_a_pass(tmp_path):
    write(tmp_path, [None])
    with pytest.raises(ValueError, match="No Navigator"):
        replay(tmp_path)


def test_duplicate_step_is_rejected(tmp_path):
    nav, feedback = setup()
    _, row = recorded_step(nav, feedback)
    write(tmp_path, [row, row])
    with pytest.raises(ValueError, match="increasing"):
        replay(tmp_path)


def test_arrival_roundtrip(tmp_path):
    nav, f = setup()
    records = []
    for now in (0, .2, .4, .6, .8, 1, 1.2, 1.4):
        feedback = replace(f, now=now)
        if now == .8:
            feedback = replace(feedback, feet=(220, 260), surface=None)
        elif now >= 1:
            feedback = replace(feedback, feet=(280, 300), surface="ledge")
        _, row = recorded_step(nav, feedback)
        records.append(row)
    assert nav.stage == "arrived"
    write(tmp_path, records)
    assert replay(tmp_path)["differences"] == []
