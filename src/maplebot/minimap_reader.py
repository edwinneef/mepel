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
# Scrolling minimap: Tree Dungeon frames score 0.45-0.49 at the true scroll and at most
# 0.15 anywhere else; require a clear winner on both counts.
SCROLL_MATCH, SCROLL_MARGIN = 0.35, 0.15
MIN_TERRAIN_VALUE = 80
SKY_HUE = (95, 130)  # OpenCV hue band of blue sky seen through the minimap


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


def _framed_canvas(region: np.ndarray) -> Rect | None:
    """The picture inside the minimap window's thin white frame, for maps without navy."""
    white = np.all(region >= 235, axis=2)
    height, width = white.shape
    for top in range(height):
        row = white[top]
        x = 0
        while x < width:
            if not row[x]:
                x += 1
                continue
            right = x
            while right + 1 < width and row[right + 1]:
                right += 1
            if right - x >= 60:
                bottom = top + 1
                while (bottom < height and white[bottom, x] and white[bottom, right]
                       and not white[bottom, x:right + 1].all()):
                    bottom += 1
                if (bottom < height and bottom - top >= 20
                        and white[bottom, x:right + 1].mean() > 0.9
                        and white[top + 1:bottom, x + 1:right].mean() < 0.5):
                    return Rect(x + 1, top + 1, right - x - 1, bottom - top - 1)
            x = right + 1
    return None


def find_canvas(image: np.ndarray) -> Rect | None:
    """Locate the minimap picture: the navy background plus the terrain below it.

    Maps whose minimap art has no navy background use the window's white frame.
    """
    region = image[:SEARCH[1], :SEARCH[0]]
    # Translucent scenery can split navy into narrow components inside the window.
    # A complete enclosing frame establishes the full picture extent.
    framed = _framed_canvas(region)
    if framed is not None:
        return framed
    navy = cv2.inRange(region, *NAVY)
    navy = cv2.morphologyEx(navy, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(navy)
    if count < 2:
        return _framed_canvas(region)
    x, y, width, height, area = max(stats[1:], key=lambda stat: stat[4])
    if width < 40 or height < 20 or area < 0.3 * width * height:
        return _framed_canvas(region)
    bottom = y + height
    while bottom < region.shape[0]:
        row = region[bottom, x:x + width]
        if np.mean(row.min(axis=1) > 170) > 0.5:
            break
        bottom += 1
    return Rect(int(x), int(y), int(width), int(bottom - y))


class AreaMinimap:
    """Compare live minimaps against one reference view's minimap picture."""

    def __init__(self, reference: np.ndarray, terrain: np.ndarray | None = None) -> None:
        canvas = find_canvas(reference)
        if canvas is None:
            raise ValueError("No minimap in the reference view; open the minimap and capture again")
        self.size = reference.shape[:2]
        self.home = canvas
        self.template = reference[canvas.y:canvas.feet, canvas.x:canvas.x + canvas.width].copy()
        # Minimap backgrounds (navy, or a grey sky) are translucent: scenery shows
        # through them while the camera scrolls. Only the opaque terrain identifies the map.
        hsv = cv2.cvtColor(self.template, cv2.COLOR_BGR2HSV)
        # Bright scenery through grey gaps is just as transient as dark scenery.
        background = cv2.inRange(self.template, *NAVY) | np.uint8(hsv[..., 1] < 50) * 255
        # Blue sky through the translucent background changes as the camera moves too.
        background |= cv2.inRange(hsv[..., 0], *SKY_HUE)
        background = cv2.dilate(background, np.ones((3, 3), np.uint8)) > 0
        # Dark saturated scenery also shows through the minimap's translucent gaps.
        # Use brighter terrain for identity; dark-only references must stay unknown.
        self.static = (~_markers(self.template) & ~background
                       & (hsv[..., 2] >= MIN_TERRAIN_VALUE))
        # A map taller than its minimap window scrolls vertically to keep the player in
        # view, so the marker's canvas row is not the player's height. Then the picture
        # placement is measured on every frame and the marker is corrected back to the
        # reference view's scroll.
        self.scroll: tuple[int, int] | None = None
        if terrain is not None:
            from .public_map import picture_offset

            if terrain.ndim != 3 or terrain.shape[2] != 4:
                raise ValueError("Public minimap terrain must be RGBA")
            x, y = picture_offset(self.template, terrain)
            opaque = cv2.warpAffine(
                (terrain[..., 3] > 200).astype(np.uint8),
                np.float32([[1, 0, round(x)], [0, 1, round(y)]]),
                (canvas.width, canvas.height), flags=cv2.INTER_NEAREST,
            ) > 0
            self.static = opaque & ~_markers(self.template)
            if terrain.shape[0] > canvas.height:
                self.picture, self.scroll = terrain, (round(x), round(y))
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

    def _scroll_offset(self, crop: np.ndarray) -> tuple[float, float] | None:
        """The picture's top row in this canvas, if one vertical placement clearly wins."""
        assert self.scroll is not None
        picture, (left, _) = self.picture, self.scroll
        height, width = crop.shape[:2]
        x0, x1 = max(0, left), min(width, left + picture.shape[1])
        if x1 - x0 < 8 or picture.shape[0] <= height:
            return None
        # Slide this canvas's picture columns down the public picture; player markers
        # are left out. Correlation tolerates the minimap's translucent colour blending.
        strip = crop[:, x0:x1].astype(np.float32)
        mask = (~_markers(crop)[:, x0:x1]).astype(np.uint8)
        scores = cv2.matchTemplate(picture[..., :3].astype(np.float32), strip,
                                   cv2.TM_CCOEFF_NORMED, mask=cv2.merge([mask] * 3))
        scores = np.nan_to_num(scores[:, x0 - left], nan=-1, posinf=-1, neginf=-1)
        row = int(np.argmax(scores))
        rival = float(np.max(np.delete(scores, np.arange(max(0, row - 3), row + 4)),
                             initial=-1))
        # Repeating terrain can fit at two scrolls; then the height stays unknown.
        if scores[row] < SCROLL_MATCH or scores[row] - rival < SCROLL_MARGIN:
            return None
        # Sub-pixel peak: one minimap pixel is 16 game pixels of height.
        shift = 0.0
        if 0 < row < len(scores) - 1:
            below, here, above = scores[row - 1], scores[row], scores[row + 1]
            curve = below - 2 * here + above
            if curve < 0:
                shift = float(np.clip(0.5 * (below - above) / curve, -0.5, 0.5))
        return -(row + shift), float(scores[row])

    def _read_scrolled(self, image: np.ndarray, at: Rect) -> MinimapFix:
        assert self.scroll is not None
        crop = image[at.y:at.feet, at.x:at.x + at.width]
        found = self._scroll_offset(crop) if crop.shape == self.template.shape else None
        if found is None:
            return MinimapFix(None, None, 0.0, 0,
                              "Minimap scroll unclear: covered, repeating terrain or another map")
        top, agreement = found
        self.last = at
        dots = _dots(crop)
        if len(dots) != 1:
            reason = "No player marker" if not dots else "Several player markers"
            return MinimapFix(None, at, agreement, len(dots), reason)
        x, y = dots[0]
        return MinimapFix((x, y - (top - self.scroll[1])), at, agreement, 1,
                          "Player marker on the taught map (scroll corrected)")

    def read(self, image: np.ndarray) -> MinimapFix:
        if image.shape[:2] != self.size:
            return MinimapFix(None, None, 0.0, 0, "Capture size differs from the taught view")
        if self.scroll is not None:
            # The window stays put while its content scrolls; identity comes from the
            # picture match, not from the reference view's scroll position.
            return self._read_scrolled(image, self.last)
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
