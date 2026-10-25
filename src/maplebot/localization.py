"""Offline, taught-geometry localization. No input or live runtime integration."""

import math
from dataclasses import dataclass
from statistics import median

import cv2
import numpy as np

from .geometry import Rect
from .perception import Detection


@dataclass(frozen=True)
class ViewTransform:
    """Manual native-view to area transform; this is not localization evidence."""

    x: float = 0
    y: float = 0
    scale: float = 1

    def __post_init__(self) -> None:
        if (not all(type(v) in (int, float) and math.isfinite(v)
                    for v in (self.x, self.y, self.scale))
                or not 0.05 <= self.scale <= 20
                or max(abs(self.x), abs(self.y)) > 1_000_000):
            raise ValueError("Invalid manual view transform")

    def to_area(self, x: float, y: float) -> tuple[float, float]:
        return x / self.scale + self.x, y / self.scale + self.y

    def to_view(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x) * self.scale, (y - self.y) * self.scale


@dataclass(frozen=True)
class Platform:
    id: str
    left: int
    right: int
    y: int


@dataclass(frozen=True)
class Rope:
    id: str
    x: int
    top: int
    bottom: int


@dataclass(frozen=True)
class SpotGeometry:
    width: int
    height: int
    platforms: tuple[Platform, ...]
    ropes: tuple[Rope, ...] = ()

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Spot dimensions must be positive")
        ids = [item.id for item in (*self.platforms, *self.ropes)]
        if any(not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("Surface IDs must be nonempty and unique")
        for platform in self.platforms:
            if not (0 <= platform.left < platform.right <= self.width
                    and 0 <= platform.y <= self.height):
                raise ValueError(f"Platform {platform.id} is outside the reference frame")
        for rope in self.ropes:
            if not (0 <= rope.x <= self.width and 0 <= rope.top < rope.bottom <= self.height):
                raise ValueError(f"Rope {rope.id} is outside the reference frame")


@dataclass(frozen=True)
class Alignment:
    offset: tuple[float, float] | None
    matches: int
    reason: str


class AnchorMatcher:
    """Find an absolute reference-to-frame translation from two distinct taught crops.

    Each crop must have a unique strong match; all accepted offsets must agree.
    This avoids integrating camera deltas, which drift or reset on missing frames.
    """

    def __init__(self, reference: np.ndarray, boxes: tuple[Rect, ...]) -> None:
        if len(boxes) < 2:
            raise ValueError("Teach at least two separate spot anchors")
        self.shape = reference.shape
        frame = Rect(0, 0, reference.shape[1], reference.shape[0])
        gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        self.anchors = []
        for index, box in enumerate(boxes):
            if not frame.contains(box) or min(box.width, box.height) < 8:
                raise ValueError("Anchor must be inside the reference and at least 8x8 pixels")
            if any(box.iou(other) > 0 for other in boxes[:index]):
                raise ValueError("Spot anchors must not overlap")
            crop = gray[box.y:box.y + box.height, box.x:box.x + box.width].copy()
            if crop.std() < 5:
                raise ValueError("Choose textured spot anchors")
            self.anchors.append((box, crop))

    def match(self, image: np.ndarray) -> Alignment:
        if image.shape != self.shape:
            return Alignment(None, 0, "Capture size changed")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        offsets = []
        for box, crop in self.anchors:
            scores = cv2.matchTemplate(gray, crop, cv2.TM_CCOEFF_NORMED)
            _, best, _, (x, y) = cv2.minMaxLoc(scores)
            scores[max(0, y - box.height // 2):y + box.height // 2 + 1,
                   max(0, x - box.width // 2):x + box.width // 2 + 1] = -1
            runner_up = float(scores.max())
            if math.isfinite(best) and best >= 0.90 and best - runner_up >= 0.04:
                offsets.append((x - box.x, y - box.y))
        if len(offsets) < 2:
            return Alignment(None, len(offsets), "Fewer than two unique spot anchors")
        offset = (median(dx for dx, _ in offsets), median(dy for _, dy in offsets))
        if any(max(abs(dx - offset[0]), abs(dy - offset[1])) > 2 for dx, dy in offsets):
            return Alignment(None, len(offsets), "Spot anchors disagree")
        return Alignment(offset, len(offsets), "Spot anchors agree")


@dataclass(frozen=True)
class Location:
    kind: str
    surface_id: str | None
    reference_feet: tuple[float, float] | None
    reason: str


class SurfaceTracker:
    """Require two fresh observations at least 150 ms apart before assigning a surface.

    A spatial platform match does not prove grounded contact. `near_rope` never
    proves attachment or authorizes a climb. Move completion needs later evidence.
    """

    def __init__(self, geometry: SpotGeometry) -> None:
        self.geometry = geometry
        self.previous_time = float("-inf")
        self.candidate: tuple[str, str] | None = None
        self.candidate_since = 0.0

    def update(self, player: Detection | None, alignment: Alignment, now: float) -> Location:
        if not math.isfinite(now) or now <= self.previous_time:
            raise ValueError("Capture time must be finite and strictly increasing")
        gap = now - self.previous_time
        self.previous_time = now
        if gap > 1.0:
            self.candidate = None
        if alignment.offset is None:
            return self._unknown(alignment.reason)
        if alignment.matches < 2:
            return self._unknown("Fewer than two spot anchors")
        if (player is None or player.tracked or not math.isfinite(player.confidence)
                or player.confidence < 0.90):
            return self._unknown("Player missing, weak or tracked-only")
        if player.kind != "player":
            return self._unknown("Detection is not the player")
        x = player.box.center[0] - alignment.offset[0]
        y = player.box.feet - alignment.offset[1]
        if not math.isfinite(x) or not math.isfinite(y):
            return self._unknown("Invalid anchor offset")
        feet = (x, y)
        candidates = [
            ("platform", platform.id) for platform in self.geometry.platforms
            if platform.left <= x <= platform.right and abs(y - platform.y) <= 6
        ]
        # A platform at a rope endpoint wins; proximity alone is not a rope grab.
        if not candidates:
            candidates = [
                ("near_rope", rope.id) for rope in self.geometry.ropes
                if abs(x - rope.x) <= 6 and rope.top < y < rope.bottom
            ]
        if len(candidates) != 1:
            return self._unknown("No unique taught surface", feet)
        candidate = candidates[0]
        if candidate != self.candidate:
            self.candidate, self.candidate_since = candidate, now
            return Location("unknown", None, feet, "Waiting for a second surface observation")
        if now - self.candidate_since < 0.15:
            return Location("unknown", None, feet, "Waiting for surface confirmation time")
        return Location(*candidate, feet, "Stable spatial match; contact not verified")

    def _unknown(self, reason: str, feet: tuple[float, float] | None = None) -> Location:
        self.candidate = None
        return Location("unknown", None, feet, reason)
