import json
from dataclasses import asdict, replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from maplebot.config import AgentConfig, PerceptionConfig
from maplebot.decision import Agent
from maplebot.enemy_tracking import EnemyTracker
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation, TemplateDetector


def enemy(x, *, name="Snail", y=100):
    return Detection("monster", Rect(x, y - 30, 40, 30), .99, f"catalog:{name}:move-0")


def tick(tracker, now, detections=(), shift=(0, 0), confidence=1):
    tracker.prepare(now, shift, confidence)
    return tracker.update(list(detections), now)


def test_hidden_reversal_reassociates_original_id_with_growing_uncertainty():
    tracker = EnemyTracker(PerceptionConfig())
    tracker.regions = (Rect(80, 60, 180, 50),)
    first = tick(tracker, 0, [enemy(80)])[0].track_id
    tick(tracker, .2, [enemy(90)])
    tick(tracker, .4)
    before = tracker.snapshot()[0]
    tick(tracker, .8)
    hidden = tracker.snapshot()[0]
    assert hidden.state == "occluded" and not hidden.observed
    assert hidden.visible_bounds is None
    assert hidden.uncertainty[0] > before.uncertainty[0]
    assert hidden.confidence < before.confidence
    assert tick(tracker, 1, [enemy(75)])[0].track_id == first
    assert tracker.snapshot()[0].state == "visible"


def test_occluded_expiry_lost_state_and_no_indefinite_partial_refresh():
    tracker = EnemyTracker(PerceptionConfig(enemy_occlusion_seconds=1))
    tracker.regions = (Rect(60, 50, 180, 60),)
    tick(tracker, 0, [enemy(80)])
    track_id = tracker.snapshot()[0].track_id
    tracker.prepare(.8, (0, 0), 1)
    tracker.update([], .8, [(track_id, replace(enemy(80), tracked=True))])
    tick(tracker, 1.1)
    assert tracker.snapshot()[0].state == "lost"
    tick(tracker, 2)
    assert tracker.snapshot() == []
    assert tick(tracker, 2.1, [enemy(80)])[0].track_id != track_id


def test_unexplained_misses_expire_quickly_and_time_reset_clears_identity():
    tracker = EnemyTracker(PerceptionConfig())
    first = tick(tracker, 0, [enemy(80)])[0].track_id
    tick(tracker, .2)
    assert tracker.snapshot()[0].state == "lost"
    tick(tracker, .6)
    assert not tracker.snapshot()
    second = tick(tracker, .7, [enemy(80)])[0].track_id
    assert first != second
    assert tick(tracker, .1, [enemy(80)])[0].track_id != second


def test_camera_compensation_precedes_matching_and_moves_platforms_and_regions():
    tracker = EnemyTracker(PerceptionConfig())
    tracker.regions = (Rect(80, 50, 180, 50),)
    tracker.platforms = ((50, 100, 350, 130),)
    first = tick(tracker, 0, [enemy(80, y=105)])[0].track_id
    assert tick(tracker, .1, [enemy(0, y=111)], (-80, 6))[0].track_id == first
    assert tracker.regions[0].x == 0
    assert tracker.snapshot()[0].ground_position[1] == pytest.approx(111)
    assert abs(tracker.tracks[0].velocity) < 1
    before = tracker.snapshot()[0].uncertainty
    tick(tracker, .2, shift=(1000, 1000), confidence=0)
    assert tracker.snapshot()[0].uncertainty[0] > before[0]


def test_prediction_stops_at_known_platform_edge_without_claiming_a_reversal():
    tracker = EnemyTracker(PerceptionConfig())
    tracker.platforms = ((80, 100, 160, 100),)
    tracker.regions = (Rect(80, 50, 100, 60),)
    tick(tracker, 0, [enemy(100)])
    tick(tracker, .1, [enemy(110)])
    tick(tracker, .8)
    assert tracker.snapshot()[0].ground_position[0] == 160
    assert tracker.snapshot()[0].uncertainty[0] > 50
    assert not tracker.snapshot()[0].observed


def test_multiple_enemies_types_and_ambiguous_overlap_do_not_duplicate_tracks():
    tracker = EnemyTracker(PerceptionConfig())
    initial = tick(tracker, 0, [enemy(80), enemy(160), enemy(250, name="Pig")])
    ids = [item.track_id for item in initial]
    assert len(set(ids)) == 3
    moved = tick(tracker, .1, [enemy(85), enemy(155), enemy(245, name="Pig")])
    assert [item.track_id for item in moved] == ids
    merged = tick(tracker, .3, [enemy(120), enemy(245, name="Pig")])
    assert merged[0].track_id is None  # An unresolved crossing is not a new enemy.
    assert len(tracker.tracks) == 3
    assert merged[1].track_id == ids[2]


def test_prediction_is_never_fresh_attack_evidence():
    tracker = EnemyTracker(PerceptionConfig())
    tracker.regions = (Rect(80, 50, 180, 60),)
    tick(tracker, 0, [enemy(140)])
    assert tick(tracker, .1) == []
    player = Detection("player", Rect(80, 50, 30, 50), 1)
    agent = Agent(AgentConfig())
    agent.start()
    decision = agent.step(Observation(player, [], enemy_tracks=tracker.snapshot()), .1)
    assert decision.target is None and decision.action.kind == "release"


def test_reference_geometry_partial_pixels_and_camera_translation(tmp_path):
    """Deterministic screenshot sequence; synthetic textures, not native-game accuracy."""
    rng = np.random.default_rng(7)
    background = rng.integers(20, 100, (220, 360, 3), dtype=np.uint8)
    sprite = rng.integers(20, 240, (30, 40, 3), dtype=np.uint8)
    (tmp_path / "monster").mkdir()
    rgba = np.dstack((sprite, np.full((30, 40), 255, np.uint8)))
    cv2.imwrite(str(tmp_path / "monster/snail.png"), rgba)
    cv2.imwrite(str(tmp_path / "reference.png"), background)
    (tmp_path / "enemy-occlusion.json").write_text(json.dumps({"Test": {
        "reference": "reference.png", "regions": [[90, 65, 160, 31]],
        "platforms": [[30, 100, 330, 100]],
    }}))
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    detector.map_filter.select = lambda *_: None
    detector.map_filter.title = "Test"

    def frame(x, covered=False, scroll=0):
        image = background.copy()
        image[70:100, x:x + 40] = sprite
        if covered:
            image[65:96, 90:250] = (35, 65, 110)
        return cv2.warpAffine(image, np.float32([[1, 0, scroll], [0, 1, 0]]), (360, 220))

    first = detector.detect(frame(100), 0)
    assert len(first.monsters) == 1
    track_id = first.monsters[0].track_id
    partial = detector.detect(frame(104, True), .1)
    assert partial.monsters == []
    assert partial.enemy_tracks[0].state == "partially_occluded"
    assert partial.enemy_tracks[0].visible_bounds.height <= 4
    assert partial.enemy_tracks[0].ground_position[1] == pytest.approx(100, abs=.01)
    moved = detector.detect(frame(106, True, -20), .2)
    assert moved.enemy_tracks[0].track_id == track_id
    assert moved.enemy_tracks[0].state == "partially_occluded"
    assert moved.enemy_tracks[0].ground_position[0] == pytest.approx(106, abs=2)
    emerged = detector.detect(frame(100, False, -20), .3)
    assert emerged.monsters[0].track_id == track_id
    assert emerged.enemy_tracks[0].state == "visible"
    assert json.dumps(asdict(emerged))
    detector.enemy_source = "new capture source"
    changed = detector.detect(frame(100), .4)
    assert changed.monsters[0].track_id != track_id
    paused = detector.detect(frame(100), .5, monsters=False)
    assert paused.monsters == [] and paused.enemy_tracks == []
    detector.pool.shutdown(wait=True)
    detector.map_filter.close()


@pytest.mark.parametrize("value", [0, -1, float("nan"), 11])
def test_invalid_retention_config_rejected(value):
    with pytest.raises(ValueError, match="enemy_occlusion_seconds"):
        PerceptionConfig(enemy_occlusion_seconds=value)


@pytest.mark.parametrize("scenario", ["partial", "reversal", "camera", "multiple"])
def test_recorded_artwork_sequences(tmp_path, scenario):
    """Controlled composites of saved game pixels: known positions, no live input."""
    fixture = Path(__file__).parent / "fixtures/enemy-occlusion"
    scene = cv2.imread(str(fixture / "bridge-scene.png"))
    rgba = cv2.imread(str(fixture / "blue-snail.png"), cv2.IMREAD_UNCHANGED)
    (tmp_path / "monster").mkdir()
    cv2.imwrite(str(tmp_path / "monster/snail.png"), rgba)
    cv2.imwrite(str(tmp_path / "reference.png"), scene)
    (tmp_path / "enemy-occlusion.json").write_text(json.dumps({"Bridge": {
        "reference": "reference.png", "regions": [[44, 45, 205, 51]],
        "platforms": [[0, 103, 319, 103]],
    }}))
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    detector.map_filter.select = lambda *_: None
    detector.map_filter.title = "Bridge"

    def frame(positions, cover=False, scroll=0):
        image = scene.copy()
        h, w = rgba.shape[:2]
        for x in positions:
            region = image[103 - h:103, x:x + w]
            region[rgba[:, :, 3] > 0] = rgba[:, :, :3][rgba[:, :, 3] > 0]
        if cover:
            image[45:96, 44:249] = scene[45:96, 44:249]
        return cv2.warpAffine(image, np.float32([[1, 0, scroll], [0, 1, 0]]), (320, 140))

    positions = [60, 190] if scenario == "multiple" else [80]
    first = detector.detect(frame(positions), 0)
    ids = {item.track_id for item in first.monsters}
    assert len(ids) == len(positions) and None not in ids
    if scenario == "partial":
        partial = detector.detect(frame([83], True), .1)
        assert partial.monsters == []
        assert partial.enemy_tracks[0].state == "partially_occluded"
        # Remove the enemy; unchanged foreground pixels cannot refresh its evidence.
        missing = detector.detect(frame([], True), .2)
        assert missing.enemy_tracks[0].state == "occluded"
        assert missing.enemy_tracks[0].last_seen == .1
    else:
        # Full occlusion: no enemy pixels, then a reversal/scroll/two-enemy emergence.
        second = detector.detect(frame([p + 4 for p in positions]), .1)
        assert {item.track_id for item in second.monsters} == ids
        hidden = detector.detect(frame([], True), .3)
        assert {t.state for t in hidden.enemy_tracks} == {"occluded"}
        scroll = -18 if scenario == "camera" else 0
        emerged = detector.detect(frame([p - 3 for p in positions], scroll=scroll), .5)
        assert {item.track_id for item in emerged.monsters} == ids
        assert len(emerged.enemy_tracks) == len(positions)
    detector.pool.shutdown(wait=True)
    detector.map_filter.close()
