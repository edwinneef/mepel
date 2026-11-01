import cv2
import numpy as np
import pytest

from maplebot.camera_motion import feature_translation
from maplebot.perception import CameraTracker


def scene():
    noise = np.random.default_rng(17).integers(0, 256, (400, 640), dtype=np.uint8)
    return cv2.GaussianBlur(noise, (5, 5), 0)


def test_feature_translation_requires_distributed_consistent_motion():
    before = scene()
    after = cv2.warpAffine(before, np.float32([[1, 0, -18], [0, 1, 4]]), (640, 400))
    shift, confidence = feature_translation(before, after)
    assert shift == pytest.approx((-18, 4), abs=1)
    assert confidence >= .60


def test_flat_scene_or_a_single_moving_actor_is_not_camera_evidence():
    before = np.zeros((400, 640), np.uint8)
    assert feature_translation(before, before) == ((0, 0), 0)
    before[150:210, 300:360] = scene()[150:210, 300:360]
    after = cv2.warpAffine(before, np.float32([[1, 0, -18], [0, 1, 4]]), (640, 400))
    assert feature_translation(before, after) == ((0, 0), 0)


def test_weak_global_correlation_uses_feature_evidence_without_lowering_gate(monkeypatch):
    before = cv2.cvtColor(scene(), cv2.COLOR_GRAY2BGR)
    after = cv2.warpAffine(before, np.float32([[1, 0, -18], [0, 1, 4]]), (640, 400))
    tracker = CameraTracker()
    tracker.update(before)
    monkeypatch.setattr(cv2, "phaseCorrelate", lambda *args: ((0, 0), .1))
    shift, confidence = tracker.update(after)
    assert shift == pytest.approx((-18, 4), abs=1)
    assert confidence >= .60


def test_unrelated_frames_are_not_a_translation():
    before = scene()
    after = np.random.default_rng(99).integers(0, 256, before.shape, dtype=np.uint8)
    assert feature_translation(before, after) == ((0, 0), 0)


def test_large_three_fps_scroll_uses_hint_only_to_locate_verified_features():
    before = scene()
    after = cv2.warpAffine(before, np.float32([[1, 0, -61], [0, 1, 0]]), (640, 400))
    shift, confidence = feature_translation(before, after, (-60, 1))
    assert shift == pytest.approx((-61, 0), abs=1)
    assert confidence >= .60
    unrelated = np.random.default_rng(10).integers(0, 256, before.shape, dtype=np.uint8)
    assert feature_translation(before, unrelated, (-60, 1)) == ((0, 0), 0)


def test_stationary_camera_does_not_accumulate_windowing_drift():
    image = np.random.default_rng(71).integers(0, 256, (400, 640, 3), dtype=np.uint8)
    tracker = CameraTracker()
    shifts = [tracker.update(image.copy())[0] for _ in range(12)]
    assert np.sum(shifts, axis=0) == pytest.approx((0, 0), abs=.001)
    expected = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None, fx=.5, fy=.5)
    assert np.array_equal(tracker.previous, expected.astype(np.float32))


def test_verified_features_correct_biased_high_correlation(monkeypatch):
    image = cv2.cvtColor(scene(), cv2.COLOR_GRAY2BGR)
    tracker = CameraTracker()
    tracker.update(image)
    monkeypatch.setattr(cv2, "phaseCorrelate", lambda *args: ((.8, -.6), .99))
    shift, confidence = tracker.update(image.copy())
    assert shift == pytest.approx((0, 0), abs=.05)
    assert confidence >= .60
