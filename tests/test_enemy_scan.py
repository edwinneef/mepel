"""Tile scanning never changes recognition or gameplay eligibility thresholds."""

from dataclasses import asdict

import cv2
import numpy as np

from maplebot.combat_readiness import summarize
from maplebot.config import Config, PerceptionConfig
from maplebot.perception import TemplateDetector


def test_tiles_find_outside_roi_enemies_and_preserve_player(tmp_path, monkeypatch):
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
        assert detector.enemy_scan_stage == "local"  # A whole-frame search needs no tiles.
        # One high-confidence enemy is outside the local window; another is on another floor.
        frame[350:378, 1000:1024] = sprites[1]
        frame[100:128, 650:674] = sprites[1]
        stages, found = [], set()
        for step in range(8):  # At most one full cycle of grid cells.
            observation = detector.detect(frame, .1 * (step + 1))
            assert observation.player.box == first.player.box
            assert detector.search_window is not None  # the local window never widens
            stages.append(detector.enemy_scan_stage)
            cell = observation.player_tracking["enemy_cell"]
            assert cell is not None and cell == {**cell, **vars(detector.enemy_cell)}
            found |= {(x.box.x, x.box.y) for x in observation.monsters if x.confidence > .99}
        assert {(1000, 350), (650, 100)} <= found
        assert all(stage.startswith("tile ") for stage in stages)
        assert len(set(stages)) > 1  # cells rotate
        evidence = summarize({"frame": {"available": True, "captured_at": .9},
                              "player": asdict(observation.player),
                              "monsters": [asdict(x) for x in observation.monsters]},
                             Config(), .9)
        assert not evidence["same_platform_targets"]  # tiles never widen targeting
        detector.enemy_source = "new session"
        detector.enemy_tile = 5
        detector.detect(frame, 1.5)
        assert detector.enemy_tile != 5 or detector.enemy_scan_stage == "local"
        monkeypatch.setattr(detector.map_filter, "select", lambda image, taught: None)
        detector.map_filter.title = "another map"
        detector.enemy_empty_observations = 3
        detector.detect(frame, 2.5)
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


