"""Offline minimap marker and motion measurements; no gameplay input."""

from dataclasses import dataclass

import cv2
import numpy as np

DOT_SHAPE = np.array([
    [0, 0, 1, 1, 0, 0], [0, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1], [0, 1, 1, 1, 1, 0], [0, 0, 1, 1, 0, 0],
], dtype=bool)


@dataclass(frozen=True)
class MinimapReading:
    dot: tuple[float, float] | None
    canvas: np.ndarray | None
    candidates: int
    reason: str


class MinimapDetector:
    """Measure the expanded, native-1x minimap used in the saved recordings.

    The header is an explicitly selected screenshot crop, not an inferred game
    identity. Missing UI, resized captures and multiple yellow dots stay unknown.
    """

    def __init__(self, reference: np.ndarray) -> None:
        if reference.shape[:2] != (766, 1023):
            raise ValueError("This probe requires the recorded 1023x766 capture layout")
        self.header = reference[2:16, 3:60].copy()

    def read(self, image: np.ndarray) -> MinimapReading:
        if image.shape[:2] != (766, 1023):
            return MinimapReading(None, None, 0, "Unsupported capture size")
        header = image[2:16, 3:60]
        if np.mean(cv2.absdiff(header, self.header)) > 3:
            return MinimapReading(None, None, 0, "Minimap header missing or covered")
        panel = image[:260, :400]
        low = panel.min(axis=2)
        white = (low > 210) & (panel.max(axis=2).astype(int) - low < 20)
        ends = np.flatnonzero(~white[68, 3:])
        right = int(ends[0]) + 3 if len(ends) else 400
        if not 150 < right < 350:
            return MinimapReading(None, None, 0, "Minimap border missing")
        bottoms = np.flatnonzero(np.all(white[80:, 3:right], axis=1))
        if not len(bottoms):
            return MinimapReading(None, None, 0, "Minimap bottom border missing")
        bottom = int(bottoms[0]) + 80
        canvas = image[70:bottom, 5:right - 3].copy()
        hsv = cv2.cvtColor(canvas, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, (20, 140, 180), (40, 255, 255))
        _, labels, stats, centers = cv2.connectedComponentsWithStats(yellow)
        dots = []
        for label, (stat, center) in enumerate(zip(stats[1:], centers[1:], strict=True), 1):
            x, y, width, height, area = stat
            if (width, height) != (6, 6) or not 22 <= area <= 26:
                continue
            component = labels[y:y + height, x:x + width] == label
            overlap = np.count_nonzero(component & DOT_SHAPE) / np.count_nonzero(
                component | DOT_SHAPE
            )
            if overlap >= 0.9:
                dots.append(tuple(float(value) for value in center))
        if len(dots) != 1:
            return MinimapReading(None, canvas, len(dots), "No unique yellow marker")
        return MinimapReading(dots[0], canvas, 1, "Unique yellow marker")


def terrain_motion(previous: np.ndarray, current: np.ndarray) -> tuple[tuple[float, float], float]:
    """Measure scrolling inside the minimap independently of the player's dot."""
    if previous.shape != current.shape:
        return (0.0, 0.0), 0.0
    first = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
    second = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    texture = np.abs(cv2.Laplacian(first, cv2.CV_32F)) > 10
    height, width = first.shape
    scores = []
    # Integer minimap scrolling: compare textured pixels rather than the moving
    # markers whose bright rings can bias whole-image phase correlation.
    for dy in range(-4, 5):
        for dx in range(-8, 9):
            x0, x1 = max(0, -dx), min(width, width - dx)
            y0, y1 = max(0, -dy), min(height, height - dy)
            valid = texture[y0:y1, x0:x1]
            if np.count_nonzero(valid) < 100:
                continue
            error = cv2.absdiff(first[y0:y1, x0:x1], second[y0 + dy:y1 + dy, x0 + dx:x1 + dx])
            scores.append((float(np.mean(error[valid] <= 3)), dx, dy))
    scores.sort(reverse=True)
    if len(scores) < 2 or scores[0][0] < 0.50 or scores[0][0] - scores[1][0] < 0.02:
        return (0.0, 0.0), 0.0
    score, dx, dy = scores[0]
    return (float(dx), float(dy)), score
