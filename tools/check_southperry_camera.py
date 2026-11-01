"""Offline camera check against copied scenery references; no runtime changes or input."""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from maplebot.perception import CameraTracker
from tools.compare_southperry_scenery import agreement
from tools.export_classic_assets import check_output, digest, load_json, safe_path, write_json

MIN_FRACTION = {"house": .65, "house-decoration": .75}
MIN_MARGIN = .10
MAX_DISAGREEMENT = 1
CAMERA_CONFIDENCE = .60


def landmark(frame, sprite, minimum):
    mask = sprite[:, :, 3] == 255
    scores = cv2.matchTemplate(frame, sprite[:, :, :3], cv2.TM_SQDIFF_NORMED,
                               mask=mask.astype("uint8") * 255)
    scores[~np.isfinite(scores)] = np.inf
    _, _, (x, y), _ = cv2.minMaxLoc(scores)
    height, width = sprite.shape[:2]
    fraction = agreement(frame[y:y + height, x:x + width], sprite[:, :, :3], mask)["exact_fraction"]
    scores[max(0, y - 24):y + 25, max(0, x - 24):x + 25] = np.inf
    _, _, (sx, sy), _ = cv2.minMaxLoc(scores)
    second = agreement(frame[sy:sy + height, sx:sx + width], sprite[:, :, :3], mask)[
        "exact_fraction"]
    return {"top_left": [x, y], "exact_fraction": fraction, "second_exact_fraction": second,
            "accepted": fraction >= minimum and fraction - second >= MIN_MARGIN}


def reference(results, origins):
    if not all(row["accepted"] for row in results.values()):
        return None
    shifts = [np.subtract(results[name]["top_left"], origins[name]) for name in results]
    if np.max(np.abs(shifts[0] - shifts[1])) > MAX_DISAGREEMENT:
        return None
    return np.mean(shifts, axis=0)


def evaluate(assets, reference_path, recordings, output, selected_sessions=None):
    started = time.perf_counter()
    assets, recordings = safe_path(assets), safe_path(recordings)
    output = check_output(output, recordings, [])
    prior = load_json(reference_path)
    origins = prior["source_world_top_left"]
    sprites = {}
    pins = load_json(assets / "provenance.json")
    for name in MIN_FRACTION:
        path = assets / (name + ".png")
        if digest(path) != pins["outputs"][path.name]:
            raise ValueError("Scenery reference changed")
        sprites[name] = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    sessions = sorted({f["recording"] for a in prior["assets"].values() for f in a["frames"]})
    if selected_sessions:
        sessions = list(selected_sessions)
    result = {"scope": "Southperry diagnostic; frozen thresholds then full existing clips",
              "thresholds": {"min_exact": MIN_FRACTION, "min_margin": MIN_MARGIN,
                             "max_anchor_disagreement_px": MAX_DISAGREEMENT,
                             "camera_confidence": CAMERA_CONFIDENCE},
              "scenery_reference_sha256": digest(reference_path), "sessions": [],
              "runtime_camera_source_sha256": digest(Path("src/maplebot/perception.py")),
              "runtime_camera_fallback_sha256": digest(Path("src/maplebot/camera_motion.py")),
              "native_acceptance": False, "input_sent": False,
              "native_feet_contact_verified": False, "unseen_map_benchmark": False}
    output.mkdir()
    errors, drifts, shifts = [], [], []
    available = accepted = eligible = moving_pairs = camera_pairs = 0
    for session in sessions:
        root = safe_path(recordings / session)
        if root.parent != recordings:
            raise ValueError("Recording escaped source root")
        log = root / "decisions.jsonl"
        log_hash = digest(log)
        selected = []
        with log.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if (row.get("catalog") or {}).get("active_map") == "Southperry":
                    selected.append((row["frame"], row["captured_at"]))
        tracker, previous, cumulative = CameraTracker(), None, np.zeros(2)
        rows = []
        for index, (filename, timestamp) in enumerate(selected):
            eligible += 1
            path = safe_path(root / filename)
            if path.parent != root or path.suffix != ".png":
                raise ValueError("Frame escaped recording")
            if not path.is_file():
                rows.append({"frame": filename, "accepted": False,
                             "reason": "Existing PNG missing"})
                tracker, previous, cumulative = CameraTracker(), None, np.zeros(2)
                continue
            available += 1
            frame_hash = digest(path)
            frame = cv2.imread(str(path))
            if frame is None or frame.shape != (768, 1366, 3):
                raise ValueError("Unexpected frame dimensions")
            predictions = {name: landmark(frame, sprite, MIN_FRACTION[name])
                           for name, sprite in sprites.items()}
            shift = reference(predictions, origins)
            predicted, confidence = tracker.update(frame)
            row = {"frame": filename, "sha256": frame_hash, "captured_at": timestamp,
                   "landmarks": predictions, "accepted": shift is not None,
                   "runtime_shift": list(predicted), "runtime_confidence": confidence}
            if shift is not None:
                accepted += 1
                shifts.append(shift.tolist())
                row["scenery_translation"] = shift.tolist()
                if (previous is not None and 0 < timestamp - previous["at"] <= .5
                        and confidence >= CAMERA_CONFIDENCE):
                    delta = shift - previous["shift"]
                    error = np.array(predicted) - delta
                    errors.append(float(np.linalg.norm(error)))
                    moving_pairs += bool(np.max(np.abs(delta)) >= 1)
                    camera_pairs += 1
                    cumulative += error
                    drifts.append(float(np.linalg.norm(cumulative)))
                    row.update(reference_delta=delta.tolist(), step_error_px=errors[-1],
                               cumulative_error_px=drifts[-1])
                else:
                    cumulative = np.zeros(2)
                previous = {"at": timestamp, "shift": shift}
            else:
                previous, cumulative = None, np.zeros(2)
            rows.append(row)
            if index % 30 == 0:
                print(f"{session}: {index + 1}/{len(selected)} frames", flush=True)
        if digest(log) != log_hash:
            raise ValueError("Recording log changed during evaluation")
        write_json(output / (session + ".json"), {"log_sha256": log_hash, "frames": rows})
        result["sessions"].append({"recording": session, "eligible": len(selected),
                                   "available": sum("sha256" in r for r in rows),
                                   "accepted": sum(r["accepted"] for r in rows)})
    span = np.ptp(shifts, axis=0).tolist() if shifts else [0, 0]
    if eligible == 0:
        raise ValueError("No Southperry frames available")
    result["summary"] = {"eligible_frames": eligible, "available_frames": available,
                         "accepted_anchors": accepted, "anchor_coverage": accepted / eligible,
                         "scored_camera_pairs": camera_pairs, "moving_pairs": moving_pairs,
                         "camera_translation_span_px": span,
                         "step_error_p95_px": float(np.percentile(errors, 95)) if errors else None,
                         "step_error_max_px": max(errors, default=None),
                         "cumulative_drift_max_px": max(drifts, default=None)}
    result["runtime_seconds"] = round(time.perf_counter() - started, 3)
    write_json(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--recordings", type=Path, default=Path("data/recordings"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session", action="append")
    args = parser.parse_args()
    print(evaluate(args.assets, args.reference, args.recordings, args.output,
                   args.session)["summary"])
