"""Screenshot-only enemy identity and diagnostic predictions; never attack evidence."""

import math
from collections import deque
from dataclasses import dataclass, field, replace

from .geometry import Rect


def species(template: str) -> str:
    return template.rsplit(":", 1)[0] if template.startswith("catalog:") else template


@dataclass(frozen=True)
class EnemyTrack:
    track_id: str
    enemy_type: str
    state: str
    predicted_position: tuple[float, float]
    ground_position: tuple[float, float]
    visible_bounds: Rect | None
    confidence: float
    uncertainty: tuple[float, float]
    last_seen: float
    observed: bool


@dataclass
class _Track:
    track_id: str
    detection: object
    ground: tuple[float, float]
    last_seen: float
    last_full: float
    confidence: float
    velocity: float = 0
    uncertainty: tuple[float, float] = (6, 4)
    state: str = "visible"
    history: deque = field(default_factory=lambda: deque(maxlen=5))
    hidden_since: float | None = None
    retained: bool = False
    observed: bool = True


class EnemyTracker:
    def __init__(self, config):
        self.config = config
        self.tracks: list[_Track] = []
        self.serial = 0
        self.at = None
        self.regions: tuple[Rect, ...] = ()
        self.platforms: tuple[tuple[float, float, float, float], ...] = ()

    def clear(self):
        self.tracks.clear()
        self.at = None
        self.regions, self.platforms = (), ()

    def translate_geometry(self, dx, dy):
        self.regions = tuple(box.translated(dx, dy) for box in self.regions)
        self.platforms = tuple((x1 + dx, y1 + dy, x2 + dx, y2 + dy)
                               for x1, y1, x2, y2 in self.platforms)

    def covered(self, box):
        return any(box.iou(region) > 0 for region in self.regions)

    def _ground(self, x, y):
        candidates = []
        for x1, y1, x2, y2 in self.platforms:
            if x1 <= x <= x2:
                height = y1 + (y2 - y1) * (x - x1) / max(1, x2 - x1)
                if abs(y - height) <= 18:
                    candidates.append(height)
        return x, min(candidates, key=lambda height: abs(y - height)) if candidates else y

    def _predict_ground(self, track, dx, dy, dt):
        x, y = track.ground[0] + dx, track.ground[1] + dy
        predicted = x + track.velocity * dt
        supports = []
        for x1, y1, x2, y2 in self.platforms:
            if x1 <= x <= x2:
                height = y1 + (y2 - y1) * (x - x1) / max(1, x2 - x1)
                if abs(y - height) <= 18:
                    supports.append((abs(y - height), x1, x2))
        if supports:
            _, left, right = min(supports)
            predicted = max(left, min(right, predicted))
        return self._ground(predicted, y)

    def prepare(self, now, shift, camera_confidence):
        """Compensate screen motion before matching; stale/unknown motion adds uncertainty."""
        if not math.isfinite(now):
            raise ValueError("Enemy tracking requires a finite timestamp")
        if self.at is not None and now <= self.at:
            self.clear()
        dt = max(0, now - self.at) if self.at is not None else 0
        self.at = now
        camera_ok = (camera_confidence >= .35
                     and all(math.isfinite(value) for value in shift))
        dx, dy = shift if camera_ok else (0, 0)
        self.translate_geometry(dx, dy)
        for track in self.tracks:
            track.history = deque(((t, x + dx, y + dy) for t, x, y in track.history), maxlen=5)
            track.ground = self._predict_ground(track, dx, dy, dt)
            ux, uy = track.uncertainty
            # A reversal can diverge at twice the walking speed in either direction.
            growth = 2 * max(abs(track.velocity), 35) * dt
            track.uncertainty = (min(240, ux + growth + (0 if camera_ok else 35)),
                                 min(80, uy + 3 * dt + (0 if camera_ok else 15)))
            track.observed = False
        self.tracks = [track for track in self.tracks
                       if now - track.last_full <= (self.config.enemy_occlusion_seconds
                                                    + self.config.enemy_lost_seconds)
                       and (track.state != "lost"
                            or now - track.last_seen <= self.config.enemy_lost_seconds)]

    def expected_box(self, track):
        box = track.detection.box
        return Rect(round(track.ground[0] - box.width / 2),
                    round(track.ground[1] - box.height), box.width, box.height)

    def update(self, detections, now, partials=()):
        """One-to-one conservative association; ambiguous evidence cannot create duplicates."""
        full = [item for item in detections
                if item.confidence >= self.config.confidence and not item.tracked]
        edges = []
        for i, track in enumerate(self.tracks):
            for j, item in enumerate(full):
                if species(item.template) != species(track.detection.template):
                    continue
                x, y = self._ground(item.box.center[0], item.box.feet)
                dx, dy = abs(x - track.ground[0]), abs(y - track.ground[1])
                ux, uy = track.uncertainty
                if dx <= min(180, ux + 18) and dy <= min(36, uy + 10):
                    score = dx / (ux + 18) + dy / (uy + 10) + .2 * (1 - item.confidence)
                    edges.append((score, i, j))
        assigned, used, plausible = {}, set(), {j for _, _, j in edges}
        for score, i, j in sorted(edges):
            if i in used or j in assigned:
                continue
            # Refuse crossings/merged sprites rather than guessing which ID survived.
            if any(abs(other - score) < .18 and (a == i or b == j)
                   for other, a, b in edges if (a, b) != (i, j)):
                continue
            assigned[j], used = self.tracks[i], used | {i}
        for j, item in enumerate(full):
            track = assigned.get(j)
            if track is None and j not in plausible:
                self.serial += 1
                ground = self._ground(item.box.center[0], item.box.feet)
                track = _Track(f"enemy:{self.serial}", item, ground, now, now, item.confidence)
                self.tracks.append(track)
                assigned[j] = track
            if track is not None:
                self._observe(track, item, now, partial=False)
        for track_id, item in partials:
            track = next((t for t in self.tracks if t.track_id == track_id), None)
            if (track is not None and not track.observed
                    and now - track.last_full <= self.config.enemy_occlusion_seconds):
                self._observe(track, item, now, partial=True)
        for track in self.tracks:
            if track.observed:
                continue
            if track.hidden_since is None:
                track.hidden_since = now
                previous = self.expected_box(track)
                if track.history:
                    _, x, y = track.history[-1]
                    previous = Rect(round(x - previous.width / 2), round(y - previous.height),
                                    previous.width, previous.height)
                track.retained = (self.covered(self.expected_box(track)) or self.covered(previous))
            age = now - track.last_full
            track.state = ("occluded" if track.retained
                           and age <= self.config.enemy_occlusion_seconds else "lost")
            track.confidence = min(track.confidence, math.exp(-age / 2))
        ids = {id(full[j]): track.track_id for j, track in assigned.items()}
        return [replace(item, track_id=ids.get(id(item))) for item in detections]

    def _observe(self, track, item, now, *, partial):
        ground = self._ground(item.box.center[0], item.box.feet)
        if not partial and track.history:
            at, x, _ = track.history[-1]
            if 0 < now - at <= .8:
                velocity = (ground[0] - x) / (now - at)
                track.velocity = max(-160, min(160, .4 * track.velocity + .6 * velocity))
            else:
                track.velocity = 0  # Hidden motion is not a velocity measurement.
        if not partial:
            track.history.append((now, *ground))
            track.last_full = now
            track.hidden_since, track.retained = None, False
        track.detection, track.ground, track.last_seen = item, ground, now
        track.confidence = item.confidence * (.8 if partial else 1)
        track.state = "partially_occluded" if partial else "visible"
        track.uncertainty = (12, 8) if partial else (6, 4)
        track.observed = True

    def snapshot(self):
        return [EnemyTrack(t.track_id, species(t.detection.template), t.state, t.ground,
                           t.ground, (t.detection.visible_bounds or t.detection.box)
                           if t.observed else None,
                           round(t.confidence, 4), t.uncertainty, t.last_seen, t.observed)
                for t in self.tracks]


def partial_enemies(image, templates, tracker, full):
    """Bounded masked-template search for exposed pixels on already known enemies only."""
    import cv2
    import numpy as np

    from .perception import Detection, masked_score

    if not tracker.regions:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found = []
    for track in tracker.tracks:
        expected = tracker.expected_box(track)
        if (not tracker.covered(expected)
                or any(item.box.iou(expected) > .3 for item in full)):
            continue
        variants = [t for t in templates if t.kind == "monster" and t.mask is not None
                    and species(t.name) == species(track.detection.template)]
        variants.sort(key=lambda t: t.name != track.detection.template)
        best = None
        for template in variants[:24]:
            anchor = template.anchor
            if anchor is None:
                continue
            height, width = template.image.shape[:2]
            left, top = round(track.ground[0] - width / 2), round(track.ground[1] - height)
            mask = np.zeros((height, width), np.uint8)
            mask[anchor.y:anchor.y + anchor.height, anchor.x:anchor.x + anchor.width] = (
                template.mask != 0)
            total = np.count_nonzero(mask)
            for region in tracker.regions:
                mask[max(0, region.y - top):max(0, region.feet - top),
                     max(0, region.x - left):max(0, region.x + region.width - left)] = 0
            ys, xs = np.nonzero(mask)
            if (len(xs) < max(24, .08 * total) or len(xs) > .9 * total
                    or np.ptp(xs) < 5 or np.ptp(ys) < 2):
                continue
            radius = min(80, math.ceil(track.uncertainty[0] + 8))
            x0, y0 = max(0, left - radius), max(0, top - 6)
            x1, y1 = min(image.shape[1], left + width + radius), min(
                image.shape[0], top + height + 6)
            if x1 - x0 < width or y1 - y0 < height:
                continue
            scores = cv2.matchTemplate(image[y0:y1, x0:x1], template.image,
                                       cv2.TM_SQDIFF_NORMED, mask=mask)
            scores[~np.isfinite(scores)] = 1
            _, _, minimum, _ = cv2.minMaxLoc(scores)
            x, y = x0 + minimum[0], y0 + minimum[1]
            # Verify with the actual foreground mask at the proposed position.
            visible = np.zeros((height, width), bool)
            visible[anchor.y:anchor.y + anchor.height, anchor.x:anchor.x + anchor.width] = (
                template.mask != 0)
            for region in tracker.regions:
                visible[max(0, region.y - y):max(0, region.feet - y),
                        max(0, region.x - x):max(0, region.x + region.width - x)] = False
            rows, cols = np.nonzero(visible)
            if (len(cols) < max(24, .08 * total) or len(cols) > .9 * total
                    or np.ptp(cols) < 5 or np.ptp(rows) < 2):
                continue
            reference = template.image[visible].astype(np.float32)
            observed = image[y:y + height, x:x + width][visible].astype(np.float32)
            reference_gray = template.gray[visible].astype(np.float32)
            if (np.std(reference_gray) < 10
                    or np.mean(np.max(np.abs(reference - observed), axis=1) <= 24) < .9):
                continue
            confidence = masked_score(observed, gray[y:y + height, x:x + width][visible]
                                      .astype(np.float32), reference, reference_gray)
            if confidence < .95:
                continue
            # Exposed pixels must be associated uniquely, including when enemies overlap.
            ground = (x + width / 2, y + height)
            if any(other is not track
                   and species(other.detection.template) == species(template.name)
                   and abs(other.ground[0] - ground[0]) <= other.uncertainty[0] + 18
                   and abs(other.ground[1] - ground[1]) <= 18 for other in tracker.tracks):
                continue
            item = Detection("monster", Rect(x, y, width, height), confidence, template.name,
                             tracked=True, track_id=track.track_id,
                             visible_bounds=Rect(x + int(cols.min()), y + int(rows.min()),
                                                 int(np.ptp(cols)) + 1, int(np.ptp(rows)) + 1))
            if best is None or confidence > best.confidence:
                best = item
        if best is not None:
            found.append((track.track_id, best))
    return found
