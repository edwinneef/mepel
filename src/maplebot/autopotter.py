"""Screenshot-only HP/MP measurement and input-free potion decisions."""

import base64
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from .capture import Image
from .geometry import Rect


def fill_pixels(image: Image, resource: str) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    color = ((hue < 12) | (hue > 170)) if resource == "hp" else ((hue > 85) & (hue < 130))
    return color & (saturation > 110) & (value > 65)


@dataclass(frozen=True)
class BarReading:
    percent: float | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class BarReference:
    box: Rect
    interior: Rect
    width: int
    height: int
    image: Image

    @property
    def anchors(self) -> np.ndarray:
        hsv = cv2.cvtColor(self.image, cv2.COLOR_BGR2HSV)
        ring = np.ones(hsv.shape[:2], dtype=bool)
        ring[3:-3, 3:-3] = False
        return ring & (hsv[:, :, 1] < 35) & (hsv[:, :, 2] > 130)

    def read(self, image: Image, resource: str) -> BarReading:
        if image.shape[:2] != (self.height, self.width):
            return BarReading(None, 0, "Capture size changed; recalibrate HUD")
        box = self.box
        patch = image[box.y : box.feet, box.x : box.x + box.width]
        if np.count_nonzero(self.anchors) < 16:
            return BarReading(None, 0, "HUD border reference is insufficient")
        difference = np.max(np.abs(patch.astype(np.int16) - self.image.astype(np.int16)), axis=2)
        anchor_confidence = float(np.mean(difference[self.anchors] <= 24))
        if anchor_confidence < 0.9:
            return BarReading(None, anchor_confidence, "HUD frame missing, moved or covered")
        roi = self.interior
        strip = patch[roi.y : roi.feet, roi.x : roi.x + roi.width]
        filled = fill_pixels(strip, resource).mean(axis=0) >= 0.35
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        empty_pixels = (strip.max(axis=2) < 70) | ((hsv[:, :, 1] < 35) & (hsv[:, :, 2] < 230))
        empty = empty_pixels.mean(axis=0) >= 0.5
        known = float(np.mean(filled | empty))
        # Choose the left-filled/right-empty split with the fewest inconsistent columns.
        errors = np.r_[0, np.cumsum(~filled)] + np.r_[np.cumsum(filled[::-1])[::-1], 0]
        edge = int(np.argmin(errors))
        continuity = 1 - float(errors[edge]) / roi.width
        confidence = min(anchor_confidence, known, continuity)
        if confidence < 0.9:
            return BarReading(None, confidence, "Bar colors or fill pattern uncertain")
        return BarReading(round(100 * edge / roi.width, 1), confidence, "Visible bar fill")


class PotionMonitor:
    """Independent preview policy. This class has no keyboard/input dependency."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.settings = {"hp_threshold": 50.0, "mp_threshold": 30.0, "cooldown": 1.5}
        self.bars: dict[str, BarReference] = {}
        self.enabled = False
        self.low_frames = {"hp": 0, "mp": 0}
        self.last_suggestion = -math.inf
        self.last_time = -math.inf
        if path.exists():
            saved = json.loads(path.read_text("utf-8"))
            self._validate_settings(saved["settings"])
            self.settings.update(saved["settings"])
            for resource, bar in saved["bars"].items():
                self._resource(resource)
                decoded = cv2.imdecode(
                    np.frombuffer(base64.b64decode(bar["image"]), dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if decoded is None:
                    raise ValueError("Unreadable autopotter reference")
                box, interior = Rect(**bar["box"]), Rect(**bar["interior"])
                if decoded.shape[:2] != (box.height, box.width):
                    raise ValueError("Autopotter reference dimensions do not match")
                self.bars[resource] = BarReference(
                    box, interior, bar["width"], bar["height"], decoded
                )

    @staticmethod
    def _resource(resource: str) -> None:
        if resource not in {"hp", "mp"}:
            raise ValueError("Select HP or MP")

    @staticmethod
    def _validate_settings(settings: dict) -> None:
        for key, lower, upper in [
            ("hp_threshold", 0, 95),
            ("mp_threshold", 0, 95),
            ("cooldown", 0.5, 30),
        ]:
            value = settings[key]
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not lower <= value <= upper
            ):
                raise ValueError(f"{key} must be between {lower} and {upper}")

    def configure(self, *, hp_threshold: float, mp_threshold: float, cooldown: float) -> None:
        settings = dict(hp_threshold=hp_threshold, mp_threshold=mp_threshold, cooldown=cooldown)
        self._validate_settings(settings)
        self.settings = settings
        self.stop()
        self.save()

    def calibrate(self, resource: str, image: Image, box: Rect) -> None:
        self._resource(resource)
        if not Rect(0, 0, image.shape[1], image.shape[0]).contains(box):
            raise ValueError("HUD bar is outside the screenshot")
        if box.width < 30 or box.height < 10 or box.width < 3 * box.height:
            raise ValueError("Select the entire horizontal bar including its pale border")
        patch = image[box.y : box.feet, box.x : box.x + box.width].copy()
        reference = BarReference(
            box, Rect(3, 3, box.width - 6, box.height - 6), image.shape[1], image.shape[0], patch
        )
        anchor = reference.anchors
        if any(
            np.count_nonzero(side) < 2
            for side in [anchor[:3], anchor[-3:], anchor[:, :3], anchor[:, -3:]]
        ):
            raise ValueError("Include all four pale bar borders; exclude the HP/MP numbers")
        center = patch[3:-3, 3:-3]
        if fill_pixels(center, resource).mean() < 0.85:
            raise ValueError(f"Calibrate {resource.upper()} from a full, unobscured bar")
        self.bars[resource] = reference
        self.stop()
        self.save()

    def save(self) -> None:
        bars = {}
        for resource, bar in self.bars.items():
            ok, encoded = cv2.imencode(".png", bar.image)
            if not ok:
                raise OSError("Could not encode HUD reference")
            bars[resource] = {
                "box": asdict(bar.box),
                "interior": asdict(bar.interior),
                "width": bar.width,
                "height": bar.height,
                "image": base64.b64encode(encoded).decode("ascii"),
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"settings": self.settings, "bars": bars}), "utf-8")
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(f".{time.time_ns()}.bak"))
        temporary.replace(self.path)

    def start(self) -> None:
        if not self.bars:
            raise ValueError("Calibrate at least one full HP or MP bar first")
        self.stop()
        self.enabled = True

    def stop(self) -> None:
        self.enabled = False
        self.low_frames = {"hp": 0, "mp": 0}
        self.last_suggestion = self.last_time = -math.inf

    def snapshot(self) -> dict:
        return {
            "enabled": self.enabled,
            "preview_only": True,
            "input_sent": False,
            "settings": self.settings.copy(),
            "calibrated": list(self.bars),
        }

    def observe(self, image: Image, now: float, *, safe: bool = True) -> dict:
        readings = {resource: bar.read(image, resource) for resource, bar in self.bars.items()}
        suggestion = None
        reason = "Preview stopped" if self.bars else "Calibrate full HP/MP bars"
        fresh = math.isfinite(now) and now > self.last_time
        self.last_time = now
        if self.enabled:
            reason = "Above thresholds; preview only"
            if (
                not safe
                or not fresh
                or any(
                    reading.percent is None
                    for resource, reading in readings.items()
                    if self.settings[f"{resource}_threshold"] > 0
                )
            ):
                self.low_frames = {"hp": 0, "mp": 0}
                reason = "No suggestion: capture/calibration or HUD confidence insufficient"
            elif readings.get("hp") and readings["hp"].percent == 0:
                self.low_frames = {"hp": 0, "mp": 0}
                reason = "HP bar empty: possible death; check manually"
            else:
                for resource, reading in readings.items():
                    threshold = self.settings[f"{resource}_threshold"]
                    low = (
                        threshold > 0
                        and reading.percent is not None
                        and reading.percent <= threshold
                    )
                    self.low_frames[resource] = self.low_frames[resource] + 1 if low else 0
                if now - self.last_suggestion < self.settings["cooldown"]:
                    reason = "Preview cooldown; no repeated suggestion"
                else:
                    for resource in ("hp", "mp"):
                        if self.low_frames[resource] >= 2:
                            suggestion = resource
                            self.last_suggestion = now
                            reason = (
                                f"Would use {resource.upper()} potion; "
                                "preview only, effect unconfirmed"
                            )
                            break
                    if not suggestion and any(self.low_frames.values()):
                        reason = "Low resource: waiting for a second stable reading"
        return {
            **self.snapshot(),
            "readings": {resource: asdict(reading) for resource, reading in readings.items()},
            "suggestion": suggestion,
            "reason": reason,
        }

    def annotate(self, image: Image, status: dict) -> None:
        for resource, bar in self.bars.items():
            if image.shape[:2] != (bar.height, bar.width):
                continue
            reading = status["readings"][resource]
            value = reading["percent"]
            label = (
                f"{resource.upper()} {value:.0f}%"
                if value is not None
                else f"{resource.upper()} uncertain"
            )
            color = (70, 160, 240) if resource == "hp" else (240, 190, 80)
            box = bar.box
            cv2.rectangle(image, (box.x, box.y), (box.x + box.width, box.feet), color, 1)
            cv2.putText(
                image, label, (box.x, max(14, box.y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1
            )
