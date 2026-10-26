"""Read-only live position on one taught area, plus walk calibration. Never sends input.

The minimap marker places the player; the fused MinimapTracker confirms platforms.
Walk calibration pairs the marker with name-tag feet registered against the
reference view. Registration is slow, so it runs on one background thread.
"""

import json
import math
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict

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
from .map_teacher import MapTeacher, problems
from .minimap_reader import AreaMinimap, MinimapFix
from .perception import Detection, Observation
from .profiles import AreaStore, contains
from .teaching_drafts import TeachingDrafts, basis

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
        self.missed = 0  # screenshots kept when the minimap could not be read while teaching
        self.teach_calibrating = False
        self.proposal: dict | None = None
        self.preview: tuple[float, dict] | None = None
        self.drafts = TeachingDrafts(store.directory, area_id)
        self.draft_revision = 0
        self.draft_id = uuid.uuid4().hex
        self.draft_saved_at: float | None = None
        self.draft_error: str | None = None
        self.interrupted = False
        self.checkpoint_at = 0.0
        self.checkpoint_count = 0
        self.checkpoint_log_count = 0
        self.checkpoint_marker: tuple | None = None
        self.map_receipt: dict | None = None
        self._load(area_id)
        self._recover_draft()

    def _recover_draft(self) -> None:
        try:
            saved = self.drafts.load()
            if saved is None:
                self._import_legacy_log()
                return
            self.draft_revision = saved["revision"]
            if saved["phase"] in {"used", "discarded"}:
                return
            self.draft_id, self.draft_saved_at = saved["id"], saved["saved_at"]
            if saved["basis"] != basis(self.profile):
                raise ValueError("Saved map changed; teaching draft preserved for recovery")
            if saved.get("teacher") is not None:
                self.finished = MapTeacher.restore(saved["teacher"])
                self._name_context(self.finished)
                self.checkpoint_count = len(self.finished.samples)
                self.checkpoint_log_count = len(self.finished.log)
                if saved["phase"] == "review":
                    self.proposal = self.finished.geometry()
                else:
                    self.interrupted = True
            else:
                self.samples = [(tuple(a), tuple(b)) for a, b in saved.get("pairs", [])]
                self.interrupted = True
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.draft_error = f"Draft recovery: {error}"

    def _import_legacy_log(self) -> None:
        """Recover the last Finish result without replacing the saved map."""
        if self.tracker is None:
            return
        logs = sorted((self.store.directory / "teaching").glob(
            f"{self.profile['id']}-[0-9]*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not logs:
            return
        path = logs[-1]
        if path.stat().st_size > 16_000_000:
            raise ValueError("Legacy log too large; preserved for recovery")
        rows = [json.loads(row) for row in path.read_text("utf-8").splitlines()]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("Invalid legacy teaching log; original file preserved")
        proposal = rows[-1].get("proposal") if rows else None
        if not proposal:
            return
        if all(self.profile[key] == proposal[key] for key in ("platforms", "ropes", "links")):
            return  # This result has already been installed as the saved map.
        transform = self.tracker.transform
        teacher = MapTeacher.restore({
            "transform": asdict(transform),
            "samples": [{"t": row["t"], "kind": row["kind"], "dot": row["sample_dot"],
                         "feet": transform.to_area(*row["sample_dot"])}
                        for row in rows if "sample_dot" in row],
            "log": [row for row in rows if "reason" in row],
        })
        self._name_context(teacher)
        actual = teacher.geometry()
        def plain(value: dict) -> dict:
            return {**{k: value[k] for k in ("links", "boundary", "problems")},
                    **{k: [{field: item[field] for field in ("id", "start", "end")}
                           for item in value[k]] for k in ("platforms", "ropes")}}
        if plain(actual) != plain(proposal):
            raise ValueError("Legacy log/calibration mismatch; original log preserved")
        self._name_context(teacher)
        self.finished, self.proposal = teacher, teacher.geometry()
        self._checkpoint(force=True)

    def _checkpoint(self, *, force: bool = False) -> None:
        teacher = self.teacher or self.finished
        if teacher is None and not self.teach_calibrating and not self.interrupted:
            return
        now = time.perf_counter()
        marker = (len(teacher.samples), len(teacher.log), bool(self.proposal), self.interrupted
                  ) if teacher else (len(self.samples or []), self.interrupted)
        if not force and marker == self.checkpoint_marker:
            return
        if not force and now - self.checkpoint_at < 1:
            return
        try:
            if self.draft_error and self.draft_error.startswith("Draft recovery:"):
                return  # Never overwrite an unreadable or conflicting checkpoint.
            saved = self.drafts.save({
                "id": self.draft_id, "basis": basis(self.profile),
                "base_revision": self.profile["revision"], "reference": self.view_id,
                "phase": "review" if self.proposal else "recording" if teacher else "calibrating",
                "teacher": teacher.checkpoint() if teacher else None,
                "pairs": self.samples or [],
            }, self.draft_revision)
            self.draft_revision, self.draft_saved_at = saved["revision"], saved["saved_at"]
            self.checkpoint_count = len(teacher.samples) if teacher else len(self.samples or [])
            self.checkpoint_log_count = len(teacher.log) if teacher else 0
            self.draft_error = None
            self.checkpoint_marker = marker
        except (OSError, ValueError, TypeError) as error:
            self.draft_error = f"Draft not saved: {error}"
        self.checkpoint_at = now

    def _name_context(self, teacher: MapTeacher) -> None:
        registry = teacher.identities
        if self.profile["platforms"]:
            registry.setdefault("floor_y", max(max(p["start"]["y"], p["end"]["y"])
                                               for p in self.profile["platforms"]))
        registry.setdefault("center_x", self.profile["boundary"]["x"]
                            + self.profile["boundary"]["width"] / 2)

    def _new_teacher(self) -> MapTeacher:
        assert self.tracker is not None
        teacher = MapTeacher(self.tracker.transform)
        teacher.identities["surfaces"] = {
            kind: [p for p in self.profile[kind] if p.get("name")]
            for kind in ("platforms", "ropes")}
        self._name_context(teacher)
        return teacher

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
        if self.teacher is not None and fix.canvas is None and self.missed < 5:
            self._save_miss(image)
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
            self.teacher = self._new_teacher()
        if self.teacher is not None:
            self.teacher.add(fix, player, shift, now)
        self._checkpoint()

    def _teaching_status(self, now: float) -> dict:
        phase = ("conflict" if self.draft_error and self.draft_error.startswith("Draft recovery:")
                 else "interrupted" if self.interrupted
                 else "calibrating" if self.teach_calibrating else "recording" if self.teacher
                 else "review" if self.proposal else None)
        if self.teacher is not None and (self.preview is None or now - self.preview[0] >= 1):
            self.preview = (now, self.teacher.geometry())
        geometry = self.proposal or (self.preview[1] if self.preview and self.teacher else None)
        if geometry is None and self.interrupted and self.finished is not None:
            geometry = self.finished.geometry()
        draft_geometry = geometry is not None
        if geometry is None and phase is None:
            geometry = {key: self.profile[key] for key in
                        ("platforms", "ropes", "links", "boundary")}
        teacher = self.teacher or self.finished
        log = teacher.log if teacher else []
        misses = sum(row.get("dot") is None for row in log)
        evidence = sorted((self.store.directory / "teaching").glob(
            f"{self.profile['id']}-miss-*.png"), key=lambda p: p.stat().st_mtime)[-5:]
        status = {"phase": phase, "geometry": geometry,
                "samples": len(teacher.samples) if teacher else 0,
                "draft": {"id": self.draft_id, "revision": self.draft_revision,
                          "saved_at": self.draft_saved_at, "error": self.draft_error,
                          "pending": (len(teacher.samples) != self.checkpoint_count
                                      or len(teacher.log) != self.checkpoint_log_count)
                          if teacher else len(self.samples or []) != self.checkpoint_count,
                          "saved": self.draft_saved_at is not None and not self.draft_error},
                "map_revision": self.profile["revision"], "map_receipt": self.map_receipt,
                "health": {"checks": len(log), "misses": misses,
                           "last_reason": log[-1].get("reason") if log else None},
                "references": self.profile["views"],
                "evidence": [path.name for path in evidence],
                "geometry_source": "draft" if draft_geometry else "active_map"}
        self.teaching_snapshot = status
        return status

    def begin_teaching(self) -> dict:
        """Record the operator's play; calibrate first when the area has no calibration."""
        if self.draft_error or self.finished is not None or self.interrupted:
            raise ValueError("Resume or explicitly discard the existing teaching draft first")
        if self.teacher is not None or self.teach_calibrating:
            return self._teaching_status(time.perf_counter())
        self.proposal, self.preview = None, None
        self.draft_id = uuid.uuid4().hex
        if self.tracker is None:
            self.begin_calibration()
            self.teach_calibrating, self.teacher = True, None
        else:
            self.teach_calibrating, self.teacher = False, self._new_teacher()
        self._checkpoint(force=True)
        return self._teaching_status(time.perf_counter())

    def finish_teaching(self) -> dict:
        if self.teacher is None:
            raise ValueError("Start teaching and walk the map first")
        proposal = self.teacher.geometry()
        if not proposal["platforms"]:
            raise ValueError("No platform seen yet: walk along each floor and ledge")
        self.proposal, self.finished = proposal, self.teacher
        self.teacher, self.preview = None, None
        self._checkpoint(force=True)
        return {**proposal, "log": self._write_log(self.finished, proposal)}

    def resume_teaching(self) -> dict:
        """Back from review to recording, keeping everything walked so far."""
        if self.draft_error:
            raise ValueError(self.draft_error)
        if self.interrupted and self.finished is None:
            self.interrupted, self.teach_calibrating = False, True
            self._checkpoint(force=True)
            return self._teaching_status(time.perf_counter())
        if self.finished is None:
            raise ValueError("Nothing to resume; start teaching first")
        self.teacher, self.finished, self.proposal = self.finished, None, None
        self.interrupted = False
        self.teacher.last, self.teacher.climb_run = None, 0
        # Separate the recording segments even when Resume follows Finish immediately.
        self.teacher = MapTeacher.restore(self.teacher.checkpoint())
        self._checkpoint(force=True)
        return self._teaching_status(time.perf_counter())

    def pause_teaching(self) -> dict:
        if self.teacher is not None:
            self.finished, self.teacher = self.teacher, None
        self.interrupted, self.teach_calibrating, self.preview = True, False, None
        self._checkpoint(force=True)
        return self._teaching_status(time.perf_counter())

    def checkpoint_teaching(self) -> dict:
        self._checkpoint(force=True)
        return self._teaching_status(time.perf_counter())

    def _save_miss(self, image: np.ndarray) -> None:
        """Keep a few frames where the minimap was unreadable, for diagnosis."""
        self.missed += 1
        directory = self.store.directory / "teaching"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(directory / f"{self.profile['id']}-miss-{time.time_ns()}.png"), image)
        except (OSError, cv2.error):
            pass

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

    def save_teaching(self, *, confirm_partial: bool = False) -> dict:
        if self.proposal is None:
            raise ValueError("Finish teaching before saving the map")
        geometry = self.proposal
        issue = problems(geometry["platforms"], geometry["ropes"], geometry["links"])
        boundary = geometry["boundary"]
        removed = sum(not (contains(boundary, zone["rect"]) and contains(boundary, {
            "x": zone["rect"]["x"] + zone["rect"]["width"],
            "y": zone["rect"]["y"] + zone["rect"]["height"]}))
            for zone in self.profile["zones"])
        if not confirm_partial and (issue["unreachable"] or issue["stranded"] or removed
                                    or len(geometry["platforms"]) < len(self.profile["platforms"])):
            return {"requires_confirmation": True,
                    "reason": "This replaces the saved map with an incomplete or smaller map",
                    "platforms_before": len(self.profile["platforms"]),
                    "platforms_after": len(geometry["platforms"]), "zones_removed": removed}
        saved = self.store.save_geometry(self.profile["id"], self.profile["revision"],
                                         self.proposal)
        self.proposal, self.finished = None, None
        self._load(self.profile["id"])
        self.map_receipt = {"revision": self.profile["revision"], "saved_at": time.time()}
        saved["receipt"] = self.map_receipt
        try:
            retired = self.drafts.retire("used", self.draft_revision)
            self.draft_revision = retired["revision"]
        except (OSError, ValueError) as error:
            saved["warnings"].append(f"Map saved; old draft recovery copy retained: {error}")
        self.draft_saved_at = None
        return saved

    def cancel_teaching(self) -> dict:
        retired = self.drafts.retire("discarded", self.draft_revision)
        self.draft_revision, self.draft_saved_at = retired["revision"], None
        self.draft_error, self.interrupted = None, False
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
        self._checkpoint(force=True)
        self.pool.shutdown(wait=False, cancel_futures=True)
