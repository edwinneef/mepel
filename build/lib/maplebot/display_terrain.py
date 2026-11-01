"""Read-only registration of saved terrain to a fresh screenshot.

This is drawing evidence, never player localization. A reference-image anchor is
propagated using background features, independently of feet/platform contact.
"""

import math

import cv2
import numpy as np

from .capture import Image
from .geometry import Rect


class DisplayTerrain:
    """One-owner visual tracker. Reconfigure on map/view/source changes.

    Coordinates in the configured reference obey screen = (area - origin) * scale.
    HUD strips and supplied actor boxes cannot support registration. Propagation
    expires after two seconds without an absolute reference-image re-anchor.
    Background seen at verified alignments extends the reference beyond its one
    screen, so later views of that part of the map can re-anchor too.
    """

    ANCHOR_INTERVAL = 0.5
    ANCHOR_LIFETIME = 2.0
    MAX_FRAME_GAP = 0.5
    MAX_JUMP = 16.0  # px; larger disagreement with live propagation needs confirmation
    FEATURES = 1600  # per reference-screen area
    EXTEND_INTERVAL = 1.0

    def __init__(self) -> None:
        self.orb = cv2.ORB_create(nfeatures=self.FEATURES, fastThreshold=12, edgeThreshold=15)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.reset()

    def reset(self) -> None:
        self.reference: np.ndarray | None = None
        self.filled: np.ndarray | None = None
        self.pad = np.zeros(2, np.float32)
        self.base_area = 1
        self.reference_points: np.ndarray | None = None
        self.descriptors: np.ndarray | None = None
        self.shape: tuple[int, ...] | None = None
        self.area_id = ""
        self.revision = 0
        self.origin = (0.0, 0.0)
        self.scale = 1.0
        self._clear()

    def _clear(self) -> None:
        self.previous: np.ndarray | None = None
        self.points: np.ndarray | None = None
        self.offset = np.zeros(2, np.float32)
        self.anchor_offset = np.zeros(2, np.float32)
        self.last_time: float | None = None
        self.anchor_time = float("-inf")
        self.feature_time = float("-inf")
        self.attempt_time = float("-inf")
        self.support = 0
        self.residual = 0.0
        self.disagreements: list[np.ndarray] = []
        self.extend_time = float("-inf")

    @staticmethod
    def _gray(image: Image) -> np.ndarray:
        return cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None, fx=0.5, fy=0.5)

    @staticmethod
    def _mask(shape: tuple[int, ...], boxes: tuple[Rect, ...] = ()) -> np.ndarray:
        height, width = shape[:2]
        mask = np.zeros((height, width), np.uint8)
        # Minimap/title at the top and chat/HP/action bars at the bottom are screen-fixed.
        mask[int(height * 0.22):int(height * 0.82), int(width * 0.04):int(width * 0.96)] = 255
        for box in boxes:
            left = max(0, int(box.x / 2) - 8)
            top = max(0, int(box.y / 2) - 8)
            right = min(width, int((box.x + box.width) / 2) + 8)
            bottom = min(height, int((box.y + box.height) / 2) + 8)
            mask[top:bottom, left:right] = 0
        return mask

    def configure(self, reference: Image, x: float, y: float, scale: float,
                  area_id: str, revision: int) -> None:
        self.reset()
        if not all(math.isfinite(value) for value in (x, y, scale)) or not 0.05 <= scale <= 20:
            raise ValueError("Invalid terrain view transform")
        gray = self._gray(reference)
        height, width = gray.shape
        # Room for about one more screen sideways and half a screen vertically.
        self.pad = np.float32([width, height // 2])
        px, py = int(self.pad[0]), int(self.pad[1])
        self.reference = np.zeros((height + 2 * py, width + 2 * px), np.uint8)
        self.filled = np.zeros_like(self.reference)
        self.reference[py:py + height, px:px + width] = gray
        self.filled[py:py + height, px:px + width] = self._mask(gray.shape)
        self.base_area = int(np.count_nonzero(self.filled))
        self.shape = reference.shape
        self.origin, self.scale = (x, y), scale
        self.area_id, self.revision = area_id, revision
        self._features()

    def _features(self) -> None:
        """Reference features in canvas coordinates over every verified pixel."""
        assert self.reference is not None and self.filled is not None
        area = int(np.count_nonzero(self.filled))
        orb = cv2.ORB_create(nfeatures=min(4 * self.FEATURES, self.FEATURES * area
                                           // self.base_area),
                             fastThreshold=12, edgeThreshold=15)
        mask = cv2.erode(self.filled, np.ones((9, 9), np.uint8))
        points, self.descriptors = orb.detectAndCompute(self.reference, mask)
        self.reference_points = np.float32([point.pt for point in points]).reshape(-1, 2)

    def _extend(self, gray: np.ndarray, mask: np.ndarray) -> None:
        """Add newly seen background at the verified offset; existing pixels stay."""
        assert self.reference is not None and self.filled is not None
        shift = self.pad - self.offset / 2
        transform = np.float32([[1, 0, shift[0]], [0, 1, shift[1]]])
        size = self.reference.shape[::-1]
        placed = cv2.warpAffine(gray, transform, size, flags=cv2.INTER_LINEAR)
        cover = cv2.warpAffine(cv2.erode(mask, np.ones((5, 5), np.uint8)), transform, size,
                               flags=cv2.INTER_NEAREST)
        new = (cover != 0) & (self.filled == 0)
        if np.count_nonzero(new) < 0.03 * mask.size:
            return
        self.reference[new] = placed[new]
        self.filled[new] = 255
        self._features()

    @staticmethod
    def _consensus(deltas: np.ndarray, points: np.ndarray,
                   shape: tuple[int, ...], *, absolute: bool = False,
                   ) -> tuple[np.ndarray, np.ndarray, float] | None:
        if len(deltas) < 12:
            return None
        offset = np.median(deltas, axis=0)
        errors = np.linalg.norm(deltas - offset, axis=1)
        # ORB pyramid features are quantized more coarsely than temporal LK tracks.
        good = errors <= (2.5 if absolute else 1.5)
        if good.sum() < 12 or good.mean() < (0.5 if absolute else 0.75):
            return None
        if absolute:
            # Random descriptor mistakes differ from a second coherent parallax plane.
            other = deltas[~good]
            for candidate in other:
                if (np.linalg.norm(other - candidate, axis=1) <= 2.5).sum() >= max(
                    6, len(deltas) * 0.25
                ):
                    return None
        spread = np.ptp(points[good], axis=0)
        height, width = shape[:2]
        if spread[0] < width * 0.25 or spread[1] < height * 0.10:
            return None
        return np.median(deltas[good], axis=0), good, float(np.percentile(errors[good], 95))

    def _anchor(self, gray: np.ndarray, mask: np.ndarray, captured_at: float,
                expected: np.ndarray | None = None) -> bool:
        self.attempt_time = captured_at
        if self.descriptors is None or self.reference_points is None:
            return False
        features, descriptors = self.orb.detectAndCompute(gray, mask)
        if descriptors is None or len(descriptors) < 12:
            return False
        matches = [pair[0] for pair in self.matcher.knnMatch(self.descriptors, descriptors, k=2)
                   if len(pair) == 2 and pair[0].distance < pair[1].distance * 0.70]
        # Many reference features mapping to one sprite do not count as independent support.
        unique = {match.trainIdx: match
                  for match in sorted(matches, key=lambda item: -item.distance)}
        matches = list(unique.values())
        if len(matches) < 12:
            return False
        current = np.float32([features[match.trainIdx].pt for match in matches])
        reference = self.reference_points[[match.queryIdx for match in matches]] - self.pad
        consensus = self._consensus(current - reference, current, gray.shape, absolute=True)
        if consensus is None:
            return False
        offset, good, residual = consensus
        refined = self._refine(gray, mask, reference[good], offset)
        if refined is None:
            return False
        if expected is not None and np.linalg.norm(refined * 2 - expected) > self.MAX_JUMP:
            # One registration cannot overrule continuous propagation; three consistent
            # disagreements in a row can.
            self.disagreements = [*self.disagreements[-2:], refined * 2 - expected]
            if len(self.disagreements) < 3 or max(
                    np.linalg.norm(item - self.disagreements[-1])
                    for item in self.disagreements) > 3:
                return False
        self.disagreements = []
        self.offset = self.anchor_offset = refined * 2
        self.anchor_time = captured_at
        self.feature_time = captured_at
        self.points = current[good].reshape(-1, 1, 2)
        self.support, self.residual = int(good.sum()), residual * 2
        return True

    def _refine(self, gray: np.ndarray, mask: np.ndarray, reference: np.ndarray,
                offset: np.ndarray) -> np.ndarray | None:
        # Verify the descriptor translation against several separated image patches.
        # This also removes pyramid-coordinate quantization before publishing geometry.
        patches = []
        centers = []
        cells = set()
        height, width = gray.shape
        canvas_height, canvas_width = self.reference.shape
        pad_x, pad_y = int(self.pad[0]), int(self.pad[1])
        for point in reference:
            cell = (int(point[0] * 6 / width), int(point[1] * 6 / height))
            if cell in cells:
                continue
            if any(np.linalg.norm(point - center) < 35 for center in centers):
                continue
            # Reference patches come from the padded canvas; rx/ry are canvas pixels.
            rx, ry = np.rint(point).astype(int) + (pad_x, pad_y)
            cx, cy = np.rint(point + offset).astype(int)
            if min(rx, ry, cx, cy) < 13:
                continue
            if (rx + 13 >= canvas_width or ry + 13 >= canvas_height
                    or cx + 13 >= width or cy + 13 >= height):
                continue
            patch = self.reference[ry - 9:ry + 10, rx - 9:rx + 10]
            search = gray[cy - 12:cy + 13, cx - 12:cx + 13]
            if (float(patch.std()) < 10 or not mask[cy - 9:cy + 10, cx - 9:cx + 10].all()
                    or not self.filled[ry - 9:ry + 10, rx - 9:rx + 10].all()):
                continue
            scores = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(scores)
            if score >= 0.85:
                px, py = location
                subpixel = []
                for values, index in ((scores[py, :], px), (scores[:, px], py)):
                    shift = 0.0
                    if 0 < index < len(values) - 1:
                        left, center, right = values[index - 1:index + 2]
                        denominator = float(left - 2 * center + right)
                        if denominator < -1e-6:
                            shift = float(np.clip(0.5 * (left - right) / denominator, -0.5, 0.5))
                    subpixel.append(shift)
                patches.append((cx - rx + pad_x + px - 3 + subpixel[0],
                                cy - ry + pad_y + py - 3 + subpixel[1]))
                centers.append(point)
                cells.add(cell)
                if len(patches) >= 8:
                    break
        if len(patches) < 3:
            return None
        refined = np.median(patches, axis=0)
        if np.max(np.linalg.norm(np.asarray(patches) - refined, axis=1)) > 2:
            return None
        return refined

    def _propagate(self, gray: np.ndarray, mask: np.ndarray) -> bool:
        if self.previous is None or self.points is None:
            return False
        current, status, error = cv2.calcOpticalFlowPyrLK(
            self.previous, gray, self.points, None, winSize=(21, 21), maxLevel=2
        )
        if current is None:
            return False
        back, back_status, _ = cv2.calcOpticalFlowPyrLK(
            gray, self.previous, current, None, winSize=(21, 21), maxLevel=2
        )
        if back is None:
            return False
        old, new = self.points.reshape(-1, 2), current.reshape(-1, 2)
        valid = (status.ravel() != 0) & (back_status.ravel() != 0) & (error.ravel() < 20)
        valid &= np.linalg.norm(back.reshape(-1, 2) - old, axis=1) < 0.75
        indices = np.rint(new).astype(int)
        height, width = gray.shape
        valid &= (indices[:, 0] >= 0) & (indices[:, 0] < width)
        valid &= (indices[:, 1] >= 0) & (indices[:, 1] < height)
        inside = np.flatnonzero(valid)
        valid[inside] &= mask[indices[inside, 1], indices[inside, 0]] != 0
        if valid.sum() < 12 or valid.mean() < 0.5:
            return False
        consensus = self._consensus(new[valid] - old[valid], new[valid], gray.shape)
        if consensus is None:
            return False
        shift, good, residual = consensus
        if np.linalg.norm(shift) > 60:
            return False
        self.offset = self.offset + shift * 2
        self.points = new[valid][good].reshape(-1, 1, 2)
        self.support, self.residual = int(good.sum()), residual * 2
        return True

    def update(self, image: Image, captured_at: float,
               excluded_boxes: tuple[Rect, ...] = ()) -> dict | None:
        if self.reference is None or image.shape != self.shape or not math.isfinite(captured_at):
            self._clear()
            return None
        if (self.last_time is not None
                and not 0 < captured_at - self.last_time <= self.MAX_FRAME_GAP):
            self._clear()
        gray = self._gray(image)
        mask = self._mask(gray.shape, excluded_boxes)
        tracked = self._propagate(gray, mask)
        anchored = False
        # Re-check early during fast scrolls, before propagation reaches its 160 px limit
        # and before its feature points leave the view.
        scrolled = bool(np.linalg.norm(self.offset - self.anchor_offset) > 80)
        if scrolled or captured_at - self.attempt_time >= (
                self.ANCHOR_INTERVAL if tracked else 0.1):
            # Recheck the original image patches, not merely the preceding frame.
            # With a usable prediction this avoids full descriptor extraction/matching.
            self.attempt_time = captured_at
            # Replenish feature support periodically as old features leave the view.
            if not tracked or scrolled or captured_at - self.feature_time >= 1:
                anchored = self._anchor(gray, mask, captured_at,
                                        self.offset.copy() if tracked else None)
            if tracked and not anchored:
                refined = self._refine(gray, mask, self.points.reshape(-1, 2) - self.offset / 2,
                                       self.offset / 2)
                if refined is not None:
                    self.offset = self.anchor_offset = refined * 2
                    self.anchor_time = captured_at
                    anchored = True
        valid = (anchored or tracked) and captured_at - self.anchor_time <= self.ANCHOR_LIFETIME
        valid &= np.linalg.norm(self.offset - self.anchor_offset) <= 160
        self.last_time = captured_at
        self.previous = gray
        if valid and anchored and captured_at - self.extend_time >= self.EXTEND_INTERVAL:
            self.extend_time = captured_at
            self._extend(gray, mask)
        if not valid:
            self.points = None
            return None
        return {
            "area_id": self.area_id, "kind": "unknown", "surface_id": None, "feet": None,
            "captured_at": captured_at, "stale": False,
            "projection": {"x": float(self.offset[0] - self.origin[0] * self.scale),
                           "y": float(self.offset[1] - self.origin[1] * self.scale),
                           "scale": self.scale, "revision": self.revision},
            "alignment": {"method": "background-registration", "support": self.support,
                          "residual_px": round(self.residual, 3),
                          "anchor_age_ms": round((captured_at - self.anchor_time) * 1000, 1)},
            "reason": "Saved terrain aligned to fresh background features; not player location",
        }
