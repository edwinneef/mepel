"""Read-only live position on one saved area, plus walk calibration. Never sends input.

The minimap marker places the player; the fused MinimapTracker confirms platforms.
Walk calibration pairs the marker with name-tag feet registered against the
reference view. Registration is slow, so it runs on one background thread. While the
operator walks an uncalibrated area with input idle, the same pairs are collected
passively; they are saved only when they pass the same fit and a one-marker-pixel residual.
"""

import math
import time
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy

import cv2
import numpy as np

from . import localization_supplement
from .geometry_anchors import GeometryTracking
from .localization import (
    Location,
    MinimapTracker,
    MinimapTransform,
    Platform,
    Rope,
    ViewTransform,
    register_view,
)
from .map_alignment import PositionInterval, align
from .minimap_reader import AreaMinimap, MinimapFix
from .motion_learning import PassiveMovement
from .perception import Detection, Observation
from .profiles import AreaStore

STALE_SECONDS = 0.5
MAX_PAIRS = 400
# Passive pairs are unattended, so they need more evidence than the operator's walk.
PASSIVE_MIN_PAIRS = 20
PASSIVE_FIT_EVERY = 5


def platforms(profile: dict) -> tuple[Platform, ...]:
    result = []
    for item in profile["platforms"]:
        left, right = sorted((item["start"], item["end"]), key=lambda p: p["x"])
        result.append(Platform(item["id"], int(left["x"]), int(right["x"]), int(round(left["y"])),
                               None if left["y"] == right["y"] else right["y"],
                               tuple((p["x"], p["y"]) for p in item.get("points", ()))))
    return tuple(result)


def _fresh(player: Detection | None) -> bool:
    return (player is not None and player.kind == "player" and not player.tracked
            and math.isfinite(player.confidence) and player.confidence >= 0.90)


def _percentiles(values: np.ndarray) -> dict:
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "max": float(values.max())}


def detect_area(store: AreaStore, image: np.ndarray) -> str:
    """The one saved area whose reference minimap matches this frame; refuse otherwise."""
    matches = []
    for item in store.list()["areas"]:
        profile = store.load(item["id"])["profile"]
        for view in profile["views"]:
            body = store.frame(view["image"])
            reference = cv2.imdecode(np.frombuffer(body or b"", np.uint8), cv2.IMREAD_COLOR)
            try:
                fix = AreaMinimap(reference, None).read(image) if reference is not None else None
            except ValueError:
                continue  # A reference without enough minimap terrain cannot identify a map.
            if fix is not None and fix.canvas is not None:
                matches.append((profile["id"], profile["name"]))
                break
    if not matches:
        raise ValueError("No saved map matches the minimap; open the minimap or choose the map")
    if len(matches) > 1:
        raise ValueError("Several saved maps match the minimap: "
                         + ", ".join(sorted(name for _, name in matches)) + "; choose one")
    return matches[0][0]


class LivePosition:
    """Position on one saved area; reloads its calibration when the operator saves one."""

    def __init__(self, store: AreaStore, area_id: str, *, capture_only: bool = False,
                 map_id: int | None = None, player_threshold: float = .90) -> None:
        self.store = store
        self.capture_only = capture_only
        self.map_id = map_id
        self.player_threshold = player_threshold
        self.supplement_tracker: MinimapTracker | None = None
        self.supplement_available = False
        self.supplement_reason = "Off; session-only observation"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="walk-calibration")
        self.samples: list[tuple[tuple[float, float], tuple[float, float]]] | None = None
        self.pending: Future | None = None
        self.rejected = 0
        self.passive: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self.passive_pending: Future | None = None
        self.passive_rejected = 0
        self.passive_fitted = 0
        self.passive_reason = "Off"
        self.passive_previous: tuple[float, float] | None = None  # time, feet screen y
        self._load(area_id)

    def _load(self, area_id: str) -> None:
        self.set_supplement(False)
        profile = self.store.load(area_id)["profile"]
        calibration = profile.get("minimap_calibration")
        # A saved walk calibration is the verified basis; it supersedes automatic alignment.
        automatic = None if calibration else profile.get("automatic_alignment")
        basis = calibration or automatic
        view = next((item for item in profile["views"]
                     if basis and item["id"] == basis["view_id"]),
                    profile["views"][0])
        body = self.store.frame(view["image"])
        reference = cv2.imdecode(np.frombuffer(body or b"", np.uint8), cv2.IMREAD_COLOR)
        if reference is None:
            raise ValueError("Reference image is missing or corrupt; capture the area again")
        terrain = None
        public = profile.get("public_map")
        map_id = public["id"] if public else self.map_id
        if map_id is not None:
            from .public_map import cached, picture

            def missing_cache(url: str) -> bytes:
                raise ValueError("Cache the public layout before starting position tracking")

            if public and public.get("provider") == "meowdb-classic":
                from .meowdb import cached_source

                source, digest = cached_source(self.store.directory, public)
            else:
                source, digest = cached(self.store.directory, map_id, missing_cache)
            if public and digest != public["sha256"]:
                raise ValueError("Cached public layout changed; import the map again")
            terrain = picture(source["miniMap"])
            if automatic:
                verified = align(reference, view["minimap"]["canvas"], source["miniMap"])
                if any(verified[k] != automatic[k] for k in
                       ("transform", "magnification", "picture_offset", "uncertainty_px")):
                    raise ValueError("Automatic map alignment changed; import again")
        self.minimap = AreaMinimap(reference, terrain)
        self.profile, self.reference, self.view_id = profile, reference, view["id"]
        self.view = ViewTransform(view["origin"]["x"], view["origin"]["y"], view["scale"])
        self.platforms = platforms(profile)
        self.calibration = calibration
        self.automatic = automatic
        self.geometry_tracking = GeometryTracking(source) if automatic else None
        self.interval = PositionInterval()
        self.interval_identity = None
        self.learning = PassiveMovement(self.store.directory / "movement-estimates" /
                                        f"{profile['id']}.json")
        self.tracker = (
            MinimapTracker(MinimapTransform(**basis["transform"]), self.platforms,
                           ropes=tuple(Rope(r["id"], r["start"]["x"],
                                            min(r["start"]["y"], r["end"]["y"]),
                                            max(r["start"]["y"], r["end"]["y"]))
                                       for r in profile["ropes"]),
                           player_threshold=self.player_threshold)
            if basis else None
        )
        self.supplement_available = self.capture_only and localization_supplement.matches(
            self.store.directory, self.profile)

    def supplement_status(self) -> dict:
        return {"available": self.supplement_available,
                "enabled": self.supplement_tracker is not None,
                "reason": self.supplement_reason,
                "platform": deepcopy(localization_supplement.PLATFORM)
                if self.supplement_tracker else None}

    def set_supplement(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise ValueError("Supplement enabled must be a boolean")
        if enabled:
            if (not self.capture_only or not self.tracker
                    or not localization_supplement.matches(self.store.directory, self.profile)):
                raise ValueError(
                    "Supplement needs capture-only observation on unchanged revision 4")
            if self.samples is not None:
                raise ValueError("Finish walk calibration before observing the supplement")
            if self.supplement_tracker is None:
                self.supplement_tracker = MinimapTracker(
                    self.tracker.transform,
                    platforms({"platforms": [localization_supplement.PLATFORM]}),
                    player_threshold=self.player_threshold)
            self.supplement_reason = "Provisional screenshot coverage; no movement evidence"
        else:
            self.supplement_tracker = None
            self.supplement_reason = "Off; session-only observation"
        return self.supplement_status()

    def read_map(self, image: np.ndarray) -> MinimapFix:
        return self.minimap.read(image)

    def update(self, image: np.ndarray, fix: MinimapFix, observation: Observation,
               now: float, *, captured_at: float | None = None,
               allow_supplement: bool = False, input_timing: dict | None = None,
               movement_keys: tuple[str, str] = ("left", "right"),
               observation_context: tuple | None = None,
               passive_calibration: bool = False) -> dict:
        captured_at = time.time() if captured_at is None else captured_at
        player = observation.player
        shift = observation.camera_shift if observation.camera_confidence >= 0.35 else None
        self._collect(image, fix, player)
        learned = (self._learn(image, fix, player, self._steady(player, shift, now))
                   if passive_calibration else None)
        if self.tracker is None:
            location = Location("unknown", None, None, "Walk calibration needed")
        else:
            location = self.tracker.update(fix, player, shift, now)
        alignment_status = None
        movement = None
        if self.automatic:
            uncertainty = self.automatic["uncertainty_px"]
            refined = None
            identity = player.template if _fresh(player) else None
            if identity != self.interval_identity:
                self.interval.reset()
                self.interval_identity = identity
            if (fix.dot is not None and _fresh(player) and shift is not None
                    and observation.camera_confidence >= .60):
                refined = self.interval.update(
                    self.tracker.transform.to_area(*fix.dot),
                    (player.box.center[0], player.box.feet), shift, now, uncertainty)
            else:
                self.interval.reset()
            if refined:
                feet, uncertainty = refined
            else:
                feet = location.reference_feet
            anchor = None
            if refined and _fresh(player):
                actors = [vars(item.box) for item in [player, *observation.monsters]]
                anchor = self.geometry_tracking.observe(
                    image, (player.box.center[0], player.box.feet),
                    self.tracker.transform.to_area(*fix.dot), now,
                    (observation_context, identity), shift, actors)
                x = anchor.get("candidate_x")
                if location.kind == "platform" and x is not None:
                    platform = next(p for p in self.platforms if p.id == location.surface_id)
                    if platform.left <= x <= platform.right:
                        anchor = {**anchor, "candidate_xy": [x, platform.y_at(x)],
                                  "uncertainty_xy": [anchor["uncertainty_x"], 12],
                                  "contact_verified": False}
            else:
                self.geometry_tracking.reset()
            alignment_status = {
                "mode": "automatic", "state": "uncertain" if feet else "aligning",
                "uncertainty_px": uncertainty, "precision_verified": False,
                "observed_surface": location.surface_id,
                "geometry": anchor,
                "reason": "Automatic map aligned; absolute position precision awaits validation",
            }
            movement = self.learning.observe(
                context=(self.profile["public_map"]["sha256"], player.template if player else None),
                clock=now, feet=feet, surface=location.surface_id,
                valid=bool(refined and location.kind == "platform"),
                timing=input_timing or {}, left=movement_keys[0], right=movement_keys[1])
            # Automatic registration is useful observation, not precision/contact proof.
            # Keep input consumers on their existing unknown-position refusal path.
            location = Location("unknown", None, feet, alignment_status["reason"])
        self.supplement_available = self.capture_only and localization_supplement.matches(
            self.store.directory, self.profile)
        provisional = False
        if self.supplement_tracker is not None:
            if (not allow_supplement or not self.supplement_available
                    or self.samples is not None):
                self.set_supplement(False)
                self.supplement_reason = "Disabled: observation mode or pinned map basis changed"
            else:
                extra = self.supplement_tracker.update(fix, player, shift, now)
                if (location.reason == "No unique taught platform or rope"
                        and extra.kind == "platform"):
                    location, provisional = extra, True
        canvas = fix.canvas
        # Project saved area coordinates into this same observation's crop pixels.
        # Never infer a camera transform from an unconfirmed/airborne position.
        projection = None
        if location.kind == "platform" and location.reference_feet and player is not None:
            x, y = location.reference_feet
            projection = {
                "x": player.box.center[0] - x * self.view.scale,
                "y": player.box.feet - y * self.view.scale,
                "scale": self.view.scale,
                "revision": self.profile["revision"],
            }
        return {
            "area_id": self.profile["id"],
            "area_name": self.profile["name"],
            "kind": location.kind,
            "surface_id": location.surface_id,
            "feet": list(location.reference_feet) if location.reference_feet else None,
            "projection": projection,
            "reason": "Provisional screenshot match; contact and movement not verified"
            if provisional else location.reason,
            "provisional": provisional,
            "supplement": self.supplement_status(),
            "map": fix.reason,
            "canvas": {"x": canvas.x, "y": canvas.y, "width": canvas.width,
                       "height": canvas.height} if canvas else None,
            "marker": list(fix.dot) if fix.dot else None,
            "calibrated": self.tracker is not None,
            "calibration": {**self._calibration_status(), "learned": learned},
            "map_alignment": alignment_status,
            "movement_learning": movement,
            "captured_at": captured_at,
            "input_sent": False,
        }

    def _collect(self, image: np.ndarray, fix: MinimapFix, player: Detection | None) -> None:
        if self.samples is None:
            return
        self.pending, lost = self._gather(self.samples, self.pending, image, fix, player)
        self.rejected += lost

    def _gather(self, samples: list, pending: Future | None, image: np.ndarray,
                fix: MinimapFix, player: Detection | None) -> tuple[Future | None, int]:
        lost = 0
        if pending is not None and pending.done():
            try:
                pair = pending.result()
            except Exception:  # a failed registration is just a lost pair
                pair = None
            if pair is None:
                lost = 1
            else:
                samples.append(pair)
            pending = None
        if (pending is None and fix.dot is not None and _fresh(player)
                and len(samples) < MAX_PAIRS):
            assert player is not None
            dot, screen = fix.dot, (player.box.center[0], float(player.box.feet))
            pending = self.pool.submit(self._register, image.copy(), dot, screen)
        return pending, lost

    def _steady(self, player: Detection | None, shift, now: float) -> bool:
        """The name tag kept its height since the last frame, allowing for the camera.

        While the player jumps or climbs, the minimap marker and the name tag update at
        different moments, so such pairs disagree in height; they are not collected.
        """
        if not _fresh(player) or shift is None:
            self.passive_previous = None
            return False
        assert player is not None
        previous, self.passive_previous = self.passive_previous, (now, float(player.box.feet))
        return (previous is not None and 0 < now - previous[0] <= 0.5
                and abs(player.box.feet - previous[1] - shift[1]) <= 2)

    def _learn(self, image: np.ndarray, fix: MinimapFix,
               player: Detection | None, steady: bool = True) -> dict | None:
        """Collect pairs while input is idle; save only a fit within one marker pixel."""
        if self.calibration is not None or self.samples is not None:
            self.passive, self.passive_pending = [], None
            self.passive_reason = "Off: walk calibration saved or in progress"
            return None
        self.passive_pending, lost = self._gather(self.passive, self.passive_pending,
                                                  image, fix, player if steady else None)
        self.passive_rejected += lost
        count = len(self.passive)
        if count < PASSIVE_MIN_PAIRS:
            self.passive_reason = f"Collecting pairs while you walk ({count}/{PASSIVE_MIN_PAIRS})"
            return None
        if count - self.passive_fitted < PASSIVE_FIT_EVERY and count < MAX_PAIRS:
            return None
        self.passive_fitted = count
        try:
            calibration = self._fit(self.passive)
        except ValueError as error:
            self.passive_reason = f"Keep walking: {error}"
            return None
        limit = calibration["transform"]["scale_x"]  # one minimap marker pixel
        residual = calibration["residual_px"]
        if residual["x"]["p95"] > limit or residual["y"]["p95"] > limit:
            self.passive_reason = (
                f"Pairs disagree (p95 x {residual['x']['p95']:.1f} / y "
                f"{residual['y']['p95']:.1f} px, limit {limit:g}); "
                + ("use walk calibration" if count >= MAX_PAIRS else "still collecting"))
            return None
        result = self._save_calibration(calibration)
        self.passive, self.passive_pending, self.passive_fitted = [], None, 0
        self.passive_reason = "Learned from passive pairs"
        return result

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
            "passive": {"pairs": len(self.passive), "rejected": self.passive_rejected,
                        "reason": self.passive_reason},
            "saved": {key: saved[key] for key in ("residual_px", "pairs", "captured_at")}
            if saved else None,
        }

    def begin_calibration(self) -> dict:
        if self.automatic:
            raise ValueError("Public map uses automatic alignment; no walk calibration needed")
        self.set_supplement(False)
        self.samples, self.rejected = [], 0
        self.passive, self.passive_pending = [], None
        return self._calibration_status()

    def cancel_calibration(self) -> dict:
        self.samples, self.pending = None, None
        return self._calibration_status()

    def finish_calibration(self) -> dict:
        if self.samples is None:
            raise ValueError("Begin walk calibration first")
        result = self._save_calibration(self._fit(self.samples))
        self.samples, self.pending = None, None
        return result

    def _fit(self, pairs: list) -> dict:
        samples = list(pairs)
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
        return calibration

    def _save_calibration(self, calibration: dict) -> dict:
        saved = self.store.save_calibration(
            self.profile["id"], self.profile["revision"], calibration
        )
        self._load(self.profile["id"])
        return {"calibration": calibration, "revision": saved["profile"]["revision"],
                "warnings": saved["warnings"]}

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
        try:
            self.learning.save()
        except OSError:
            pass  # Diagnostic cache failure cannot delay shutdown/input release.
