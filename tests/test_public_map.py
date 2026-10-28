import base64

import cv2
import numpy as np
import pytest

from maplebot.public_map import MARKER_BIAS, locate, picture_offset, world_transform


def public_picture():
    rng = np.random.default_rng(3)
    image = np.zeros((40, 60, 4), np.uint8)
    image[..., :3] = rng.integers(40, 255, (40, 60, 3))
    image[..., 3] = 255
    image[:5, :, 3] = 0  # transparent top rows are ignored by the match
    return image


def test_picture_offset_finds_the_picture_even_when_it_overhangs():
    image = public_picture()
    captured = np.zeros((45, 80, 3), np.uint8)
    captured[:37, 12:72] = image[3:, :, :3]  # placed at (12, -3): top rows cut off
    assert picture_offset(captured, image) == pytest.approx((12, -3), abs=.25)


def test_world_transform_follows_minimap_math():
    walk = {"scale_x": 16, "offset_x": 10, "scale_y": 15, "offset_y": -5}
    minimap = {"centerX": 32, "centerY": 160, "magnification": 4}
    fit = world_transform(walk, minimap, (2, -1))
    assert fit["x"] == pytest.approx((1, 16 * (2 + 2 + MARKER_BIAS[0]) + 10))
    assert fit["y"] == pytest.approx((15 / 16, 15 * (10 - 1 + MARKER_BIAS[1]) - 5))


def test_locate_reads_the_view_canvas():
    image = public_picture()
    reference = np.zeros((120, 160, 3), np.uint8)
    reference[30:65, 25:85] = image[5:, :, :3]  # picture at (5, 0) in a canvas at (20, 25)
    minimap = {"canvas": base64.b64encode(cv2.imencode(".png", image)[1]).decode(),
               "centerX": 0, "centerY": 0, "magnification": 4}
    walk = {"scale_x": 16, "offset_x": 0, "scale_y": 16, "offset_y": 0}
    fit = locate(reference, {"x": 20, "y": 25, "width": 80, "height": 50}, walk, minimap)
    assert fit["x"][1] == pytest.approx(16 * (5 + MARKER_BIAS[0]), abs=4)
    assert fit["y"][1] == pytest.approx(16 * MARKER_BIAS[1], abs=4)
