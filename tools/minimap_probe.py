"""Validate minimap motion against recorded name tracking, without sending input."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median

import cv2
import numpy as np

from maplebot.minimap import MinimapDetector, terrain_motion

CALIBRATION = "session-1792887641233734800-clip"
BASELINE = "session-1792888007516281700-clip"
TOLERANCE = 24.0


def load_recording(folder: Path, detector: MinimapDetector) -> list[dict]:
    rows = []
    with (folder / "decisions.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            source = json.loads(line)
            frame = folder / source["frame"]
            if frame.parent != folder:
                raise ValueError("Frame must be inside its source recording")
            image = cv2.imread(str(frame)) if frame.is_file() else None
            reading = detector.read(image) if image is not None else None
            player = source.get("player")
            named = bool(
                player and not player.get("tracked") and player["confidence"] >= 0.9
                and player.get("template", "").startswith("nametag:")
            )
            box = player["box"] if named else None
            policy_time = source.get("policy_input", {}).get("now")
            rows.append({
                "frame": source["frame"], "sequence": source["sequence"],
                "time": policy_time if policy_time is not None else source["captured_at"],
                "capture_id": source["captured_at"],
                "reading": reading, "named": named,
                "feet": np.array([box["x"] + box["width"] / 2, box["y"] + box["height"]])
                if box else None,
                "camera": np.array(source.get("camera_shift", (0, 0))),
                "camera_confidence": source.get("camera_confidence", 0),
            })
    return rows


def motion_pair(previous: dict, current: dict) -> tuple[dict | None, str]:
    if not 0 < current["time"] - previous["time"] <= 1:
        return None, "Nonconsecutive capture time"
    if current["sequence"] != previous["sequence"] + 1:
        return None, "Nonconsecutive frame sequence"
    if not previous["named"] or not current["named"]:
        return None, "Fresh name tracking unavailable"
    before, after = previous["reading"], current["reading"]
    if before is None or after is None:
        return None, "Frame PNG missing"
    if before.dot is None or after.dot is None:
        return None, "Unique minimap marker unavailable"
    if not np.isfinite(current["camera_confidence"]) or current["camera_confidence"] < 0.35:
        return None, "Screen camera motion unavailable"
    scroll, quality = terrain_motion(before.canvas, after.canvas)
    if quality < 0.5:
        return None, "Minimap terrain registration unavailable"
    mini = np.array(after.dot) - before.dot - scroll
    name = current["feet"] - previous["feet"] - current["camera"]
    if not np.isfinite([*mini, *name]).all():
        return None, "Invalid motion measurement"
    return {"minimap": mini, "name": name, "terrain_shift": scroll,
            "terrain_quality": quality}, "Measured"


def fit_scale(rows: list[dict]) -> dict:
    estimates, chunk = [], []
    for previous, current in zip(rows, rows[1:], strict=False):
        pair, _ = motion_pair(previous, current)
        if pair is None:
            chunk = []
            continue
        chunk.append(pair)
        if len(chunk) == 6:
            mini = sum(item["minimap"] for item in chunk)
            name = sum(item["name"] for item in chunk)
            estimates.extend(
                float(world / dot) for dot, world in zip(mini, name, strict=True)
                if abs(dot) >= 3 and dot * world > 0
            )
            chunk = []
    if len(estimates) < 3:
        raise ValueError("Calibration needs at least three nonoverlapping moving six-frame blocks")
    scale = median(estimates)
    if not 8 <= scale <= 32:
        raise ValueError("Calibration scale is outside the probe's supported range")
    return {"recording": CALIBRATION, "pixels_per_minimap_pixel": scale,
            "six_frame_estimates": estimates, "isotropic_scale_assumption": True}


def validate(rows: list[dict], scale: float) -> tuple[dict, list[dict]]:
    reasons, measured, output = Counter(), [], []
    for index, current in enumerate(rows):
        reading = current["reading"]
        reason = "First frame has no previous observation"
        pair = None
        if index:
            pair, reason = motion_pair(rows[index - 1], current)
        residual = np.abs(pair["name"] - pair["minimap"] * scale) if pair else None
        aligned = bool(residual is not None and max(residual) <= TOLERANCE)
        if pair:
            measured.append(residual.tolist())
            reason = "Motion agrees" if aligned else "Motion disagrees"
        reasons[reason] += 1
        output.append({
            "frame": current["frame"], "sequence": current["sequence"],
            "dot": reading.dot if reading else None,
            "fresh_name": current["named"], "aligned": aligned, "reason": reason,
            "residual_pixels": residual.tolist() if residual is not None else None,
            "minimap_motion": pair["minimap"].tolist() if pair else None,
            "name_world_motion": pair["name"].tolist() if pair else None,
            "minimap_terrain_shift": pair["terrain_shift"] if pair else None,
            "input_sent": False,
        })
    metrics = {
        "frames": len(rows), "png_frames": sum(row["reading"] is not None for row in rows),
        "unique_dot_frames": sum(bool(row["reading"] and row["reading"].dot) for row in rows),
        "fresh_name_frames": sum(row["named"] for row in rows),
        "marker_reasons": dict(Counter(
            row["reading"].reason if row["reading"] else "Frame PNG missing" for row in rows
        )),
        "checkable_frames": len(measured),
        "aligned_frames": reasons["Motion agrees"], "reasons": dict(reasons),
        "residual_p95_pixels": np.percentile(measured, 95, axis=0).tolist() if measured else None,
        "accuracy": None, "input_sent": False,
    }
    return metrics, output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.recordings.resolve(), args.output.resolve()
    if output == root or root in output.parents or output.exists():
        raise ValueError("Choose a new output directory outside the source recordings")
    reference = cv2.imread(str(args.reference))
    if reference is None:
        raise ValueError("Reference screenshot is missing")
    detector = MinimapDetector(reference)
    folders = [p for p in sorted(root.iterdir()) if (p / "decisions.jsonl").is_file()]
    data = {p.name: load_recording(p, detector) for p in folders}
    calibration = fit_scale(data[CALIBRATION])
    scale = calibration["pixels_per_minimap_pixel"]
    training_ids = {row["capture_id"] for row in data[CALIBRATION]}
    output.mkdir(parents=True)
    summary = {"calibration": calibration, "tolerance_pixels_per_axis": TOLERANCE,
               "baseline": {"recording": BASELINE, "anchor_aligned_frames": 13, "frames": 120},
               "recordings": [], "input_sent": False}
    all_ids = []
    for folder in folders:
        rows = data[folder.name]
        if not rows:
            continue
        metrics, locations = validate(rows, scale)
        metrics.update(recording=folder.name, calibration_recording=folder.name == CALIBRATION,
                       calibration_overlap_frames=sum(
                           row["capture_id"] in training_ids for row in rows
                       ))
        summary["recordings"].append(metrics)
        all_ids.extend(row["capture_id"] for row in rows)
        with (output / (folder.name + ".jsonl")).open("x", encoding="utf-8") as handle:
            for location in locations:
                handle.write(json.dumps(location) + "\n")
        print(f"{folder.name}: {metrics['aligned_frames']}/{len(rows)} aligned; "
              f"{metrics['unique_dot_frames']} unique dots", flush=True)
    summary["unique_capture_ids"] = len(set(all_ids))
    summary["reference_sha256"] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
    with (output / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


if __name__ == "__main__":
    main()
