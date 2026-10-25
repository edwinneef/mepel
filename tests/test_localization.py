import json
import runpy
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from maplebot.geometry import Rect
from maplebot.localization import (
    Alignment,
    AnchorMatcher,
    Platform,
    Rope,
    SpotGeometry,
    SurfaceTracker,
)
from maplebot.perception import Detection


@pytest.fixture
def scene():
    frame = np.random.default_rng(24).integers(0, 255, (100, 160, 3), dtype=np.uint8)
    boxes = (Rect(15, 15, 12, 12), Rect(110, 15, 12, 12))
    return frame, boxes


def player(x=60, feet=70, **kwargs):
    return Detection("player", Rect(x - 5, feet - 20, 10, 20), **{"confidence": 1, **kwargs})


def tracker():
    return SurfaceTracker(SpotGeometry(
        160, 100, (Platform("upper", 0, 160, 30), Platform("lower", 0, 160, 70)),
        (Rope("ladder", 100, 30, 70),),
    ))


def test_anchor_translation_is_absolute_not_accumulated(scene):
    frame, boxes = scene
    matcher = AnchorMatcher(frame, boxes)
    for dx, dy in [(8, 4), (-4, 10), (0, 0)]:
        shifted = cv2.warpAffine(frame, np.float32([[1, 0, dx], [0, 1, dy]]), (160, 100))
        result = matcher.match(shifted)
        assert result.offset == (dx, dy)
        assert result.matches == 2


def test_duplicate_anchor_matches_are_unknown(scene):
    frame, boxes = scene
    matcher = AnchorMatcher(frame, boxes)
    duplicated = frame.copy()
    for index, box in enumerate(boxes):
        duplicated[45:57, 15 + index * 70:27 + index * 70] = (
            frame[box.y:box.y + box.height, box.x:box.x + box.width]
        )
    assert matcher.match(duplicated).offset is None


def test_anchor_disagreement_loss_and_capture_resize_are_unknown(scene):
    frame, boxes = scene
    matcher = AnchorMatcher(frame, boxes)
    altered = frame.copy()
    box = boxes[0]
    altered[45:57, 35:47] = frame[box.y:box.y + box.height, box.x:box.x + box.width]
    altered[box.y:box.y + box.height, box.x:box.x + box.width] = 0
    assert matcher.match(altered).reason == "Spot anchors disagree"
    assert matcher.match(np.zeros_like(frame)).offset is None
    assert matcher.match(frame[:90]).reason == "Capture size changed"


def test_invalid_anchor_teaching_is_rejected(scene):
    frame, boxes = scene
    for invalid in [(boxes[0],), (boxes[0], boxes[0]), (Rect(155, 90, 12, 12), boxes[0])]:
        with pytest.raises(ValueError):
            AnchorMatcher(frame, invalid)
    with pytest.raises(ValueError, match="textured"):
        AnchorMatcher(np.zeros_like(frame), boxes)


def test_camera_motion_preserves_reference_platform():
    localizer = tracker()
    first = localizer.update(player(), Alignment((0, 0), 2, "ok"), 0)
    assert first.kind == "unknown"
    moved = localizer.update(player(x=80, feet=80), Alignment((20, 10), 2, "ok"), 0.3)
    assert moved.surface_id == "lower"
    assert moved.reference_feet == (60, 70)


def test_knock_off_drops_old_platform_and_reacquires_actual_location():
    localizer = tracker()
    aligned = Alignment((0, 0), 2, "ok")
    localizer.update(player(), aligned, 0)
    assert localizer.update(player(), aligned, 0.3).surface_id == "lower"
    assert localizer.update(player(feet=50), aligned, 0.6).kind == "unknown"
    assert localizer.update(player(feet=30), aligned, 0.9).kind == "unknown"
    assert localizer.update(player(feet=30), aligned, 1.2).surface_id == "upper"


@pytest.mark.parametrize("bad_player", [None, player(tracked=True), player(confidence=0.5)])
def test_missing_weak_and_tracked_only_players_invalidate_location(bad_player):
    localizer = tracker()
    aligned = Alignment((0, 0), 2, "ok")
    localizer.update(player(), aligned, 0)
    assert localizer.update(player(), aligned, 0.3).surface_id == "lower"
    assert localizer.update(bad_player, aligned, 0.6).kind == "unknown"
    assert localizer.update(player(), aligned, 0.9).kind == "unknown"


def test_rope_proximity_does_not_claim_attachment_and_platform_wins_at_end():
    localizer = tracker()
    aligned = Alignment((0, 0), 2, "ok")
    localizer.update(player(x=100, feet=50), aligned, 0)
    assert localizer.update(player(x=100, feet=50), aligned, 0.3).kind == "near_rope"
    localizer.update(player(x=100, feet=30), aligned, 0.6)
    result = localizer.update(player(x=100, feet=30), aligned, 0.9)
    assert (result.kind, result.surface_id) == ("platform", "upper")


def test_anchor_loss_and_long_frame_gap_require_new_confirmation():
    localizer = tracker()
    aligned = Alignment((0, 0), 2, "ok")
    localizer.update(player(), aligned, 0)
    localizer.update(player(), aligned, 0.3)
    assert localizer.update(player(), Alignment(None, 0, "Lost anchors"), 0.6).kind == "unknown"
    assert localizer.update(player(), aligned, 0.9).kind == "unknown"
    assert localizer.update(player(), aligned, 1.2).surface_id == "lower"
    assert localizer.update(player(), aligned, 3).kind == "unknown"


def test_one_anchor_cannot_assign_a_surface_and_confirmation_uses_capture_time():
    localizer = tracker()
    assert localizer.update(player(), Alignment((0, 0), 1, "single"), 0).kind == "unknown"
    aligned = Alignment((0, 0), 2, "ok")
    assert localizer.update(player(), aligned, 0.1).kind == "unknown"
    assert localizer.update(player(), aligned, 0.2).kind == "unknown"
    assert localizer.update(player(), aligned, 0.3).surface_id == "lower"


def test_ambiguous_surfaces_are_unknown_and_invalid_geometry_is_rejected():
    geometry = SpotGeometry(160, 100, (Platform("a", 0, 160, 70), Platform("b", 0, 160, 75)))
    result = SurfaceTracker(geometry).update(player(), Alignment((0, 0), 2, "ok"), 0)
    assert result.reason == "No unique taught surface"
    with pytest.raises(ValueError, match="unique"):
        replace(geometry, platforms=(geometry.platforms[0], geometry.platforms[0]))
    with pytest.raises(ValueError, match="outside"):
        SpotGeometry(160, 100, (Platform("a", 20, 10, 70),))


@pytest.mark.parametrize("bad_time", [0, -1, float("nan"), float("inf")])
def test_nonincreasing_or_invalid_capture_time_is_rejected(bad_time):
    localizer = tracker()
    aligned = Alignment((0, 0), 2, "ok")
    localizer.update(player(), aligned, 0)
    with pytest.raises(ValueError, match="Capture time"):
        localizer.update(player(), aligned, bad_time)


def test_probe_replays_saved_frames_without_changing_source(scene, tmp_path, monkeypatch, capsys):
    frame, boxes = scene
    recording = tmp_path / "recording"
    recording.mkdir()
    rows = []
    for index in range(3):
        name = f"{index:08d}.png"
        if index < 2:
            cv2.imwrite(str(recording / name), frame)
        rows.append({
            "frame": name, "sequence": index,
            "policy_input": {
                "now": index * 0.3, "last_outcome": {},
                "observation": {
                    "player": {"kind": "player", "box": {
                        "x": 55, "y": 50, "width": 10, "height": 20,
                    }, "confidence": 1}, "monsters": [],
                },
            },
        })
    log = recording / "decisions.jsonl"
    log.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    original = {path.name: path.read_bytes() for path in recording.iterdir()}
    layout = tmp_path / "layout.json"
    layout.write_text(json.dumps({
        "version": 1, "reference": "00000000.png",
        "anchors": [vars(box) for box in boxes],
        "platforms": [{"id": "floor", "left": 0, "right": 160, "y": 70}],
    }), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setattr("sys.argv", [
        "localization_probe", str(recording), "--layout", str(layout), "--output", str(output),
    ])
    script = Path(__file__).resolve().parents[1] / "tools/localization_probe.py"
    runpy.run_path(str(script), run_name="__main__")
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["input_sent"] is False
    assert metrics["accuracy"] is None
    assert metrics["locations"] == {"unknown": 2, "platform": 1}
    assert {path.name: path.read_bytes() for path in recording.iterdir()} == original
    repeat = tmp_path / "repeat"
    monkeypatch.setattr("sys.argv", [
        "localization_probe", str(recording), "--layout", str(layout), "--output", str(repeat),
    ])
    runpy.run_path(str(script), run_name="__main__")
    capsys.readouterr()
    assert (repeat / "locations.jsonl").read_bytes() == (output / "locations.jsonl").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        runpy.run_path(str(script), run_name="__main__")
