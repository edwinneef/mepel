"""Separate prediction and scoring processes for constructed reference-render scenes."""

import argparse
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from tools.alignment_corpus import CRITERIA, digest, point, write_report


def implementation():
    root = Path(__file__).resolve().parents[1]
    # Include imported preprocessing/geometry dependencies, not just the top-level locator.
    paths = sorted((root / "src/maplebot").glob("*.py"))
    paths += [Path(__file__), root / "tools/alignment_corpus.py"]
    return {str(p.relative_to(root)): digest(p) for p in paths}


def load_inputs(path):
    path = Path(path).resolve()
    value = json.loads(path.read_text("utf-8"))
    if value.get("evidence_kind") != "synthetic_reference_render":
        raise ValueError("Separate synthetic inputs required")
    if (value.get("criteria") != CRITERIA or len(value["maps"]) < 2
            or len(set(value["maps"])) != len(value["maps"])):
        raise ValueError("Frozen synthetic contract missing, weakened or duplicated")
    ids = [r["id"] for r in value["frames"]]
    if (len(ids) != len(set(ids))
            or any(r["map_id"] not in value["maps"] for r in value["frames"])):
        raise ValueError("Duplicate scene identity")
    return path, value


def input_asset(root, name, sha, folder):
    path = (root / name).resolve()
    if not path.is_relative_to(root / folder) or digest(path) != sha:
        raise ValueError("Changed or forbidden predictor asset")
    return path


def predict(inputs_path, track="detected_player", detections_path=None):
    """Labels, render metadata and camera answers are not arguments to this process."""
    from maplebot.first_visit import FirstVisitLocator

    path, inputs = load_inputs(inputs_path)
    if track not in {"detected_player", "oracle_player_geometry"}:
        raise ValueError("Unknown player evidence track")
    if track == "oracle_player_geometry" and detections_path:
        raise ValueError("Oracle and detected-player tracks cannot be mixed")
    frozen, input_hash = implementation(), digest(path)
    detections_hash = digest(detections_path) if detections_path else None
    detections = json.loads(Path(detections_path).read_text("utf-8")) if detections_path else {}
    rows, models = [], {}
    for item in inputs["frames"]:
        frame = input_asset(path.parent, item["frame"], item["sha256"], "frames")
        geometry = input_asset(path.parent, item["geometry"], item["geometry_sha256"], "geometry")
        image = cv2.imread(str(frame))
        if image is None:
            raise ValueError("Cannot read synthetic frame")
        source = json.loads(geometry.read_text("utf-8"))
        if set(source) != {"id", "miniMap", "footholds", "ladderRopes"}:
            raise ValueError("Unexpected runtime geometry fields; evaluation metadata forbidden")
        if item["geometry_sha256"] not in models:
            models[item["geometry_sha256"]] = FirstVisitLocator(source)
        model = models[item["geometry_sha256"]]
        observation = detections.get(item["id"])
        player = item.get("oracle_player") if track == "oracle_player_geometry" else None
        if track == "detected_player" and observation:
            if observation["sha256"] != item["sha256"]:
                raise ValueError("Player detection belongs to another frame")
            player = observation["player"]
        start = time.perf_counter()
        try:
            result = model.locate(image, player)
        except (ValueError, cv2.error) as error:
            result = {"xy": None, "state": "uncertain", "reason": str(error)}
        interval = None
        candidate = result.get("candidate_xy")
        uncertainty = (result.get("geometry") or {}).get("uncertainty_xy")
        if candidate is not None and uncertainty is not None:
            try:
                at, radius = point(candidate), point(uncertainty)
                if np.all(radius >= 0):
                    interval = np.column_stack((at - radius, at + radius)).tolist()
            except ValueError:
                pass
        rows.append({"id": item["id"], "map_id": item["map_id"], "sha256": item["sha256"],
                     "sequence": item["sequence"], "predicted_xy": result.get("xy"),
                     "candidate_xy": result.get("candidate_xy"), "state": result["state"],
                     "reported_interval_xy": interval,
                     "precision_verified": False, "reason": result.get("reason"),
                     "analysis_ms": (time.perf_counter() - start) * 1000})
    for item in inputs["frames"]:
        input_asset(path.parent, item["frame"], item["sha256"], "frames")
        input_asset(path.parent, item["geometry"], item["geometry_sha256"], "geometry")
    if implementation() != frozen or digest(path) != input_hash or (
            detections_path and digest(detections_path) != detections_hash):
        raise ValueError("Inputs or implementation changed during prediction")
    return {"schema_version": 1, "evidence_kind": "synthetic_reference_render",
            "input_sent": False, "native_acceptance": False, "track": track,
            "inputs_sha256": input_hash, "labels_sha256": inputs["labels_sha256"],
            "detections_sha256": detections_hash, "implementation_sha256": frozen,
            "rows": rows}


def score(inputs_path, predictions_path, labels_path):
    path, inputs = load_inputs(inputs_path)
    predictions = json.loads(Path(predictions_path).read_text("utf-8"))
    if (predictions.get("evidence_kind") != "synthetic_reference_render"
            or predictions["inputs_sha256"] != digest(path)
            or predictions["labels_sha256"] != inputs["labels_sha256"]
            or digest(labels_path) != inputs["labels_sha256"]):
        raise ValueError("Predictions and frozen labels/inputs do not belong together")
    labels = json.loads(Path(labels_path).read_text("utf-8"))
    if labels.get("evidence_kind") != "synthetic_reference_render":
        raise ValueError("Constructed labels required; native labels are separate")
    truth = {r["id"]: r for r in labels["frames"]}
    answers = {r["id"]: r for r in predictions["rows"]}
    expected = {r["id"]: r for r in inputs["frames"]}
    if (len(truth) != len(labels["frames"]) or len(answers) != len(predictions["rows"])
            or truth.keys() != expected.keys() or answers.keys() != expected.keys()):
        raise ValueError("Missing, extra or duplicated scenes")
    maps = []
    for key in inputs["maps"]:
        errors, observable, false_ready, first_fix, times = [], 0, 0, None, []
        refused = 0
        interval_errors = []
        scenes = [r for r in inputs["frames"] if r["map_id"] == key]
        for scene in scenes:
            label, result = truth[scene["id"]], answers[scene["id"]]
            if (label["method"] != "constructed_drawing_coordinates"
                    or label["sha256"] != scene["sha256"]
                    or result["sha256"] != scene["sha256"] or result["map_id"] != key):
                raise ValueError("Label or prediction identity changed")
            uncertainty = label["label_uncertainty_px"]
            valid = (label["source_pair_verified"] is True and type(uncertainty) in (float, int)
                     and 0 <= uncertainty <= CRITERIA["maximum_label_uncertainty_px"])
            visible = label["observable"] is True and valid
            observable += visible
            xy = result["predicted_xy"]
            refused += xy is None
            interval = result.get("reported_interval_xy")
            if interval is not None:
                bounds = np.array([point(v) for v in interval])
                if bounds.shape != (2, 2) or np.any(bounds[:, 0] > bounds[:, 1]):
                    raise ValueError("Invalid reported XY interval")
                truth_xy = point(label["truth_xy"])
                gap = np.maximum(np.maximum(bounds[:, 0] - truth_xy,
                                            truth_xy - bounds[:, 1]), 0)
                if visible:
                    interval_errors.append(float(np.linalg.norm(gap)))
            if xy is not None:
                error = float(np.linalg.norm(point(xy) - point(label["truth_xy"])))
                if visible:
                    errors.append(error)
                    if error <= CRITERIA["p95_error_px"] and first_fix is None:
                        first_fix = scene["sequence"] * inputs.get("frame_interval_s", .1)
                false_ready += not visible or error > CRITERIA["p95_error_px"]
            elif result.get("state") == "ready":
                false_ready += 1
            elapsed = result["analysis_ms"]
            if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("Invalid analysis duration")
            times.append(elapsed)
        coverage = len(errors) / observable if observable else 0
        p95 = float(np.percentile(errors, 95)) if errors else None
        passed = (bool(scenes) and observable > 0 and p95 is not None
                  and p95 <= CRITERIA["p95_error_px"]
                  and coverage >= CRITERIA["minimum_observable_coverage"] and false_ready == 0)
        maps.append({"map_id": key, "passed": passed, "scenes": len(scenes),
                     "observable": observable, "coverage": coverage, "p95_error_px": p95,
                     "false_ready": int(false_ready), "refused": refused,
                     "first_fix_delay_s": first_fix,
                     "p95_interval_error_px": float(np.percentile(interval_errors, 95))
                     if interval_errors else None,
                     "interval_reports": len(interval_errors),
                     "p95_analysis_ms": float(np.percentile(times, 95)) if times else None})
    return {"schema_version": 1, "evidence_kind": "synthetic_reference_render",
            "input_sent": False, "native_acceptance": False, "precision_verified": False,
            "track": predictions["track"], "inputs_sha256": digest(path),
            "predictions_sha256": digest(predictions_path), "labels_sha256": digest(labels_path),
            "implementation_sha256": predictions["implementation_sha256"],
            "assessment": {"passed": len(maps) >= CRITERIA["minimum_maps"]
                           and all(r["passed"] for r in maps), "maps": maps},
            "limitations": ["Constructed reference convention, not native client accuracy",
                            "Oracle-player track does not evaluate player recognition",
                            "First-fix delay uses the declared synthetic frame cadence",
                            "No contact, grip, route or gameplay acceptance"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("predict")
    run.add_argument("--inputs", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--track", choices=("detected_player", "oracle_player_geometry"),
                     default="detected_player")
    run.add_argument("--detections", type=Path)
    grade = commands.add_parser("score")
    for name in ("inputs", "predictions", "labels", "output"):
        grade.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    result = (predict(args.inputs, args.track, args.detections) if args.command == "predict"
              else score(args.inputs, args.predictions, args.labels))
    write_report(args.output, result)
    print(json.dumps({"report": str(args.output), "input_sent": False,
                      "native_acceptance": False, "assessment": result.get("assessment")}))


if __name__ == "__main__":
    main()
