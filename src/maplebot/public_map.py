"""Place public map data (world pixels) in a saved area's coordinates. No capture or input.

The game draws its minimap as the map's own minimap picture, one picture pixel per
2**magnification world pixels, with the world origin at the picture's (center_x,
center_y). The saved walk calibration maps the minimap marker to area pixels, so
finding where that picture sits inside the captured minimap is enough to map world
pixels to area pixels, with no taught surfaces.
"""

import base64

import cv2
import numpy as np

# The player marker's center sits this far (minimap pixels) from the character's
# position. Measured on Middle Forest III (-1.24, -6.93) and Over the Wall
# (-0.64, -7.42) against their taught surfaces; either predicts the other within 10 px.
MARKER_BIAS = (-0.94, -7.17)
_PAD = 40  # the picture may overhang the captured canvas by this much


def picture(minimap: dict) -> np.ndarray:
    """The public minimap picture as BGRA."""
    image = cv2.imdecode(np.frombuffer(base64.b64decode(minimap["canvas"]), np.uint8),
                         cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise ValueError("Public minimap picture is missing or not RGBA")
    return image


def _refine(scores: np.ndarray, at: tuple[int, int]) -> tuple[float, float]:
    """Sub-pixel minimum by a parabola through each axis' neighbours."""
    result = []
    for axis in (0, 1):
        index = at[axis]
        limit = scores.shape[1 - axis]
        if not 0 < index < limit - 1:
            result.append(float(index))
            continue
        if axis == 0:
            a, b, c = scores[at[1], index - 1:index + 2]
        else:
            a, b, c = scores[index - 1:index + 2, at[0]]
        bend = a - 2 * b + c
        result.append(float(index + (0.5 * (a - c) / bend if bend > 0 else 0)))
    return result[0], result[1]


def picture_offset(captured: np.ndarray, image: np.ndarray) -> tuple[float, float]:
    """Where the public picture's top-left sits in the captured minimap canvas."""
    padded = cv2.copyMakeBorder(captured, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=0)
    if (padded.shape[0] < image.shape[0] or padded.shape[1] < image.shape[1]):
        raise ValueError("Captured minimap is far smaller than the public picture")
    mask = (image[..., 3] > 200).astype(np.float32)
    if np.count_nonzero(mask) < 200:
        raise ValueError("Public minimap picture is almost transparent")
    scores = cv2.matchTemplate(padded.astype(np.float32), image[..., :3].astype(np.float32),
                               cv2.TM_SQDIFF, mask=cv2.merge([mask] * 3))
    _, _, at, _ = cv2.minMaxLoc(scores)
    x, y = _refine(scores, at)
    return x - _PAD, y - _PAD


def world_transform(walk: dict, minimap: dict, offset: tuple[float, float]) -> dict:
    """Per axis (scale, offset) from public world pixels to area pixels.

    marker = (world + center) / 2**magnification + picture offset + marker bias,
    area = walk scale * marker + walk offset.
    """
    zoom = 2 ** minimap["magnification"]
    result = {}
    for index, axis in enumerate(("x", "y")):
        scale, shift = walk[f"scale_{axis}"], walk[f"offset_{axis}"]
        marker = minimap[f"center{axis.upper()}"] / zoom + offset[index] + MARKER_BIAS[index]
        result[axis] = (scale / zoom, scale * marker + shift)
    return result


def locate(reference: np.ndarray, canvas: dict, walk: dict, minimap: dict) -> dict:
    """World-to-area transform for one saved view, its walk calibration and a public map."""
    crop = reference[canvas["y"]:canvas["y"] + canvas["height"],
                     canvas["x"]:canvas["x"] + canvas["width"]]
    return world_transform(walk, minimap, picture_offset(crop, picture(minimap)))
