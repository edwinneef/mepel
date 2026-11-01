"""Score the current camera tracker against frozen, pixel-matched Southperry references."""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from maplebot.perception import CameraTracker
from tools.export_classic_assets import check_output, digest, load_json, safe_path, write_json


def replay(references, recordings, output):
    started = time.perf_counter()
    references, recordings = safe_path(references), safe_path(recordings)
    output = check_output(output, recordings, [])
    if output.is_relative_to(references):
        raise ValueError("Output must stay outside frozen references")
    original = load_json(references / "summary.json")
    output.mkdir()
    errors, drifts, rows_scored, moving = [], [], 0, 0
    sessions = []
    for item in original["sessions"]:
        session = item["recording"]
        root = safe_path(recordings / session)
        if root.parent != recordings:
            raise ValueError("Recording escaped source root")
        labels = load_json(references / (session + ".json"), 16 * 1024 * 1024)
        if digest(root / "decisions.jsonl") != labels["log_sha256"]:
            raise ValueError("Recording log changed")
        tracker, previous, accumulated = CameraTracker(), None, np.zeros(2)
        results = []
        for label in labels["frames"]:
            path = safe_path(root / label["frame"])
            if path.parent != root:
                raise ValueError("Frame escaped recording")
            if "sha256" not in label:
                tracker, previous, accumulated = CameraTracker(), None, np.zeros(2)
                continue
            if digest(path) != label["sha256"]:
                raise ValueError("Recording pixels changed")
            frame = cv2.imread(str(path))
            predicted, confidence = tracker.update(frame)
            row = {"frame": label["frame"], "prediction": list(predicted), "confidence": confidence}
            at = label["captured_at"]
            if label["accepted"]:
                # Answers are used only after the pixel-only tracker made its prediction.
                shift = np.array(label["scenery_translation"])
                if previous is not None and 0 < at - previous["at"] <= .5 and confidence >= .60:
                    expected = shift - previous["shift"]
                    error = np.array(predicted) - expected
                    accumulated += error
                    errors.append(float(np.linalg.norm(error)))
                    drifts.append(float(np.linalg.norm(accumulated)))
                    rows_scored += 1
                    moving += bool(np.max(np.abs(expected)) >= 1)
                    row.update(reference_delta=expected.tolist(), step_error_px=errors[-1],
                               accumulated_error_px=drifts[-1])
                else:
                    accumulated = np.zeros(2)
                previous = {"at": at, "shift": shift}
            else:
                previous, accumulated = None, np.zeros(2)
            results.append(row)
        write_json(output / (session + ".json"), {"frames": results})
        sessions.append({"recording": session, "available": len(results)})
    result = {"source_summary_sha256": digest(references / "summary.json"),
              "runtime_camera_sha256": digest(Path("src/maplebot/perception.py")),
              "sessions": sessions, "scored_camera_pairs": rows_scored, "moving_pairs": moving,
              "step_error_p95_px": float(np.percentile(errors, 95)) if errors else None,
              "step_error_max_px": max(errors, default=None),
              "cumulative_drift_max_px": max(drifts, default=None),
              "runtime_seconds": round(time.perf_counter() - started, 3),
              "native_acceptance": False, "input_sent": False}
    write_json(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--recordings", type=Path, default=Path("data/recordings"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(replay(args.references, args.recordings, args.output))
