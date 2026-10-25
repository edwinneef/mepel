"""Replay existing screenshots and logged player detections against a probe layout."""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2

from maplebot.decision import PolicyInput
from maplebot.geometry import Rect
from maplebot.localization import (
    Alignment,
    AnchorMatcher,
    Platform,
    Rope,
    SpotGeometry,
    SurfaceTracker,
)


def probe(recording: Path, layout_path: Path, output: Path) -> dict:
    recording, output = recording.resolve(), output.resolve()
    if output == recording or recording in output.parents:
        raise ValueError("Write probe output outside the source recording")
    if any((output / name).exists() for name in ("locations.jsonl", "metrics.json")):
        raise ValueError("Probe output already exists; choose a new directory")
    layout = json.loads(layout_path.read_text("utf-8"))
    if layout.get("version") != 1:
        raise ValueError("Probe layout version must be 1")
    reference_path = recording / layout["reference"]
    if reference_path.parent != recording:
        raise ValueError("Reference must name a PNG inside the recording")
    reference = cv2.imread(str(reference_path))
    if reference is None:
        raise ValueError("Reference screenshot is missing or unreadable")
    geometry = SpotGeometry(
        reference.shape[1], reference.shape[0],
        tuple(Platform(**value) for value in layout["platforms"]),
        tuple(Rope(**value) for value in layout.get("ropes", [])),
    )
    matcher = AnchorMatcher(reference, tuple(Rect(**value) for value in layout["anchors"]))
    tracker = SurfaceTracker(geometry)
    counts: Counter = Counter()
    reasons: Counter = Counter()
    offsets = []
    rows = []
    previous_sequence = -1
    with (recording / "decisions.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            sequence = record["sequence"]
            if sequence <= previous_sequence:
                raise ValueError("Recording sequence must strictly increase")
            previous_sequence = sequence
            policy = PolicyInput.from_dict(record["policy_input"])
            path = recording / record["frame"]
            if path.parent != recording:
                raise ValueError("Frame must name a PNG inside the recording")
            image = cv2.imread(str(path)) if path.is_file() else None
            alignment = matcher.match(image) if image is not None else Alignment(
                None, 0, "Frame PNG missing or unreadable"
            )
            location = tracker.update(policy.observation.player, alignment, policy.now)
            counts[location.kind] += 1
            reasons[location.reason] += 1
            if alignment.offset is not None:
                offsets.append(alignment.offset)
            rows.append({
                "sequence": sequence, "frame": record["frame"], "now": policy.now,
                "alignment": asdict(alignment), "location": asdict(location),
                "input_sent": False,
            })
    if not rows:
        raise ValueError("Recording has no decisions")
    metrics = {
        "recording": str(recording), "layout": str(layout_path.resolve()),
        "frames": len(rows), "aligned_frames": len(offsets),
        "locations": dict(counts), "reasons": dict(reasons),
        "offset_range": {
            axis: [min(point[index] for point in offsets), max(point[index] for point in offsets)]
            for index, axis in enumerate(("x", "y"))
        } if offsets else None,
        "accuracy": None,
        "input_sent": False,
        "limitation": "Probe geometry and logged detections are not ground-truth labels. "
                      "Spatial matches do not verify grounded contact or rope attachment.",
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / "locations.jsonl").open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    with (output / "metrics.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.recording, args.layout, args.output), indent=2))


if __name__ == "__main__":
    main()
