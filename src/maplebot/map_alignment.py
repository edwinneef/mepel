"""Automatic public-minimap coordinates. Read-only; never grants input authority."""

import math

import numpy as np


def align(reference, canvas, minimap):
    # Import lazily: profiles also validates alignment records.
    from .public_map import MARKER_BIAS, crop, picture, picture_offset

    zoom = minimap["magnification"]
    if type(zoom) is not int or not 0 <= zoom <= 6:
        raise ValueError("Unsupported minimap magnification")
    scale = 2 ** zoom
    center = [minimap[key] for key in ("centerX", "centerY")]
    if not all(type(v) in (int, float) and math.isfinite(v) for v in center):
        raise ValueError("Invalid minimap origin")
    captured, terrain = crop(reference, canvas), picture(minimap)
    offset = picture_offset(captured, terrain)
    # A best match alone says nothing about whether this is the right map.
    # Verify several independent visible patches, masking moving map icons.
    from .public_map import _clipped_offset

    verified = _clipped_offset(captured, terrain)
    if max(abs(a - b) for a, b in zip(offset, verified, strict=True)) > 1:
        raise ValueError("Public minimap registrations disagree")
    transform = {}
    for index, axis in enumerate(("x", "y")):
        transform[f"scale_{axis}"] = scale
        transform[f"offset_{axis}"] = (
            -center[index] - scale * (verified[index] + MARKER_BIAS[index]))
    # Marker quantization plus the empirically observed cross-map bias variation.
    # This is a conservative estimate, not a pixel-accuracy certification.
    return {"version": 1, "transform": transform, "uncertainty_px": scale / 2 + 8,
            "picture_offset": list(verified), "magnification": zoom}


class PositionInterval:
    """Refine quantized positions with verified screen displacement, without drift."""

    def __init__(self):
        self.bounds = None
        self.screen = None
        self.at = None

    def reset(self):
        self.bounds, self.screen, self.at = None, None, None

    def update(self, feet, screen, camera, now, uncertainty):
        values = (*feet, *screen, now, uncertainty)
        if (not all(math.isfinite(v) for v in values) or uncertainty <= 0
                or (camera is not None and not all(math.isfinite(v) for v in camera))):
            self.reset()
            raise ValueError("Invalid position observation")
        bounds = np.array([[v - uncertainty, v + uncertainty] for v in feet], dtype=float)
        if (self.bounds is not None and camera is not None and self.at is not None
                and 0 < now - self.at <= .5):
            delta = np.array(screen) - self.screen - np.array(camera)
            propagated = self.bounds + delta[:, None] + np.array([-1., 1.])
            intersection = np.column_stack((np.maximum(bounds[:, 0], propagated[:, 0]),
                                            np.minimum(bounds[:, 1], propagated[:, 1])))
            if np.all(intersection[:, 0] <= intersection[:, 1]):
                bounds = intersection
            else:
                self.reset()
                return None
        self.bounds, self.screen, self.at = bounds, np.array(screen), now
        return tuple(bounds.mean(axis=1)), float(np.max(np.diff(bounds, axis=1)) / 2)
