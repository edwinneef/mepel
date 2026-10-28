"""Offline, taught-geometry localization. No input or live runtime integration."""

import math
from dataclasses import dataclass
from statistics import median

import cv2
import numpy as np

from .geometry import Rect
from .minimap_reader import MinimapFix
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
    y_right: float | None = None  # sloped platforms: y is the left end, y_right the right
    bends: tuple[tuple[float, float], ...] = ()  # walked polyline, left to right

    def y_at(self, x: float) -> float:
        if len(self.bends) >= 2:
            xs, ys = zip(*self.bends, strict=True)
            return float(np.interp(x, xs, ys))
        if self.y_right is None or self.right == self.left:
            return self.y
        return self.y + (self.y_right - self.y) * (x - self.left) / (self.right - self.left)


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


@dataclass(frozen=True)
class ViewMatch:
    offset: tuple[float, float] | None
    agree: int
    patches: int


def register_view(reference: np.ndarray, image: np.ndarray) -> tuple[float, float] | None:
    """Camera offset from a screenshot to its reference view: reference = screen + offset.

    For calibration and view alignment only. Textured patches must find unique strong
    matches and at least three must agree; parallax scenery and moving characters
    disagree and drop out. A lost or ambiguous registration returns None.
    """
    return match_view(reference, image).offset


def match_view(reference: np.ndarray, image: np.ndarray) -> ViewMatch:
    """register_view with its evidence: agreeing patches out of textured patches tried."""
    if image.shape != reference.shape:
        return ViewMatch(None, 0, 0)
    target = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    offsets = []
    patches = 0
    # Skip the minimap and HUD margins; they stay fixed while the camera scrolls.
    for y in range(height // 5, height * 3 // 4 - 100, 100):
        for x in range(width // 6, width * 5 // 6 - 120, 120):
            patch = gray[y:y + 100, x:x + 120]
            if patch.std() < 25:
                continue
            patches += 1
            scores = cv2.matchTemplate(target, patch, cv2.TM_CCOEFF_NORMED)
            _, best, _, (mx, my) = cv2.minMaxLoc(scores)
            scores[max(0, my - 50):my + 51, max(0, mx - 60):mx + 61] = -1
            if math.isfinite(best) and best >= 0.85 and best - float(scores.max()) >= 0.05:
                offsets.append((mx - x, my - y))
    if not offsets:
        return ViewMatch(None, 0, patches)
    ox, oy = max(set(offsets), key=offsets.count)
    agree = [(dx, dy) for dx, dy in offsets if abs(dx - ox) <= 2 and abs(dy - oy) <= 2]
    if len(agree) < 3:
        return ViewMatch(None, len(agree), patches)
    offset = (median(dx for dx, _ in agree), median(dy for _, dy in agree))
    return ViewMatch(offset, len(agree), patches)


@dataclass(frozen=True)
class MinimapTransform:
    """Minimap marker (canvas pixels) to area feet: per-axis scale and offset."""

    scale_x: float
    offset_x: float
    scale_y: float
    offset_y: float

    def __post_init__(self) -> None:
        values = (self.scale_x, self.offset_x, self.scale_y, self.offset_y)
        if (not all(math.isfinite(v) for v in values)
                or not all(1 <= v <= 100 for v in (self.scale_x, self.scale_y))):
            raise ValueError("Invalid minimap transform")

    @classmethod
    def fit(cls, dots: list[tuple[float, float]],
            feet: list[tuple[float, float]]) -> "MinimapTransform":
        """Least squares per axis. With too little height change, y reuses the x scale."""
        if len(dots) != len(feet) or len(dots) < 10:
            raise ValueError("Calibration needs at least ten marker and feet pairs")
        marker, area = np.array(dots, float), np.array(feet, float)
        if np.ptp(marker[:, 0]) < 10:
            raise ValueError("Walk further: the marker must move at least ten minimap pixels")
        scale_x, offset_x = np.polyfit(marker[:, 0], area[:, 0], 1)
        if np.ptp(marker[:, 1]) >= 3:
            scale_y, offset_y = np.polyfit(marker[:, 1], area[:, 1], 1)
        else:
            scale_y = scale_x
            offset_y = float(np.median(area[:, 1] - scale_y * marker[:, 1]))
        return cls(float(scale_x), float(offset_x), float(scale_y), float(offset_y))

    def to_area(self, x: float, y: float) -> tuple[float, float]:
        return self.scale_x * x + self.offset_x, self.scale_y * y + self.offset_y


class MinimapTracker:
    """Fuse the minimap marker (absolute) with the name tag (fresh, precise).

    The marker places the player in the area. Between consecutive frames, the name
    tag must move the same way once the camera shift is removed. A platform needs
    both on a stable height, for two observations at least 150 ms apart. As with
    SurfaceTracker, this is a spatial match: contact and movement are not verified.
    """

    def __init__(self, transform: MinimapTransform, platforms: tuple[Platform, ...], *,
                 agreement: float = 32, height: float = 12) -> None:
        self.transform = transform
        self.platforms = platforms
        self.agreement = agreement
        self.height = height
        self.previous_time = float("-inf")
        self.last: tuple[tuple[float, float], tuple[float, float]] | None = None
        self.candidate: str | None = None
        self.candidate_since = 0.0

    def update(self, fix: MinimapFix, player: Detection | None,
               camera_shift: tuple[float, float] | None, now: float) -> Location:
        if not math.isfinite(now) or now <= self.previous_time:
            raise ValueError("Capture time must be finite and strictly increasing")
        if now - self.previous_time > 1.0:
            self.last = None
        self.previous_time = now
        if fix.dot is None:
            return self._unknown(fix.reason)
        feet = self.transform.to_area(*fix.dot)
        if (player is None or player.kind != "player" or player.tracked
                or not math.isfinite(player.confidence) or player.confidence < 0.90):
            # A one-frame name-tag miss is common while standing still; it says nothing about
            # movement, so the platform being confirmed and the last observation survive it.
            return Location("unknown", None, feet, "Name tag missing, weak or tracked-only")
        screen = (player.box.center[0], float(player.box.feet))
        last, self.last = self.last, (fix.dot, screen)
        if last is None or camera_shift is None:
            return self._unknown("Waiting for a second fused observation", feet, keep=True)
        marker = (fix.dot[0] - last[0][0], fix.dot[1] - last[0][1])
        # Logged camera shift is the scenery's screen motion: the camera moved by -shift.
        tag = (screen[0] - last[1][0] - camera_shift[0], screen[1] - last[1][1] - camera_shift[1])
        if (abs(marker[0] * self.transform.scale_x - tag[0]) > self.agreement
                or abs(marker[1] * self.transform.scale_y - tag[1]) > self.agreement):
            return self._unknown("Minimap marker and name tag disagree", feet, keep=True)
        # One marker pixel up or down while walking, with a steady name tag, is a slope.
        slope_step = abs(marker[1]) <= 1 and abs(marker[0]) > 0.5 and abs(tag[1]) <= 24
        if (abs(marker[1]) > 0.5 or abs(tag[1]) > 3) and not slope_step:
            return self._unknown("Moving vertically (jump, fall or climb)", feet, keep=True)
        # The marker moves in whole minimap pixels (~15 px): standing a pixel or two past the
        # walked end of a ledge still means that ledge, when it is the only fit.
        slack = 2 * abs(self.transform.scale_x)
        matches = [
            platform.id for platform in self.platforms
            if platform.left - slack <= feet[0] <= platform.right + slack
            and abs(feet[1] - platform.y_at(min(max(feet[0], platform.left), platform.right)))
            <= self.height
        ]
        if len(matches) != 1:
            return self._unknown("No unique taught platform", feet, keep=True)
        if matches[0] != self.candidate:
            self.candidate, self.candidate_since = matches[0], now
            return Location("unknown", None, feet, "Waiting for a second platform observation")
        if now - self.candidate_since < 0.15:
            return Location("unknown", None, feet, "Waiting for platform confirmation time")
        return Location(
            "platform", matches[0], feet, "Marker and name tag agree; contact not verified"
        )

    def _unknown(self, reason: str, feet: tuple[float, float] | None = None, *,
                 keep: bool = False) -> Location:
        """Clear the platform candidate; without keep, also forget the last observation."""
        self.candidate = None
        if not keep:
            self.last = None
        return Location("unknown", None, feet, reason)
