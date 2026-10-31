import json
import os
import time

import pytest

from maplebot.config import RecordingConfig
from maplebot.recorder import SessionRecorder


@pytest.fixture
def recorder(tmp_path):
    config = RecordingConfig(buffer_seconds=1, keyframe_seconds=0, post_seconds=0.5)
    recorder = SessionRecorder(tmp_path, config, fps=4)
    yield recorder
    recorder.close()


def flush(recorder):
    deadline = time.monotonic() + 3
    while not recorder.jobs.empty() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)


def feed(recorder, start, count, now=0.0):
    for index in range(start, start + count):
        recorder.observe(f"{index:08d}", b"png", {"captured_at": index}, now)


def test_session_logs_every_decision_but_saves_no_frames_without_incident(recorder):
    path = recorder.start("dry-run")
    feed(recorder, 0, 10)
    flush(recorder)
    assert len((path / "decisions.jsonl").read_text("utf-8").splitlines()) == 10
    assert not list(path.glob("*.png"))


def test_recording_preserves_absolute_key_clocks_and_legacy_events(recorder):
    path = recorder.start("offline-clock-test")
    events = [{"key": "right", "down": True, "at_seconds": .25, "clock": 100.25,
               "finished_clock": 100.251, "issued_at": 1800000000.5},
              {"key": "right", "down": False, "at_seconds": .37, "clock": 100.37,
               "finished_clock": 100.371, "issued_at": 1800000000.62}]
    recorder.observe("00000000", b"png", {"capture_clock": 100.4,
                     "input_timing": {"events": events}}, 0)
    recorder.observe("00000001", b"png", {"input_timing": {"events": [
        {"key": "right", "down": True, "at_seconds": .25}]}}, .1)
    recorder.close()
    rows = [json.loads(line) for line in (path / "decisions.jsonl").read_text().splitlines()]
    assert rows[0]["input_timing"]["events"] == events
    assert rows[0]["capture_clock"] - events[0]["clock"] == pytest.approx(.15)
    assert "clock" not in rows[1]["input_timing"]["events"][0]


def test_trigger_flushes_buffer_then_records_post_window_and_closes(recorder):
    path = recorder.start("combat")
    feed(recorder, 0, 10)
    recorder.trigger("Player detection uncertain", now=0.0)
    feed(recorder, 10, 2, now=0.1)
    feed(recorder, 12, 1, now=1.0)
    recorder.trigger("Operator stopped the agent", now=1.0, close=True)
    flush(recorder)
    frames = sorted(item.stem for item in path.glob("*.png"))
    # Buffer holds 4 frames (1 s at 4 fps); post window covers frames 10-11.
    assert frames == [f"{index:08d}" for index in range(6, 13)]
    events = (path / "events.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(line)["reason"] for line in events] == [
        "Player detection uncertain",
        "Operator stopped the agent",
    ]
    assert not recorder.active


def test_clip_without_session_writes_buffered_frames_and_decisions(recorder):
    feed(recorder, 0, 6)
    path = recorder.trigger("Operator saved clip", now=0.0)
    flush(recorder)
    assert not recorder.active
    assert len(list(path.glob("*.png"))) == 4
    lines = (path / "decisions.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(line)["frame"] for line in lines] == [
        f"{index:08d}.png" for index in range(2, 6)
    ]


def test_full_mode_and_keyframes(tmp_path):
    recorder = SessionRecorder(tmp_path, RecordingConfig(keyframe_seconds=1.0), fps=4)
    try:
        path = recorder.start("combat")
        for index in range(8):
            recorder.observe(f"{index:08d}", b"png", {}, index * 0.25)
        recorder.full = True
        recorder.observe("00000008", b"png", {}, 2.1)
        flush(recorder)
        assert sorted(item.stem for item in path.glob("*.png")) == [
            "00000000",
            "00000004",
            "00000008",
        ]
    finally:
        recorder.close()


def test_slow_writer_drops_frames_instead_of_blocking(recorder):
    recorder.config = RecordingConfig(keyframe_seconds=0, max_queue_frames=1)
    recorder.start("combat")
    recorder.pending = 1
    feed(recorder, 0, 4)
    recorder.trigger("incident", now=0.0)
    assert recorder.dropped == 4
    recorder.pending = 0


def test_new_session_prunes_old_and_oversized_sessions(tmp_path):
    old = tmp_path / "session-1-combat"
    big = tmp_path / "session-2-combat"
    recent = tmp_path / "session-3-combat"
    other = tmp_path / "keep-me"
    for directory, size in ((old, 10), (big, 2 * 1024 * 1024), (recent, 10), (other, 10)):
        directory.mkdir()
        (directory / "frame.png").write_bytes(b"x" * size)
    os.utime(old, (0, 0))
    os.utime(big, (time.time() - 60, time.time() - 60))
    recorder = SessionRecorder(tmp_path, RecordingConfig(max_total_mb=1, max_age_days=1), fps=4)
    try:
        current = recorder.start("dry-run")
        flush(recorder)
        assert not old.exists() and not big.exists()
        assert recent.exists() and other.exists() and current.exists()
    finally:
        recorder.close()


def test_close_waits_for_the_stopping_frame_and_logs_pre_roll(recorder):
    feed(recorder, 0, 2)
    path = recorder.start("dry-run")
    recorder.trigger("No confident same-platform targets; stopped", now=0.0, close=True)
    assert not recorder.active
    feed(recorder, 2, 1)
    feed(recorder, 3, 1)
    flush(recorder)
    assert recorder.path is None
    lines = (path / "decisions.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(line)["frame"] for line in lines] == [
        "00000000.png",
        "00000001.png",
        "00000002.png",
    ]
    assert sorted(item.stem for item in path.glob("*.png")) == [
        "00000000",
        "00000001",
        "00000002",
    ]


def test_timed_full_recording_saves_every_frame_then_stops_by_itself(recorder):
    # Frame times are session-relative (near zero); the deadline must not depend on them.
    path = recorder.start_full(seconds=0.3)
    assert 0 < recorder.snapshot()["full_remaining"] <= 0.3
    feed(recorder, 0, 3, now=0.0)
    time.sleep(0.35)
    recorder.observe("00000003", b"png", {}, 0.1)
    assert not recorder.active and not recorder.full
    recorder.observe("00000004", b"png", {}, 0.2)
    flush(recorder)
    assert recorder.path is None
    assert sorted(item.stem for item in path.glob("*.png")) == ["00000000", "00000001", "00000002"]
    lines = (path / "decisions.jsonl").read_text("utf-8").splitlines()
    assert json.loads(lines[-1])["frame"] == "00000003.png"
