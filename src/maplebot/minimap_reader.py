"""Read the taught area's minimap: map identity and the player's marker. No input.

The minimap picture is static for a map, so the reference view's minimap canvas is
the identity check. Matching the picture rather than the title works in both the
full and the collapsed (M) layouts. A covered, missing or different minimap, and
zero or several player markers, read as unknown.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import Rect

DOT_SHAPE = np.array([
    [0, 0, 1, 1, 0, 0], [0, 1, 1, 1, 1, 0], [1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1], [0, 1, 1, 1, 1, 0], [0, 0, 1, 1, 0, 0],
], dtype=bool)
SEARCH = (400, 300)  # the minimap is anchored in the top-left corner
NAVY = ((80, 40, 15), (120, 80, 50))  # BGR minimap background
MIN_AGREEMENT = 0.85


@dataclass(frozen=True)
class MinimapFix:
    """Player marker in canvas pixels, or None with the reason it is unknown."""

    dot: tuple[float, float] | None
    canvas: Rect | None
    agreement: float
    candidates: int
    reason: str


def _markers(image: np.ndarray) -> np.ndarray:
    """Pixels of moving markers (players, NPCs, portals) and their white rims."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturated = (hsv[..., 1] > 120) & (hsv[..., 2] > 150)
    hue = hsv[..., 0]
    colored = saturated & ((hue < 12) | (hue > 165) | ((hue > 18) & (hue < 42))
                           | ((hue > 85) & (hue < 110)))
    low = image.min(axis=2)
    rim = (low > 190) & (image.max(axis=2).astype(int) - low < 30)
    return cv2.dilate((colored | rim).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0


def _dots(canvas: np.ndarray) -> list[tuple[float, float]]:
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
            dots.append((float(center[0]), float(center[1])))
    return dots


def find_canvas(image: np.ndarray) -> Rect | None:
    """Locate the minimap picture: the navy background plus the terrain below it."""
    region = image[:SEARCH[1], :SEARCH[0]]
    navy = cv2.inRange(region, *NAVY)
    navy = cv2.morphologyEx(navy, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(navy)
    if count < 2:
        return None
    x, y, width, height, area = max(stats[1:], key=lambda stat: stat[4])
    if width < 40 or height < 20 or area < 0.3 * width * height:
        return None
    bottom = y + height
    while bottom < region.shape[0]:
        row = region[bottom, x:x + width]
        if np.mean(row.min(axis=1) > 170) > 0.5:
            break
        bottom += 1
    return Rect(int(x), int(y), int(width), int(bottom - y))


class AreaMinimap:
    """Compare live minimaps against one reference view's minimap picture."""

    def __init__(self, reference: np.ndarray) -> None:
        canvas = find_canvas(reference)
        if canvas is None:
            raise ValueError("No minimap in the reference view; open the minimap and capture again")
        self.size = reference.shape[:2]
        self.home = canvas
        self.template = reference[canvas.y:canvas.feet, canvas.x:canvas.x + canvas.width].copy()
        # The navy background is translucent: scenery shows through it while the
        # camera scrolls. Only the opaque terrain identifies the map.
        navy = cv2.dilate(cv2.inRange(self.template, *NAVY), np.ones((3, 3), np.uint8)) > 0
        self.static = ~_markers(self.template) & ~navy
        if np.count_nonzero(self.static) < 200:
            raise ValueError("The reference minimap shows too little terrain to recognize the map")
        self.weights = self.static.astype(np.uint8)
        self.last = canvas

    def _agreement(self, image: np.ndarray, at: Rect) -> float:
        crop = image[at.y:at.feet, at.x:at.x + at.width]
        if crop.shape != self.template.shape:
            return 0.0
        keep = self.static & ~_markers(crop)
        if np.count_nonzero(keep) < 0.5 * np.count_nonzero(self.static):
            return 0.0
        close = cv2.absdiff(crop, self.template).max(axis=2) < 24
        return float(np.count_nonzero(close & keep) / np.count_nonzero(keep))

    def _locate(self, image: np.ndarray) -> tuple[Rect | None, float]:
        agreement = self._agreement(image, self.last)
        if agreement >= MIN_AGREEMENT:
            return self.last, agreement
        region = image[:SEARCH[1], :SEARCH[0]]
        if region.shape[0] < self.template.shape[0] or region.shape[1] < self.template.shape[1]:
            return None, 0.0
        scores = cv2.matchTemplate(region, self.template, cv2.TM_SQDIFF, mask=self.weights)
        _, _, (x, y), _ = cv2.minMaxLoc(scores)
        at = Rect(int(x), int(y), self.home.width, self.home.height)
        return at, self._agreement(image, at)

    def read(self, image: np.ndarray) -> MinimapFix:
        if image.shape[:2] != self.size:
            return MinimapFix(None, None, 0.0, 0, "Capture size differs from the taught view")
        at, agreement = self._locate(image)
        if at is None or agreement < MIN_AGREEMENT:
            return MinimapFix(None, None, agreement, 0,
                              "Minimap missing, covered or showing another map")
        self.last = at
        dots = _dots(image[at.y:at.feet, at.x:at.x + at.width])
        if len(dots) != 1:
            reason = "No player marker" if not dots else "Several player markers"
            return MinimapFix(None, at, agreement, len(dots), reason)
        return MinimapFix(dots[0], at, agreement, 1, "Player marker on the taught map")


def describe(image: np.ndarray) -> dict | None:
    """The reference view's minimap canvas and player marker, or None without a minimap."""
    try:
        reader = AreaMinimap(image)
    except ValueError:
        return None
    fix = reader.read(image)
    canvas = reader.home
    return {
        "canvas": {"x": canvas.x, "y": canvas.y, "width": canvas.width, "height": canvas.height},
        "dot": {"x": fix.dot[0], "y": fix.dot[1]} if fix.dot else None,
    }
