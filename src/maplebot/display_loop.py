"""Display-only drawings from fresh screenshots between slower recognition results.

Nothing here feeds decisions, input or safety gates. Recognition results are anchors;
between them boxes follow local image patches under stable IDs and expire quickly.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from .camera_motion import feature_translation
from .capture import Calibration, Capture, Image
from .display_terrain import DisplayTerrain
from .geometry import Rect
from .windows import Windows


@dataclass(frozen=True)
class DisplaySource:
    source_id: str
    view_generation: int
    hwnd: int | None
    manual: Rect | None
    calibration: Calibration | None
    # Published live detections plus the exact frame they describe.
    anchor: tuple[dict, Image] | None
    # area_id, revision, reference image, origin x, origin y, scale.
    terrain: tuple[str, int, Image, float, float, float] | None


def identity(item: dict) -> str:
    template = item.get("template") or ""
    return template[:template.rfind(":")] if template.startswith("catalog:") else template


@dataclass
class Track:
    id: str
    kind: str
    identity: str
    detection: dict
    template: np.ndarray
    x: float
    y: float
    seen: float
    anchored: float
    updated: float
    vx: float = 0.0
    vy: float = 0.0
    history: deque = field(default_factory=lambda: deque(maxlen=90))

    def at(self, moment: float) -> tuple[float, float]:
        """Top-left at the history sample closest to a recognition timestamp."""
        if not self.history:
            return self.x, self.y
        _, x, y = min(self.history, key=lambda item: abs(item[0] - moment))
        return x, y


class DisplayTracks:
    # Seconds since a recognition result confirming the track reached the display. Counted
    # from arrival, not capture: results arrive about 0.5 s late, so a capture-time clock
    # expired boxes just before each refresh and made the overlay blink.
    LIFETIME = 1.0
    VISIBLE = 0.5  # seconds since an image patch last confirmed the box
    SCORE = 0.6
    REFRESH = 0.8  # confident matches refresh the patch; recognition bounds any drift
    SPEED = 600.0  # px/s of search margin around a prediction
    ASSOCIATE = 48.0
    AMBIGUOUS = 16.0

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.tracks: dict[str, Track] = {}
        self.count = 0
        self.frame_id: str | None = None
        self.target: str | None = None
        self.gray: np.ndarray | None = None
        self.time: float | None = None

    @staticmethod
    def _search(gray: np.ndarray, template: np.ndarray, x: float, y: float,
                margin: float) -> tuple[int, int, float] | None:
        h, w = template.shape
        left, top = max(0, int(x - margin)), max(0, int(y - margin))
        right = min(gray.shape[1], int(x + w + margin) + 1)
        bottom = min(gray.shape[0], int(y + h + margin) + 1)
        if right - left < w or bottom - top < h or float(template.std()) < 6:
            return None
        scores = cv2.matchTemplate(gray[top:bottom, left:right], template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (px, py) = cv2.minMaxLoc(scores)
        return (left + px, top + py, score) if score >= DisplayTracks.SCORE else None

    def update(self, gray: np.ndarray, now: float) -> None:
        """Move existing tracks into a fresh frame."""
        for track in self.tracks.values():
            dt = max(0.0, now - track.updated)
            px, py = track.x + track.vx * dt, track.y + track.vy * dt
            found = self._search(gray, track.template, px, py, min(120.0, 12 + self.SPEED * dt))
            if found is None:
                track.vx = track.vy = 0.0
            else:
                if dt > 0:
                    track.vx = float(np.clip(0.5 * track.vx + 0.5 * (found[0] - track.x) / dt,
                                             -self.SPEED, self.SPEED))
                    track.vy = float(np.clip(0.5 * track.vy + 0.5 * (found[1] - track.y) / dt,
                                             -self.SPEED, self.SPEED))
                track.x, track.y, track.seen = found[0], found[1], now
                if found[2] >= self.REFRESH:
                    h, w = track.template.shape
                    track.template = gray[found[1]:found[1] + h, found[0]:found[0] + w].copy()
            track.updated = now
            track.history.append((now, track.x, track.y))
        self.tracks = {key: track for key, track in self.tracks.items()
                       if now - track.anchored <= self.LIFETIME}
        self.gray, self.time = gray, now

    def anchor(self, drawing: dict, image: Image) -> None:
        """Re-anchor to recognition: authoritative identities, boxes and templates."""
        frame = drawing["frame"]
        if frame["id"] == self.frame_id or frame.get("captured_at") is None:
            return
        self.frame_id, moment = frame["id"], frame["captured_at"]
        arrival = self.time if self.time is not None and self.time > moment else moment
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        items = ([("player", drawing["player"])] if drawing.get("player") else []) + [
            ("monster", item) for item in drawing.get("monsters") or []]
        pairs: dict[tuple[int, str], float] = {}
        for index, (kind, item) in enumerate(items):
            if kind == "player":
                continue
            center = (item["box"]["x"] + item["box"]["width"] / 2,
                      item["box"]["y"] + item["box"]["height"] / 2)
            for track in self.tracks.values():
                if track.kind == kind and track.identity == identity(item):
                    x, y = track.at(moment)
                    pairs[index, track.id] = float(np.hypot(
                        x + track.template.shape[1] / 2 - center[0],
                        y + track.template.shape[0] / 2 - center[1]))

        def clear(ranked: list[float]) -> bool:
            ranked = sorted(ranked)
            return ranked[0] <= self.ASSOCIATE and (
                len(ranked) < 2 or ranked[1] - ranked[0] >= self.AMBIGUOUS)

        # An identity carries over only when the match is unambiguous in both directions.
        candidates = [
            (distance, index, key) for (index, key), distance in pairs.items()
            if distance == min(d for (i, _), d in pairs.items() if i == index)
            and clear([d for (i, _), d in pairs.items() if i == index])
            and clear([d for (_, k), d in pairs.items() if k == key])
        ]
        assigned: dict[int, str] = {}
        for _, index, key in sorted(candidates):
            if index not in assigned and key not in assigned.values():
                assigned[index] = key
        tracks: dict[str, Track] = {}
        target = drawing.get("target")
        self.target = None
        for index, (kind, item) in enumerate(items):
            box = Rect(**item["box"])
            left, top = max(0, box.x), max(0, box.y)
            right = min(gray.shape[1], box.x + box.width)
            bottom = min(gray.shape[0], box.y + box.height)
            if right - left < 4 or bottom - top < 4:
                continue
            if kind == "player":
                key = "player"
            elif item.get("track_id"):
                key = item["track_id"]
            elif index in assigned:
                key = assigned[index]
            else:
                self.count += 1
                key = f"monster:{self.count}"
            old = self.tracks.get(key)
            template = gray[top:bottom, left:right].copy()
            if (old is not None and self.gray is not None and self.time is not None
                    and self.time - old.seen <= self.VISIBLE):
                # Recognition describes an older frame. A live track keeps its current
                # place instead of snapping back; only its patch and identity refresh.
                h, w = template.shape
                cx = old.x + old.template.shape[1] / 2 - w / 2
                cy = old.y + old.template.shape[0] / 2 - h / 2
                found = self._search(self.gray, template, cx, cy, 16.0)
                if found is not None:
                    old.template, old.x, old.y, old.seen = template, found[0], found[1], self.time
                    old.history.append((self.time, old.x, old.y))
                old.detection, old.identity, old.anchored = item, identity(item), arrival
                tracks[key] = old
            else:
                track = Track(key, kind, identity(item), item, template, float(left), float(top),
                              moment, arrival, moment)
                track.history.append((moment, track.x, track.y))
                if self.gray is not None and self.time is not None and self.time > moment:
                    # Bring the recognition box forward to the newest displayed frame.
                    dt = self.time - moment
                    found = self._search(self.gray, track.template, track.x, track.y,
                                         min(200.0, 24 + self.SPEED * dt))
                    if found is not None:
                        track.x, track.y, track.seen = found[0], found[1], self.time
                    track.updated = self.time
                    track.history.append((self.time, track.x, track.y))
                tracks[key] = track
            if target and kind == "monster" and item["box"] == target.get("box"):
                self.target = key

        def center(track: Track) -> tuple[float, float]:
            return (track.x + track.template.shape[1] / 2, track.y + track.template.shape[0] / 2)

        # A single recognition miss keeps a visible track (and its ID) until its lifetime
        # ends, unless another track now covers the same place.
        hidden = {item["track_id"] for item in drawing.get("enemy_tracks") or []
                  if item["state"] != "visible"}
        for key, old in self.tracks.items():
            if (key in tracks or key in hidden or self.time is None
                    or self.time - old.seen > self.VISIBLE):
                continue
            ox, oy = center(old)
            if all(np.hypot(ox - x, oy - y) >= max(old.template.shape) / 2
                   for x, y in map(center, tracks.values())):
                tracks[key] = old
        self.tracks = tracks

    def boxes(self) -> tuple[Rect, ...]:
        return tuple(Rect(round(track.x), round(track.y), track.template.shape[1],
                          track.template.shape[0]) for track in self.tracks.values())

    def items(self, now: float) -> tuple[dict | None, list[dict], dict | None]:
        visible = {}
        for key, track in self.tracks.items():
            if now - track.seen > self.VISIBLE:
                continue
            box = {"x": round(track.x, 1), "y": round(track.y, 1),
                   "width": track.template.shape[1], "height": track.template.shape[0]}
            visible[key] = {**track.detection, "box": box, "track_id": key}
        player = visible.pop("player", None)
        target = visible.get(self.target) if self.target else None
        return player, list(visible.values()), target


class DisplayLoop:
    """Latest-only drawing packets. Captures only while a client recently asked."""

    DEMAND_SECONDS = 2.0

    def __init__(self, source: Callable[[], DisplaySource | None], fps: float, *,
                 capture_factory: Callable[[], Capture] | None = None) -> None:
        self.source = source
        self.interval = 1 / fps if fps > 0 else None
        self.capture_factory = capture_factory or (lambda: Capture(Windows()))
        self.lock = threading.Lock()
        self.latest: dict | None = None
        self.demand = float("-inf")
        self.closed = threading.Event()
        self.wake = threading.Event()
        self.worker: threading.Thread | None = None
        self.tracks = DisplayTracks()
        self.terrain = DisplayTerrain()
        self.source_key: tuple | None = None
        self.terrain_key: tuple | None = None
        self.sequence = 0

    def start(self) -> None:
        if self.interval is None or self.worker is not None:
            return
        self.worker = threading.Thread(target=self._run, name="display", daemon=True)
        self.worker.start()

    def close(self) -> None:
        self.closed.set()
        self.wake.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=3)

    def drawings(self) -> dict | None:
        self.demand = time.monotonic()
        self.wake.set()
        with self.lock:
            return self.latest

    def _publish(self, packet: dict | None) -> None:
        with self.lock:
            self.latest = packet

    def _reset(self) -> None:
        self.tracks.reset()
        self.terrain.reset()
        self.source_key = self.terrain_key = None

    def _run(self) -> None:
        capture: Capture | None = None
        try:
            while not self.closed.is_set():
                if time.monotonic() - self.demand > self.DEMAND_SECONDS:
                    self._publish(None)
                    self._reset()
                    self.wake.wait(1)
                    self.wake.clear()
                    continue
                began = time.perf_counter()
                try:
                    capture = capture or self.capture_factory()
                    self._publish(self.step(capture))
                except Exception:
                    # Display-only: any failure clears drawings; the worker owns alarms.
                    self._publish(None)
                    self._reset()
                    self.closed.wait(0.25)
                self.closed.wait(max(0.0, self.interval - (time.perf_counter() - began)))
        finally:
            if capture:
                capture.close()

    def step(self, capture: Capture) -> dict | None:
        source = self.source()
        if source is None or source.anchor is None or not (source.hwnd or source.manual):
            self._reset()
            return None
        key = (source.source_id, source.view_generation)
        if key != self.source_key:
            self._reset()
            self.source_key = key
        began = time.perf_counter()
        captured_at = time.time()
        if source.hwnd:
            image, _, _ = capture.window(source.hwnd, source.calibration)
        else:
            image = capture.grab(source.manual)
        captured = time.perf_counter()
        latest = self.source()
        drawing, anchor_image = source.anchor
        frame = drawing["frame"]
        if (latest is None or (latest.source_id, latest.view_generation) != key
                or image.shape != anchor_image.shape):
            self._reset()
            return None
        terrain = None
        if source.terrain:
            area_id, revision, reference, x, y, scale = source.terrain
            terrain_key = (area_id, revision, id(reference), key)
            if terrain_key != self.terrain_key:
                self.terrain_key = terrain_key
                if reference.shape == image.shape:
                    self.terrain.configure(reference, x, y, scale, area_id, revision)
                else:
                    self.terrain.reset()
            aligned = self.terrain.update(image, captured_at, self.tracks.boxes())
            if aligned:
                terrain = {**aligned, "alignment": {**aligned["alignment"], "valid": True}}
        elif self.terrain_key is not None:
            self.terrain.reset()
            self.terrain_key = None
        aligned_at = time.perf_counter()
        self.tracks.update(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), captured_at)
        self.tracks.anchor(drawing, anchor_image)
        player, monsters, target = self.tracks.items(captured_at)
        enemy_tracks = project_enemy_diagnostics(drawing, anchor_image, image, captured_at)
        finished = time.perf_counter()
        self.sequence += 1
        return {
            "frame": {
                "source_id": source.source_id,
                "id": f"{source.source_id}:display:{self.sequence}",
                "sequence": self.sequence, "captured_at": captured_at,
                "width": image.shape[1], "height": image.shape[0], "available": True,
            },
            "display": True,
            "player": player, "monsters": monsters, "target": target,
            "enemy_tracks": enemy_tracks,
            "position": drawing.get("position"), "terrain": terrain,
            "anchor": {"id": frame["id"], "captured_at": frame["captured_at"]},
            "timing": {"capture_ms": round((captured - began) * 1000, 2),
                       "terrain_ms": round((aligned_at - captured) * 1000, 2),
                       "tracks_ms": round((finished - aligned_at) * 1000, 2)},
        }


def project_enemy_diagnostics(drawing, anchor, image, now):
    """Move diagnostic markers with verified scenery, without renewing their evidence age."""
    tracks = drawing.get("enemy_tracks") or []
    age = now - drawing["frame"]["captured_at"]
    if not tracks or not 0 <= age <= .5:
        return []
    shift, confidence = feature_translation(cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY),
                                             cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    if confidence < .6:
        return []
    dx, dy = shift
    projected = []
    for track in tracks:
        moved = dict(track)
        for name in ("predicted_position", "ground_position"):
            x, y = track[name]
            moved[name] = (x + dx, y + dy)
        bounds = track.get("visible_bounds")
        if bounds:
            moved["visible_bounds"] = {**bounds, "x": bounds["x"] + dx, "y": bounds["y"] + dy}
        moved["observed"] = False
        projected.append(moved)
    return projected
