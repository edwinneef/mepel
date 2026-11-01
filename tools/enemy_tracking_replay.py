"""Input-free PNG replay of enemy identity, occlusion and camera compensation."""

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2

from maplebot.config import Config
from maplebot.perception import TemplateDetector, annotate


def replay(directory, templates, output, config, geometry=None, limit=0):
    if output.resolve() == directory.resolve() or directory.resolve().is_relative_to(
            output.resolve()):
        raise ValueError("Replay output must not contain source recordings")
    output.mkdir(parents=True, exist_ok=False)
    frames = sorted(directory.glob("*.png"))
    frames = [p for p in frames if ".annotated." not in p.name]
    if limit:
        frames = frames[:limit]
    if not frames:
        raise ValueError("No recorded PNG frames")
    timestamps = {}
    log = directory / "decisions.jsonl"
    if log.exists():
        for line in log.read_text("utf-8").splitlines():
            row = json.loads(line)
            if "frame" in row and "captured_at" in row:
                timestamps[row["frame"]] = float(row["captured_at"])
    first = timestamps.get(frames[0].name, 0)
    startup = time.perf_counter()
    detector = TemplateDetector(templates, config.perception)
    if geometry:
        detector.enemy_geometry = json.loads(geometry.read_text("utf-8"))
    # Replay runs faster than real time; let screenshot-title OCR initialize before
    # consuming the sequence. No species/title comes from the old detector's log.
    initial = cv2.imread(str(frames[0]))
    detector.map_filter.select(initial)
    if detector.map_filter.pending is not None:
        detector.map_filter.pending.result(timeout=30)
        detector.map_filter.select(initial)
    startup_seconds = time.perf_counter() - startup
    states, ids = Counter(), set()
    ambiguous = reappearances = 0
    previous = {}
    started = time.perf_counter()
    try:
        with (output / "tracks.jsonl").open("w", encoding="utf-8") as handle:
            for index, path in enumerate(frames):
                image = cv2.imread(str(path))
                if image is None:
                    raise ValueError(f"Unreadable recording: {path}")
                now = timestamps.get(path.name, first + index / config.capture.fps) - first
                observation = detector.detect(image, now)
                for track in observation.enemy_tracks:
                    states[track.state] += 1
                    ids.add(track.track_id)
                    reappearances += (previous.get(track.track_id) in {"occluded", "lost"}
                                      and track.state == "visible")
                    previous[track.track_id] = track.state
                ambiguous += sum(item.track_id is None
                                 and item.confidence >= config.perception.confidence
                                 for item in observation.monsters)
                handle.write(json.dumps({"frame": path.name, "time": now,
                                         **asdict(observation), "input_sent": False,
                                         "catalog": {k: detector.catalog_info.get(k) for k in (
                                             "active_map", "active_variants", "catalog_paused",
                                             "map_filter_error")}}) + "\n")
                if index % 30 == 0 or index == len(frames) - 1:
                    cv2.imwrite(str(output / f"{path.stem}.annotated.png"),
                                annotate(image, observation, None, "REPLAY", "Input-free replay"))
    finally:
        detector.pool.shutdown(wait=True)
        detector.map_filter.close()
    report = {"source": str(directory.resolve()), "frames": len(frames),
              "states": dict(states), "unique_ids": len(ids), "reappearances": reappearances,
              "unassigned_detections": ambiguous, "input_sent": False,
              "processing_seconds": round(time.perf_counter() - started, 3),
              "startup_seconds": round(startup_seconds, 3),
              "notes": "Unlabeled recordings: counts are diagnostics, "
                       "not identity accuracy or hit proof."}
    (output / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--templates", type=Path, default=Path("data/templates"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--geometry", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(replay(args.directory, args.templates, args.output, Config.load(args.config),
                            args.geometry, args.limit), indent=2))
