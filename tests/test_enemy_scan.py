"""Wide scanning never changes recognition or gameplay eligibility thresholds."""

from dataclasses import asdict

import cv2
import numpy as np

from maplebot.combat_readiness import summarize
from maplebot.config import Config, PerceptionConfig
from maplebot.perception import TemplateDetector


def test_wide_scan_finds_outside_roi_and_preserves_player(tmp_path, monkeypatch):
    rng = np.random.default_rng(903)
    sprites = [rng.integers(20, 240, (28, 24, 3), dtype=np.uint8) for _ in range(2)]
    for kind, sprite in zip(("player", "monster"), sprites, strict=True):
        (tmp_path / kind).mkdir()
        cv2.imwrite(str(tmp_path / kind / "pose.png"), sprite)
    frame = np.full((500, 1100, 3), 30, dtype=np.uint8)
    frame[350:378, 500:524] = sprites[0]
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    try:
        first = detector.detect(frame, 0)
        assert first.player is not None
        # One high-confidence enemy is outside the local window; another is on another floor.
        frame[350:378, 1000:1024] = sprites[1]
        frame[100:128, 650:674] = sprites[1]
        for index, now in enumerate((.1, .2, .3)):
            observation = detector.detect(frame, now)
            evidence = summarize({"frame": {"available": True, "captured_at": now},
                                  "player": asdict(observation.player),
                                  "monsters": [asdict(x) for x in observation.monsters]},
                                 Config(), now)
            assert not evidence["same_platform_targets"]
            detector.enemy_scan_feedback(str(index), fresh=evidence["fresh_player"],
                                         eligible=False)
        wide = detector.detect(frame, .4)
        assert detector.enemy_scan_stage == "wide"
        assert wide.player.box == first.player.box
        assert any(x.box.x == 1000 and x.confidence > .99 for x in wide.monsters)
        detector.detect(frame, .5)
        assert detector.enemy_scan_stage == "local"
        detector.detect(frame, 1.41)
        assert detector.enemy_scan_stage == "wide"
        detector.enemy_scan_feedback("target", fresh=True, eligible=True)
        detector.detect(frame, 2.5)
        assert detector.enemy_scan_stage == "local"
        detector.enemy_empty_observations = 3
        detector.enemy_source = "new session"
        detector.detect(frame, 3.5)
        assert detector.enemy_scan_stage == "local"
        assert detector.enemy_empty_observations == 0
        detector.enemy_empty_observations = 3
        monkeypatch.setattr(detector.map_filter, "select", lambda image, taught: None)
        detector.map_filter.title = "another map"
        detector.detect(frame, 4.5)
        assert detector.enemy_scan_stage == "local"
        assert detector.enemy_empty_observations == 0
        detector.enemy_empty_observations = 3
        detector.reload()
        detector.detect(frame, 5.5)
        assert detector.enemy_scan_stage == "local"
        assert detector.enemy_empty_observations == 0
    finally:
        detector.pool.shutdown()
        detector.map_filter.close()


def test_feedback_rejects_duplicate_and_stale_observations(tmp_path):
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    try:
        detector.enemy_scan_feedback("one", fresh=True, eligible=False)
        detector.enemy_scan_feedback("one", fresh=True, eligible=False)
        assert detector.enemy_empty_observations == 1
        detector.enemy_scan_feedback("two", fresh=False, eligible=False)
        assert detector.enemy_empty_observations == 0
    finally:
        detector.pool.shutdown()
        detector.map_filter.close()


