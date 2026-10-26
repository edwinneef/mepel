"""Read-only live position on one taught area, plus walk calibration. Never sends input.

The minimap marker places the player; the fused MinimapTracker confirms platforms.
Walk calibration pairs the marker with name-tag feet registered against the
reference view. Registration is slow, so it runs on one background thread.
"""

import json
import math
import time
from concurrent.futures import Future, ThreadPoolExecutor

import cv2
import numpy as np

from .localization import (
    Location,
    MinimapTracker,
    MinimapTransform,
    Platform,
    ViewTransform,
    register_view,
)
from .map_teacher import MapTeacher
from .minimap_reader import AreaMinimap, MinimapFix
from .perception import Detection, Observation
from .profiles import AreaStore

STALE_SECONDS = 0.5
MAX_PAIRS = 400
AUTO_CALIBRATION_PAIRS = 20


def platforms(profile: dict) -> tuple[Platform, ...]:
    result = []
    for item in profile["platforms"]:
        left, right = sorted((item["start"], item["end"]), key=lambda p: p["x"])
        result.append(Platform(item["id"], int(left["x"]), int(right["x"]), int(round(left["y"])),
                               None if left["y"] == right["y"] else right["y"]))
    return tuple(result)


def _fresh(player: Detection | None) -> bool:
    return (player is not None and player.kind == "player" and not player.tracked
            and math.isfinite(player.confidence) and player.confidence >= 0.90)


def _percentiles(values: np.ndarray) -> dict:
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "max": float(values.max())}


class LivePosition:
    """Position on one saved area; reloads its calibration when the operator saves one."""

    def __init__(self, store: AreaStore, area_id: str) -> None:
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="walk-calibration")
        self.samples: list[tuple[tuple[float, float], tuple[float, float]]] | None = None
        self.pending: Future | None = None
        self.rejected = 0
        self.teacher: MapTeacher | None = None
        self.finished: MapTeacher | None = None  # kept so review can resume recording
        self.teach_calibrating = False
        self.proposal: dict | None = None
        self.preview: tuple[float, dict] | None = None
        self._load(area_id)

    def _load(self, area_id: str) -> None:
        profile = self.store.load(area_id)["profile"]
        calibration = profile.get("minimap_calibration")
        view = next((item for item in profile["views"]
                     if calibration and item["id"] == calibration["view_id"]),
                    profile["views"][0])
        body = self.store.frame(view["image"])
        reference = cv2.imdecode(np.frombuffer(body or b"", np.uint8), cv2.IMREAD_COLOR)
        if reference is None:
            raise ValueError("Reference image is missing or corrupt; capture the area again")
        self.minimap = AreaMinimap(reference)
        self.profile, self.reference, self.view_id = profile, reference, view["id"]
        self.view = ViewTransform(view["origin"]["x"], view["origin"]["y"], view["scale"])
        self.platforms = platforms(profile)
        self.calibration = calibration
        self.tracker = (
            MinimapTracker(MinimapTransform(**calibration["transform"]), self.platforms)
            if calibration else None
        )

    def read_map(self, image: np.ndarray) -> MinimapFix:
        return self.minimap.read(image)

    def update(self, image: np.ndarray, fix: MinimapFix, observation: Observation,
               now: float) -> dict:
        player = observation.player
        shift = observation.camera_shift if observation.camera_confidence >= 0.35 else None
        self._collect(image, fix, player)
        self._teach(fix, player, shift, now)
        if self.tracker is None:
            location = Location("unknown", None, None, "Walk calibration needed")
        else:
            location = self.tracker.update(fix, player, shift, now)
        canvas = fix.canvas
        return {
            "area_id": self.profile["id"],
            "area_name": self.profile["name"],
            "kind": location.kind,
            "surface_id": location.surface_id,
            "feet": list(location.reference_feet) if location.reference_feet else None,
            "reason": location.reason,
            "map": fix.reason,
            "canvas": {"x": canvas.x, "y": canvas.y, "width": canvas.width,
                       "height": canvas.height} if canvas else None,
            "marker": list(fix.dot) if fix.dot else None,
            "calibrated": self.tracker is not None,
            "calibration": self._calibration_status(),
            "teaching": self._teaching_status(now),
            "captured_at": time.time(),
            "input_sent": False,
        }

    def _teach(self, fix: MinimapFix, player: Detection | None,
               shift: tuple[float, float] | None, now: float) -> None:
        if (self.teach_calibrating and self.samples is not None
                and len(self.samples) >= AUTO_CALIBRATION_PAIRS):
            try:
                self.finish_calibration()
            except ValueError:
                return  # keep walking until the marker has moved far enough
            self.teach_calibrating = False
            assert self.tracker is not None
            self.teacher = MapTeacher(self.tracker.transform)
        if self.teacher is not None:
            self.teacher.add(fix, player, shift, now)

    def _teaching_status(self, now: float) -> dict:
        phase = ("calibrating" if self.teach_calibrating else "recording" if self.teacher
                 else "review" if self.proposal else None)
        if self.teacher is not None and (self.preview is None or now - self.preview[0] >= 1):
            self.preview = (now, self.teacher.geometry())
        geometry = self.proposal or (self.preview[1] if self.preview and self.teacher else None)
        return {"phase": phase, "geometry": geometry,
                "samples": len(self.teacher.samples) if self.teacher else 0}

    def begin_teaching(self) -> dict:
        """Record the operator's play; calibrate first when the area has no calibration."""
        self.proposal, self.preview = None, None
        if self.tracker is None:
            self.begin_calibration()
            self.teach_calibrating, self.teacher = True, None
        else:
            self.teach_calibrating, self.teacher = False, MapTeacher(self.tracker.transform)
        return self._teaching_status(time.perf_counter())

    def finish_teaching(self) -> dict:
        if self.teacher is None:
            raise ValueError("Start teaching and walk the map first")
        proposal = self.teacher.geometry()
        if not proposal["platforms"]:
            raise ValueError("No platform seen yet: walk along each floor and ledge")
        self.proposal, self.finished = proposal, self.teacher
        self.teacher, self.preview = None, None
        return {**proposal, "log": self._write_log(self.finished, proposal)}

    def resume_teaching(self) -> dict:
        """Back from review to recording, keeping everything walked so far."""
        if self.finished is None:
            raise ValueError("Nothing to resume; start teaching first")
        self.teacher, self.finished, self.proposal = self.finished, None, None
        return self._teaching_status(time.perf_counter())

    def _write_log(self, teacher: MapTeacher, proposal: dict) -> str | None:
        """Keep every teaching session's raw samples so a missed link can be diagnosed."""
        directory = self.store.directory / "teaching"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{self.profile['id']}-{time.time_ns()}.jsonl"
            with path.open("x", encoding="utf-8") as handle:
                for row in teacher.log:
                    handle.write(json.dumps(row) + "\n")
                for sample in teacher.samples:
                    handle.write(json.dumps({"t": sample.t, "kind": sample.kind,
                                             "sample_dot": list(sample.dot)}) + "\n")
                handle.write(json.dumps({"proposal": proposal}) + "\n")
            return str(path)
        except OSError:
            return None

    def save_teaching(self) -> dict:
        if self.proposal is None:
            raise ValueError("Finish teaching before saving the map")
        saved = self.store.save_geometry(self.profile["id"], self.profile["revision"],
                                         self.proposal)
        self.proposal, self.finished = None, None
        self._load(self.profile["id"])
        return saved

    def cancel_teaching(self) -> dict:
        if self.teach_calibrating:
            self.cancel_calibration()
        self.teacher, self.proposal, self.preview, self.teach_calibrating = None, None, None, False
        self.finished = None
        return self._teaching_status(time.perf_counter())

    def _collect(self, image: np.ndarray, fix: MinimapFix, player: Detection | None) -> None:
        if self.samples is None:
            return
        if self.pending is not None and self.pending.done():
            try:
                pair = self.pending.result()
            except Exception:  # a failed registration is just a lost pair
                pair = None
            if pair is None:
                self.rejected += 1
            else:
                self.samples.append(pair)
            self.pending = None
        if (self.pending is None and fix.dot is not None and _fresh(player)
                and len(self.samples) < MAX_PAIRS):
            assert player is not None
            dot, screen = fix.dot, (player.box.center[0], float(player.box.feet))
            self.pending = self.pool.submit(self._register, image.copy(), dot, screen)

    def _register(self, image: np.ndarray, dot: tuple[float, float],
                  screen: tuple[float, float]):
        offset = register_view(self.reference, image)
        if offset is None:
            return None
        return dot, self.view.to_area(screen[0] + offset[0], screen[1] + offset[1])

    def _calibration_status(self) -> dict:
        saved = self.calibration
        return {
            "active": self.samples is not None,
            "pairs": len(self.samples) if self.samples is not None else 0,
            "rejected": self.rejected,
            "saved": {key: saved[key] for key in ("residual_px", "pairs", "captured_at")}
            if saved else None,
        }

    def begin_calibration(self) -> dict:
        self.samples, self.rejected = [], 0
        return self._calibration_status()

    def cancel_calibration(self) -> dict:
        self.samples, self.pending = None, None
        return self._calibration_status()

    def finish_calibration(self) -> dict:
        if self.samples is None:
            raise ValueError("Begin walk calibration first")
        samples = list(self.samples)
        transform = MinimapTransform.fit([d for d, _ in samples], [f for _, f in samples])
        dots, feet = np.array([d for d, _ in samples]), np.array([f for _, f in samples])
        predicted = np.array([transform.to_area(*dot) for dot in dots])
        errors = np.abs(predicted - feet)
        calibration = {
            "view_id": self.view_id,
            "view_image": next(item["image"] for item in self.profile["views"]
                                if item["id"] == self.view_id),
            "transform": {"scale_x": transform.scale_x, "offset_x": transform.offset_x,
                          "scale_y": transform.scale_y, "offset_y": transform.offset_y},
            "residual_px": {"x": _percentiles(errors[:, 0]), "y": _percentiles(errors[:, 1])},
            "pairs": len(samples),
            "captured_at": time.time(),
        }
        saved = self.store.save_calibration(
            self.profile["id"], self.profile["revision"], calibration
        )
        self.samples, self.pending = None, None
        self._load(self.profile["id"])
        return {"calibration": calibration, "revision": saved["profile"]["revision"],
                "warnings": saved["warnings"]}

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
