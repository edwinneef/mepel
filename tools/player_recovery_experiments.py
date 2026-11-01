"""Synthetic, offline search-prediction and glyph-overlap ablations.

Calls existing perception primitives without constructing a detector, controller,
capture source or runtime. Results cannot promote a predicted box or glyph overlap
to player identity, authorize input, or establish real-scene recovery accuracy.
"""
import argparse
import hashlib
import json
import math
import platform
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from maplebot.geometry import Rect
from maplebot.perception import (
    NAMETAG_TEXT,
    PREDICTION_RESPONSE,
    TemplateDetector,
    text_overlap,
)

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class TimedSearchPredictor:
    """Experimental search location only; evidence advances exclusively in observe()."""

    box: Rect
    confirmed: float = 0.0
    seen: float = 0.0
    confidence: float = .99
    velocity: tuple[float, float] | None = None
    camera: tuple[float, float] = (0.0, 0.0)
    camera_trusted: bool = True
    horizon_seconds: float = .45
    max_displacement: float = 80.0
    max_speed: float = 240.0

    def predict(self, now: float, shift: tuple[float, float], response: float):
        age = now - self.seen
        if not math.isfinite(now) or age < 0:
            raise ValueError("Prediction time must be finite and follow the observation")
        if response < PREDICTION_RESPONSE:
            self.camera_trusted = False
            self.velocity = None
            self.camera = (0.0, 0.0)
            return None, "camera_uncertain"
        if not self.camera_trusted:
            return None, "camera_needs_observation"
        self.camera = tuple(a + b for a, b in zip(self.camera, shift, strict=True))
        if age > self.horizon_seconds:
            return None, "horizon_exceeded"
        if self.velocity is None:
            return None, "velocity_uninitialized"
        movement = tuple(float(np.clip(v * age, -self.max_displacement, self.max_displacement))
                         for v in self.velocity)
        return self.box.translated(movement[0] + self.camera[0],
                                   movement[1] + self.camera[1]), "search_only"

    def observe(self, box: Rect, now: float) -> None:
        elapsed = now - self.seen
        if not math.isfinite(now) or elapsed <= 0:
            raise ValueError("Observations must have increasing finite timestamps")
        if self.camera_trusted:
            self.velocity = tuple(float(np.clip((b - a - shift) / elapsed,
                                                 -self.max_speed, self.max_speed))
                                  for a, b, shift in zip(self.box.center, box.center,
                                                        self.camera, strict=True))
        else:
            self.velocity = None
        self.box, self.confirmed, self.seen = box, now, now
        self.camera, self.camera_trusted = (0.0, 0.0), True


def fixture(box: Rect, now: float = 0.0):
    """Only the state touched by actual _predict/_learn_motion; no detector setup."""
    return SimpleNamespace(track=(box, now, now), world_step=(0.0, 0.0), predicted=None,
                           confidence=.99,
                           confirmed_sprites=SimpleNamespace(translate=lambda *_: None))


def synthetic_sequences() -> list[dict]:
    scenarios = [
        ("regular", [0, .1, .2, .3, .4], [0, 10, 20, 30, 40], [0] * 5, [1] * 5),
        ("irregular", [0, .1, .3, .35, .5], [0, 10, 30, 35, 50], [0] * 5, [1] * 5),
        ("stopped", [0, .1, .2, .3, .4], [0, 10, 10, 10, 10], [0] * 5, [1] * 5),
        ("reversal", [0, .1, .2, .3, .4], [0, 10, 0, -10, -20], [0] * 5, [1] * 5),
        ("camera_scroll", [0, .1, .2, .3, .4], [0, 10, 20, 30, 40],
         [0, -10, -10, -10, -10], [1] * 5),
        ("camera_loss", [0, .1, .2, .3, .4], [0, 10, 20, 30, 40],
         [0, -10, -10, -10, -10], [1, 1, .1, 1, 1]),
        ("long_gap", [0, .1, 1.1, 1.2, 1.3], [0, 10, 110, 120, 130], [0] * 5, [1] * 5),
    ]
    result = []
    for name, times, positions, shifts, responses in scenarios:
        camera = 0
        frames = []
        for index, (at, world_x, shift, response) in enumerate(
                zip(times, positions, shifts, responses, strict=True)):
            camera += shift
            frames.append({"at": at, "box": [100 + world_x + camera, 100, 44, 64],
                           "camera_shift": [shift, 0], "camera_response": response,
                           "observed": index in {0, 1, len(times) - 1}})
        result.append({"id": name, "frames": frames})
    return result


def _box(box: Rect | None):
    return [box.x, box.y, box.width, box.height] if box else None


def prediction_experiment(sequence: dict) -> dict:
    frames = sequence["frames"]
    initial = Rect(*frames[0]["box"])
    baseline = fixture(initial, frames[0]["at"])
    candidate = TimedSearchPredictor(initial, frames[0]["at"], frames[0]["at"])
    output = []
    previous = frames[0]["at"]
    for frame in frames[1:]:
        now = frame["at"]
        if not math.isfinite(now) or now <= previous:
            raise ValueError("Sequence timestamps must be finite and strictly increasing")
        previous = now
        truth = Rect(*frame["box"])
        shift = tuple(frame["camera_shift"])
        response = frame["camera_response"]
        before = {"baseline": [*baseline.track[1:], baseline.confidence],
                  "candidate": [candidate.confirmed, candidate.seen, candidate.confidence]}
        TemplateDetector._predict(baseline, shift, response)
        predicted, reason = candidate.predict(now, shift, response)
        after = {"baseline": [*baseline.track[1:], baseline.confidence],
                 "candidate": [candidate.confirmed, candidate.seen, candidate.confidence]}
        if before != after:
            raise AssertionError("A prediction advanced evidence freshness/confidence")
        entry = {"at": now, "observed": frame["observed"], "truth": _box(truth),
                 "baseline": _box(baseline.track[0]), "candidate": _box(predicted),
                 "baseline_reason": "search_only" if baseline.predicted is not None
                 else "unchanged_search_center",
                 "candidate_reason": reason, "evidence_before": before,
                 "evidence_after_prediction": after,
                 "baseline_error_px": math.dist(baseline.track[0].center, truth.center),
                 "candidate_error_px": math.dist(predicted.center, truth.center)
                 if predicted else None, "identity_confirmed_by_prediction": False}
        output.append(entry)
        if frame["observed"]:
            baseline.track = truth, now, now
            candidate.observe(truth, now)
        TemplateDetector._learn_motion(baseline, now)
    missing = [row for row in output if not row["observed"]]
    summaries = {}
    for method in ("baseline", "candidate"):
        errors = [row[f"{method}_error_px"] for row in missing
                  if row[f"{method}_error_px"] is not None]
        summaries[method] = {"missing_observation_frames": len(missing),
                             "predictions_scored": len(errors),
                             "abstained": len(missing) - len(errors),
                             "mean_error_px": sum(errors) / len(errors) if errors else None,
                             "max_error_px": max(errors) if errors else None}
    return {"id": sequence["id"], "constructed_frames": frames,
            "results": output, "missing_frame_summary": summaries}


def glyph_cases() -> tuple[np.ndarray, list[dict]]:
    name, scale, thickness = "HeneSyphilis", .55, 1
    font = cv2.FONT_HERSHEY_SIMPLEX
    (width, height), base = cv2.getTextSize(name, font, scale, thickness)
    shape = height + base + 4, width + 4
    template = np.zeros(shape, np.uint8)
    cv2.putText(template, name, (2, height + 2), font, scale, 255, thickness, cv2.LINE_8)
    mask = np.float32(template >= NAMETAG_TEXT)
    x, y = 12, 6

    def render(text=name):
        image = np.zeros((shape[0] + 12, shape[1] * 2 + 24), np.uint8)
        cv2.putText(image, text, (x + 2, y + height + 2), font, scale, 255,
                    thickness, cv2.LINE_8)
        return image

    cases = []
    for label, kind, text in (("complete", "positive", name),
                              ("shared_prefix", "negative", "HeneSyphiliX"),
                              ("adjacent_names", "negative", "HeneOther OtherName")):
        cases.append({"id": label, "kind": kind, "gray": render(text), "origin": [x, y]})
    left = render()
    left[y:y + shape[0], x:x + round(shape[1] * .3)] = 0
    bottom = render()
    bottom[y + round(shape[0] * .55):y + shape[0], x:x + shape[1]] = 0
    speckles = render()
    speckles[::3, ::4] = 0
    cloud = render("")
    cloud[y:y + shape[0], x:x + shape[1]] = 255
    for label, kind, image in (("left_occlusion", "partial_positive", left),
                                ("bottom_occlusion", "partial_positive", bottom),
                                ("glyph_dropouts", "partial_positive", speckles),
                                ("cloud", "negative", cloud)):
        cases.append({"id": label, "kind": kind, "gray": image, "origin": [x, y]})
    return mask, cases


def glyph_experiment() -> dict:
    template, cases = glyph_cases()
    threshold = .85
    results = []
    for case in cases:
        observed = np.uint8(case["gray"] >= NAMETAG_TEXT)
        variants = {
            "raw": observed,
            "opening_2x2": cv2.morphologyEx(observed, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)),
            "closing_3x3": cv2.morphologyEx(observed, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)),
        }
        scores = {}
        for name, mask in variants.items():
            overlaps = text_overlap(case["gray"], template, np.float32(mask))
            _, peak, _, (px, py) = cv2.minMaxLoc(overlaps)
            x, y = case["origin"]
            scores[name] = {"peak": float(peak),
                            "at_constructed_origin": float(overlaps[y, x + template.shape[1] - 1]),
                            "peak_origin": [px - template.shape[1] + 1, py],
                            "above_diagnostic_threshold": peak >= threshold,
                            "observed_white_pixels": int(mask.sum())}
        results.append({"id": case["id"], "kind": case["kind"], "scores": scores,
                        "identity_confirmed": False,
                        "gray_sha256": hashlib.sha256(case["gray"].tobytes()).hexdigest()})
    return {"diagnostic_threshold": threshold,
            "template_sha256": hashlib.sha256(template.tobytes()).hexdigest(),
            "template_shape": list(template.shape), "cases": results,
            "scope": "Generated OpenCV glyphs, not MapleStory pixels. Threshold is exploratory; "
            "a negative above it exposes primitive confusion, not full-detector false identity."}


def interval_filter(x: float, interval: tuple[float, float] | None, age: float,
                    *, ambiguous: bool = False, camera_known: bool = True) -> str:
    """Supplied screen interval can only reject; retained candidates remain unconfirmed."""
    if (interval is None or ambiguous or not camera_known or not math.isfinite(age)
            or age < 0 or age > .25):
        return "abstain"
    lo, hi = interval
    if not all(math.isfinite(value) for value in (x, lo, hi)) or lo > hi:
        return "abstain"
    return "reject" if x < lo or x > hi else "retain_unconfirmed"


def interval_experiment() -> list[dict]:
    cases = [("inside", 100, (80, 120), .1, False, True),
             ("outside_left", 60, (80, 120), .1, False, True),
             ("outside_right", 160, (80, 120), .1, False, True),
             ("stale", 160, (80, 120), .3, False, True),
             ("ambiguous", 160, (80, 120), .1, True, True),
             ("unknown_camera", 160, (80, 120), .1, False, False),
             ("missing_interval", 160, None, .1, False, True)]
    return [{"id": name, "candidate_x": x, "supplied_interval": interval, "age_seconds": age,
             "ambiguous": ambiguous, "camera_known": camera,
             "result": interval_filter(x, interval, age, ambiguous=ambiguous, camera_known=camera),
             "identity_confirmed": False}
            for name, x, interval, age, ambiguous, camera in cases]


def experiment_report() -> dict:
    sources = ["tools/player_recovery_experiments.py", "src/maplebot/perception.py",
               "src/maplebot/geometry.py"]
    return {
        "version": 1, "scope": "synthetic-only offline primitive ablations",
        "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                          for path in sources},
        "versions": {"python": platform.python_version(), "opencv": cv2.__version__,
                     "numpy": np.__version__},
        "predictor_parameters": {"max_horizon_seconds": .45, "max_displacement_px": 80,
                                 "max_speed_px_per_second": 240},
        "prediction": [prediction_experiment(sequence) for sequence in synthetic_sequences()],
        "glyph_morphology": glyph_experiment(), "supplied_interval_toys": interval_experiment(),
        "limitations": [
            "Baseline invokes actual TemplateDetector._predict/_learn_motion, isolated from "
            "full tracking expiry, association, fragments, local ROI, safety and recovery logic. "
            "Its unchanged track box during camera uncertainty is scored as a search fallback.",
            "Observed boxes and camera shifts are constructed truth, not detector measurements. "
            "The confirmed_sprites translation sink is inert; sprite association is not evaluated.",
            "Time normalization addresses cadence only. Stops and reversals without evidence "
            "remain unpredictable; compare abstentions with prediction error denominators.",
            "Experiment bounds are fixed illustrative values, not calibrated runtime defaults. "
            "Predictions never advance confidence, seen or confirmed times or authorize input.",
            "Morphology tests observed masks against an unchanged template using actual "
            "text_overlap. Synthetic text cannot establish real nametag recovery accuracy.",
            "Intervals are supplied screen-coordinate constraints only. No minimap marker "
            "detection, calibration, camera transform or real localization has been validated.",
            "No runtime promotion is justified by these primitive tests; use independent labelled "
            "raw frames and regression negatives before considering any production change.",
        ],
    }


def run(output: Path) -> dict:
    if output.exists():
        raise ValueError("Output must be a new path; existing evidence cannot be overwritten")
    report = experiment_report()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New JSON report path")
    args = parser.parse_args()
    try:
        run(args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Offline experiment failed: {error}\n")
    print(f"Saved synthetic-only experiments to {args.output}")


if __name__ == "__main__":
    main()
