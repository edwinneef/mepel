import numpy as np
import pytest

from tools.compare_southperry_scenery import agreement, match


def test_matching_is_pixel_based_and_one_pixel_controls_reject_displacement():
    rng = np.random.default_rng(4)
    frame = rng.integers(0, 256, (90, 120, 3), dtype="uint8")
    rgb = rng.integers(0, 256, (17, 23, 3), dtype="uint8")
    sprite = np.dstack((rgb, np.full((17, 23), 255, "uint8")))
    frame[31:48, 42:65] = rgb
    result, crop = match(frame, sprite)
    assert result["top_left"] == [42, 31]
    assert result["opaque"]["exact_fraction"] == 1
    assert result["all_controls_worse"]
    assert np.array_equal(crop, rgb)


def test_opaque_mask_keeps_occlusion_errors_and_ignores_only_declared_transparency():
    expected = np.zeros((3, 4, 3), "uint8")
    observed = expected.copy()
    observed[0, 0] = [255, 100, 30]
    mask = np.ones((3, 4), bool)
    assert agreement(observed, expected, mask)["exact_fraction"] == pytest.approx(11 / 12)
    mask[0, 0] = False
    assert agreement(observed, expected, mask)["exact_fraction"] == 1


def test_empty_pixel_comparison_refuses():
    with pytest.raises(ValueError, match="Empty"):
        agreement(np.zeros((2, 2, 3)), np.zeros((2, 2, 3)), np.zeros((2, 2), bool))
