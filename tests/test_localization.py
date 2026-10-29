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
    MinimapTracker,
    MinimapTransform,
    Platform,
    Rope,
    SpotGeometry,
    SurfaceTracker,
    register_view,
)
from maplebot.minimap_reader import MinimapFix
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


def test_minimap_transform_fits_each_axis_and_reuses_x_scale_on_flat_walks():
    dots = [(x, 40 + x % 3) for x in range(20, 60, 2)]
    feet = [(16 * x - 500, 15 * y - 100) for x, y in dots]
    transform = MinimapTransform.fit(dots, feet)
    assert transform.to_area(30, 41) == pytest.approx((-20, 515))
    flat = MinimapTransform.fit([(x, 45) for x, _ in dots], [(16 * x - 500, 593) for x, _ in dots])
    assert flat.scale_y == pytest.approx(16) and flat.to_area(30, 45)[1] == pytest.approx(593)
    with pytest.raises(ValueError, match="Walk further"):
        MinimapTransform.fit([(20, 45)] * 12, [(0, 593)] * 12)


def fix(x=40.0, y=45.0):
    return MinimapFix((x, y), Rect(13, 72, 183, 64), 0.97, 1, "Player marker on the taught map")


@pytest.fixture
def fused():
    return MinimapTracker(MinimapTransform(16, -500, 16, -127),
                          (Platform("floor", 0, 1300, 593),))


def test_fused_platform_needs_agreeing_marker_and_tag_for_150_ms(fused):
    assert fused.update(fix(), player(600, 480), (0, 0), 1.0).reason.startswith("Waiting")
    first = fused.update(fix(41), player(600, 480), (-16, 0), 1.1)
    assert first.kind == "unknown" and first.reference_feet == (156, 593)
    assert fused.update(fix(42), player(600, 480), (-16, 0), 1.2).kind == "unknown"
    located = fused.update(fix(43), player(600, 480), (-16, 0), 1.3)
    assert (located.kind, located.surface_id) == ("platform", "floor")


@pytest.mark.parametrize(("threshold", "confidence", "tracked", "kind"), [
    (.85, .875421, False, "platform"), (.90, .875421, False, "unknown"),
    (.85, .849, False, "unknown"), (.85, .875421, True, "unknown"),
])
def test_fused_tracking_uses_configured_player_threshold(threshold, confidence, tracked, kind):
    tracker = MinimapTracker(MinimapTransform(16, -500, 16, -127),
                             (Platform("floor", 0, 1300, 593),), player_threshold=threshold)
    for now in (1.0, 1.2, 1.4):
        location = tracker.update(fix(), player(600, 480, confidence=confidence, tracked=tracked),
                                   (0, 0), now)
    assert location.kind == kind


@pytest.mark.parametrize(("marker", "tag", "shift", "reason"), [
    (fix(41), player(600, 480), (40, 0), "disagree"),
    (fix(40, 44), player(600, 470), (0, 0), "Moving vertically"),
    (fix(40), player(600, 480, tracked=True), (0, 0), "Name tag missing"),
    (MinimapFix(None, None, 0.4, 0, "Minimap missing, covered or showing another map"),
     player(600, 480), (0, 0), "Minimap missing"),
])
def test_fused_location_is_unknown_without_agreement(fused, marker, tag, shift, reason):
    for now in (1.0, 1.2, 1.4):
        fused.update(fix(), player(600, 480), (0, 0), now)
    location = fused.update(marker, tag, shift, 1.6)
    assert location.kind == "unknown" and reason in location.reason
    # Only a name-tag miss keeps the platform being confirmed; real disagreement restarts it.
    after = "platform" if reason == "Name tag missing" else "unknown"
    assert fused.update(fix(), player(600, 480), (0, 0), 1.8).kind == after


@pytest.mark.parametrize(("dot", "kind"), [(70, "platform"), (72, "unknown")])
def test_two_marker_pixels_past_a_walked_end_still_mean_that_ledge(dot, kind):
    tracker = MinimapTracker(MinimapTransform(16, -500, 16, -127),
                             (Platform("ledge", 300, 588, 593),))
    for now in (1.0, 1.1, 1.3):
        location = tracker.update(fix(dot), player(600, 480), (0, 0), now)
    assert location.kind == kind  # dot 70 is 32 px past the end; dot 72 is 64 px


def test_stale_fused_observation_starts_over(fused):
    for now in (1.0, 1.2, 1.4):
        fused.update(fix(), player(600, 480), (0, 0), now)
    assert fused.update(fix(), player(600, 480), (0, 0), 2.6).reason.startswith("Waiting")


def test_register_view_finds_camera_offset_and_rejects_featureless_frames():
    noise = np.random.default_rng(5).integers(0, 255, (96, 171, 3), dtype=np.uint8)
    reference = cv2.resize(noise, (1366, 768), interpolation=cv2.INTER_LINEAR)
    shifted = np.zeros_like(reference)
    shifted[:, 37:] = reference[:, :-37]
    assert register_view(reference, shifted) == (-37, 0)
    assert register_view(reference, np.zeros_like(reference)) is None
    assert register_view(reference, shifted[:700]) is None


def test_platform_height_follows_its_bends():
    from maplebot.localization import Platform

    ledge = Platform("p", 50, 200, 440, 400, ((50, 440), (90, 400), (200, 400)))
    assert ledge.y_at(70) == 420 and ledge.y_at(150) == 400
    assert Platform("q", 0, 100, 10, 30).y_at(50) == 20


def test_a_one_frame_name_tag_miss_does_not_restart_platform_confirmation(fused):
    for now in (1.0, 1.2, 1.4):
        fused.update(fix(), player(600, 480), (0, 0), now)
    assert fused.update(fix(), None, (0, 0), 1.6).reason.startswith("Name tag missing")
    assert fused.update(fix(), player(600, 480), (0, 0), 1.8).kind == "platform"

def test_fused_rope_origin_requires_unique_stable_agreement():
    from maplebot.localization import Rope
    tracker = MinimapTracker(MinimapTransform(1, 0, 1, 0), (),
                             ropes=(Rope("r", 50, 0, 200),))
    for now in (1, 1.2, 1.6):
        location = tracker.update(fix(50), player(600, 480), (0, 0), now)
    assert location.kind == "rope" and location.surface_id == "r"
    assert tracker.update(fix(50), None, (0, 0), 1.8).kind == "unknown"
    tracker.ropes = (Rope("r", 50, 0, 200), Rope("s", 51, 0, 200))
    assert tracker.update(fix(50), player(600, 480), (0, 0), 2).kind == "unknown"
