import cv2
import numpy as np

from maplebot.config import PerceptionConfig
from maplebot.perception import TemplateDetector


def test_failed_alignment_is_throttled_and_geometry_stays_unavailable(tmp_path, monkeypatch):
    image = np.zeros((80, 100, 3), np.uint8)
    cv2.imwrite(str(tmp_path / "reference.png"), image)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    calls = []
    confidence = [.1]

    class Camera:
        def update(self, frame):
            calls.append(True)
            return (0, 0), confidence[0]

    monkeypatch.setattr("maplebot.perception.CameraTracker", Camera)
    detector.enemy_geometry = {"map": {"reference": "reference.png",
                                       "regions": [[10, 10, 20, 20]],
                                       "platforms": [[0, 50, 90, 50]]}}
    detector.catalog_info["active_map"] = "map"
    try:
        for now in (0, .1, .5, .99):
            detector._configure_enemy_geometry(image, 1, now)
        assert len(calls) == 2
        assert not detector.enemy_geometry_ready
        assert detector.enemy_tracker.regions == ()
        confidence[0] = .9
        detector._configure_enemy_geometry(image, 1, 1)
        assert len(calls) == 4
        assert detector.enemy_geometry_ready
        assert detector.enemy_tracker.regions
        detector._configure_enemy_geometry(image, .1, 1.1)
        assert not detector.enemy_geometry_ready
        assert detector.enemy_tracker.regions == ()
        assert detector.enemy_tracker.platforms == ()
        assert len(calls) == 4
        detector.reload()
        assert detector.enemy_geometry_retry_at == float("-inf")
    finally:
        detector.pool.shutdown()
        detector.map_filter.close()
