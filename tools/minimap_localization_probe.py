"""Offline minimap localization on a saved recording of a taught area. No input.

`label` proposes feet labels (name tag plus reference registration) and a review
montage; a person marks each reviewed label. `evaluate` fits the minimap transform
on two time folds, scores reviewed labels held out from their fold's fit, and
replays the fused MinimapTracker.
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from maplebot.decision import PolicyInput
from maplebot.localization import (
    MinimapTracker,
    MinimapTransform,
    Platform,
    ViewTransform,
    register_view,
)
from maplebot.minimap_reader import AreaMinimap
from maplebot.profiles import AreaStore

BLOCK = 20  # consecutive sequences per fold block


def _area(areas: Path, area_id: str) -> tuple[dict, np.ndarray, ViewTransform]:
    store = AreaStore(areas)
    profile = store.load(area_id)["profile"]
    view = profile["views"][0]
    reference = cv2.imdecode(np.frombuffer(store.frame(view["image"]), np.uint8),
                             cv2.IMREAD_COLOR)
    return profile, reference, ViewTransform(view["origin"]["x"], view["origin"]["y"],
                                             view["scale"])


def _frames(recording: Path):
    previous = -1
    with (recording / "decisions.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record["sequence"] <= previous:
                raise ValueError("Recording sequence must strictly increase")
            previous = record["sequence"]
            path = recording / record["frame"]
            if path.parent != recording:
                raise ValueError("Frame must name a PNG inside the recording")
            image = cv2.imread(str(path)) if path.is_file() else None
            if image is not None:
                yield record, PolicyInput.from_dict(record["policy_input"]), image


def _fresh(player) -> bool:
    return player is not None and not player.tracked and player.confidence >= 0.90


def _new_output(output: Path, recording: Path, names: tuple[str, ...]) -> Path:
    output = output.resolve()
    if output == recording or recording in output.parents:
        raise ValueError("Write probe output outside the source recording")
    if any((output / name).exists() for name in names):
        raise ValueError("Probe output already exists; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    return output


def label(recording: Path, areas: Path, area_id: str, count: int, output: Path) -> dict:
    recording = recording.resolve()
    output = _new_output(output, recording, ("labels.json", "review.png"))
    _, reference, view = _area(areas, area_id)
    reader = AreaMinimap(reference)
    candidates = []
    for record, policy, image in _frames(recording):
        player = policy.observation.player
        offset = register_view(reference, image)
        if not _fresh(player) or offset is None or reader.read(image).dot is None:
            continue
        x, y = player.box.center[0], float(player.box.feet)
        candidates.append((record, image, (x, y), view.to_area(x + offset[0], y + offset[1])))
    if len(candidates) < count:
        raise ValueError(f"Only {len(candidates)} frames have a name tag, marker and registration")
    labels, tiles = [], []
    for index in np.linspace(0, len(candidates) - 1, count).astype(int):
        record, image, (x, y), feet = candidates[index]
        labels.append({"frame": record["frame"], "sequence": record["sequence"],
                       "feet": {"x": feet[0], "y": feet[1]}, "reviewed": False})
        padded = cv2.copyMakeBorder(image, 120, 120, 120, 120, cv2.BORDER_CONSTANT)
        tile = padded[int(y) + 30:int(y) + 150, int(x) + 60:int(x) + 180]
        tile = cv2.resize(tile, (240, 240), interpolation=cv2.INTER_NEAREST)
        cv2.line(tile, (0, 180), (239, 180), (0, 0, 255), 1)
        cv2.line(tile, (120, 0), (120, 239), (0, 0, 255), 1)
        cv2.putText(tile, str(record["sequence"]), (2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 1)
        tiles.append(tile)
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 8)
    cv2.imwrite(str(output / "review.png"),
                np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)]))
    result = {"version": 1, "recording": str(recording), "area": area_id,
              "instructions": "Set reviewed=true where the crosshair is on the player's feet; "
                              "delete wrong labels.", "labels": labels}
    with (output / "labels.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2))
    return {"labels": len(labels), "candidates": len(candidates), "output": str(output)}


def _percentiles(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95)),
            "max": float(max(values))}


def evaluate(recording: Path, areas: Path, area_id: str, labels_path: Path,
             output: Path) -> dict:
    recording = recording.resolve()
    output = _new_output(output, recording, ("locations.jsonl", "metrics.json"))
    profile, reference, view = _area(areas, area_id)
    labels = json.loads(labels_path.read_text("utf-8"))
    if labels.get("version") != 1 or labels.get("area") != area_id:
        raise ValueError("Labels must be version 1 for this area")
    truth = {item["sequence"]: (item["feet"]["x"], item["feet"]["y"])
             for item in labels["labels"] if item.get("reviewed") is True}
    reader = AreaMinimap(reference)
    frames = []
    for record, policy, image in _frames(recording):
        fix = reader.read(image)
        player = policy.observation.player
        offset = register_view(reference, image) if fix.dot and _fresh(player) else None
        pair = None
        if offset is not None:
            x, y = player.box.center[0] + offset[0], player.box.feet + offset[1]
            pair = (fix.dot, view.to_area(x, y))
        frames.append((record, policy, fix, pair))
    errors: dict[str, list[float]] = {"x": [], "y": []}
    folds = []
    for fold in (0, 1):
        train = [pair for record, _, _, pair in frames
                 if pair and record["sequence"] // BLOCK % 2 != fold
                 and record["sequence"] not in truth]
        transform = MinimapTransform.fit([d for d, _ in train], [f for _, f in train])
        folds.append({"fold": fold, "pairs": len(train), "transform": asdict(transform)})
        for record, _, fix, _ in frames:
            sequence = record["sequence"]
            if sequence in truth and sequence // BLOCK % 2 == fold and fix.dot:
                x, y = transform.to_area(*fix.dot)
                errors["x"].append(abs(x - truth[sequence][0]))
                errors["y"].append(abs(y - truth[sequence][1]))
    pairs = [pair for record, _, _, pair in frames
             if pair and record["sequence"] not in truth]
    transform = MinimapTransform.fit([d for d, _ in pairs], [f for _, f in pairs])
    platforms = tuple(
        Platform(item["id"], int(min(item["start"]["x"], item["end"]["x"])),
                 int(max(item["start"]["x"], item["end"]["x"])),
                 int(round((item["start"]["y"] + item["end"]["y"]) / 2)))
        for item in profile["platforms"]
    )
    tracker = MinimapTracker(transform, platforms)
    kinds: Counter = Counter()
    reasons: Counter = Counter()
    without_marker = 0
    rows = []
    for record, policy, fix, _ in frames:
        shift = policy.observation.camera_shift
        if policy.observation.camera_confidence < 0.35:
            shift = None
        location = tracker.update(fix, policy.observation.player, shift, policy.now)
        kinds[location.kind] += 1
        reasons[location.reason] += 1
        if fix.dot is None and location.kind != "unknown":
            without_marker += 1
        rows.append({"sequence": record["sequence"], "frame": record["frame"],
                     "now": policy.now, "fix": fix.reason, "location": asdict(location),
                     "input_sent": False})
    metrics = {
        "recording": str(recording), "area": area_id, "frames": len(frames),
        "labels": {"reviewed": len(truth), "scored": len(errors["x"])},
        "held_out_error_px": {axis: _percentiles(values) for axis, values in errors.items()},
        "folds": folds, "transform": asdict(transform),
        "marker_frames": sum(1 for _, _, fix, _ in frames if fix.dot),
        "locations": dict(kinds), "reasons": dict(reasons),
        "located_without_marker": without_marker, "input_sent": False,
        "limitation": "Labels come from reviewed name-tag feet and reference registration. "
                      "Platform matches are spatial; contact and movement are not verified.",
    }
    with (output / "locations.jsonl").open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    with (output / "metrics.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("label", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("recording", type=Path)
        command.add_argument("--area", required=True)
        command.add_argument("--areas", type=Path, default=Path("data/areas"))
        command.add_argument("--output", type=Path, required=True)
        if name == "label":
            command.add_argument("--count", type=int, default=48)
        else:
            command.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "label":
        result = label(args.recording, args.areas, args.area, args.count, args.output)
    else:
        result = evaluate(args.recording, args.areas, args.area, args.labels, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
