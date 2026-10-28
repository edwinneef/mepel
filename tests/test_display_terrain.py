import cv2
import numpy as np
import pytest

from maplebot.display_terrain import DisplayTerrain
from maplebot.geometry import Rect


def scene(seed=71):
    rng = np.random.default_rng(seed)
    image = np.zeros((768, 1366, 3), np.uint8)
    for _ in range(800):
        x, y = rng.integers([0, 0], [1366, 768])
        radius = int(rng.integers(2, 12))
        color = tuple(int(value) for value in rng.integers(30, 255, 3))
        cv2.circle(image, (int(x), int(y)), radius, color, -1)
    return image


def moved(image, x, y):
    return cv2.warpAffine(image, np.float32([[1, 0, x], [0, 1, y]]), (1366, 768))


def tracker(image):
    value = DisplayTerrain()
    value.configure(image, 100, 200, 1.5, "forest", 7)
    return value


def test_camera_translation_and_reversal_do_not_require_platform_contact():
    image = scene()
    value = tracker(image)
    for index, (x, y) in enumerate([(0, 0), (4, 2), (8, 4), (12, 6), (8, 4), (0, 0)]):
        result = value.update(moved(image, x, y), 100 + index / 30)
        assert result is not None
        assert result["kind"] == "unknown"
        assert result["feet"] is None
        assert result["surface_id"] is None
        assert result["projection"]["x"] == pytest.approx(x - 150, abs=0.8)
        assert result["projection"]["y"] == pytest.approx(y - 300, abs=0.8)
        assert result["alignment"]["support"] >= 12


def test_absolute_registration_recovers_when_starting_on_scrolled_ladder_view():
    image = scene()
    result = tracker(image).update(moved(image, -90, 70), 100)
    assert result is not None
    assert result["projection"]["x"] == pytest.approx(-240, abs=1)
    assert result["projection"]["y"] == pytest.approx(-230, abs=1)


def test_scene_loss_clears_immediately_and_reacquires_from_reference():
    image = scene()
    value = tracker(image)
    assert value.update(image, 100)
    assert value.update(np.zeros_like(image), 100.03) is None
    assert value.update(scene(4), 100.06) is None
    assert value.update(moved(image, 20, 12), 100.6)


def test_resize_and_source_reset_cannot_reuse_alignment():
    image = scene()
    value = tracker(image)
    assert value.update(image, 100)
    assert value.update(image[:600], 100.03) is None
    value.reset()
    assert value.update(image, 100.06) is None
    value.configure(scene(4), 0, 0, 1, "other", 8)
    assert value.update(image, 100.1) is None


def test_current_actor_mask_does_not_move_terrain_with_the_actor():
    image = scene()
    value = tracker(image)
    assert value.update(image, 100)
    changed = moved(image, 5, 2)
    changed[220:460, 400:700] = np.random.default_rng(8).integers(
        0, 256, (240, 300, 3), dtype=np.uint8
    )
    result = value.update(changed, 100.03, (Rect(400, 220, 300, 240),))
    assert result
    assert result["projection"]["x"] == pytest.approx(-145, abs=1)


def test_competing_background_motion_is_rejected():
    image = scene()
    value = tracker(image)
    assert value.update(image, 100)
    changed = moved(image, 14, 0)
    changed[:, :683] = moved(image, -14, 0)[:, :683]
    assert value.update(changed, 100.03) is None
    assert tracker(image).update(changed, 100) is None


def test_screen_fixed_hud_cannot_anchor_an_unrelated_scene():
    image = scene()
    changed = scene(4)
    changed[:160] = image[:160]
    changed[650:] = image[650:]
    assert tracker(image).update(changed, 100) is None


def test_propagation_expires_without_absolute_reference_evidence(monkeypatch):
    image = scene()
    value = tracker(image)
    assert value.update(image, 100)
    monkeypatch.setattr(value, "_anchor", lambda *args: False)
    monkeypatch.setattr(value, "_refine", lambda *args: None)
    for index in range(1, 61):
        assert value.update(image, 100 + index / 30)
    assert value.update(image, 100 + 61 / 30) is None


def test_low_texture_and_nonfinite_transform_are_rejected():
    image = np.zeros((768, 1366, 3), np.uint8)
    assert tracker(image).update(image, 100) is None
    with pytest.raises(ValueError):
        DisplayTerrain().configure(image, float("nan"), 0, 1, "forest", 1)


def test_long_sequence_reanchors_and_does_not_accumulate_drift():
    image = scene()
    value = tracker(image)
    for index in range(100):
        x = int(30 * np.sin(index / 18))
        y = int(15 * np.sin(index / 16))
        result = value.update(moved(image, x, y), 100 + index / 30)
        assert result
        assert result["projection"]["x"] == pytest.approx(x - 150, abs=1)
        assert result["projection"]["y"] == pytest.approx(y - 300, abs=1)
        assert result["alignment"]["anchor_age_ms"] <= 550
