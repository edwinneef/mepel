"""Time TemplateDetector on recorded frames and compare its outputs with a saved reference.

Offline only: frames come from saved clips and screenshots, no capture or input backend is
created. Each recorded clip replays in order with its recorded clock, so tracking, the search
window and sprite refresh behave as they did live. The map title is read before timing each
frame so the asynchronous OCR cannot make two runs differ.

    python tools/perception_benchmark.py --write artifacts/perception/golden.jsonl
    python tools/perception_benchmark.py --compare artifacts/perception/golden.jsonl
"""

import argparse
import hashlib
import json
import statistics
import time
import tomllib
from collections import defaultdict
from pathlib import Path

import cv2

from maplebot.config import PerceptionConfig
from maplebot.perception import CameraTracker, Observation, TemplateDetector

STAGES = ("_candidates", "_nametag_candidates", "_uncover", "_follow", "_refresh_sprite")
NO_MONSTER_MODES = {"navigation", "navigation_wait"}


def perception_config(path: Path) -> PerceptionConfig:
    values = tomllib.loads(path.read_text("utf-8")).get("perception", {})
    return PerceptionConfig(
        **{key: value for key, value in values.items()
           if key in PerceptionConfig.__dataclass_fields__})


def sources(data: Path, limit: int | None) -> list[tuple[str, list[tuple[Path, float, bool]]]]:
    """Recorded clips in time order (duplicate clips skipped), then saved screenshots."""
    found, seen = [], set()
    for clip in sorted((data / "recordings").glob("session-*")):
        log = clip / "decisions.jsonl"
        if not log.exists():
            continue
        frames = []
        for line in log.read_text("utf-8").splitlines():
            record = json.loads(line)
            path = clip / record["frame"]
            if path.exists():
                monsters = record.get("mode") not in NO_MONSTER_MODES
                frames.append((path, float(record["policy_input"]["now"]), monsters))
        key = hashlib.sha256(
            b"".join(path.read_bytes() for path, _, _ in frames[:3])).hexdigest()
        if frames and key not in seen:
            seen.add(key)
            found.append((clip.name, frames[:limit]))
    shots = sorted((data / "screenshots").glob("frame-*[0-9].png"))[:limit]
    if shots:
        # Unrelated screenshots: far enough apart in time that nothing is tracked across them.
        found.append(("screenshots", [(path, index * 10.0, True)
                                      for index, path in enumerate(shots)]))
    return found


def reset(detector: TemplateDetector) -> None:
    """Forget per-session state between clips without reloading the catalog."""
    detector.fresh.clear()
    detector.refreshed = float("-inf")
    detector.track = None
    detector.previous_monsters = ()
    detector.strip = None
    detector.camera = CameraTracker()
    detector.map_filter.previous = None
    detector.map_filter.taught = None


def settle_map(detector: TemplateDetector, image) -> None:
    """Finish the title OCR for this frame so the timed detect() sees a settled filter."""
    for _ in range(50):
        detector.map_filter.select(image, True)
        pending = detector.map_filter.pending
        if pending is None:
            return
        pending.result()


def summary(observation: Observation) -> dict:
    def item(detection):
        box = detection.box
        return {"box": [box.x, box.y, box.width, box.height], "confidence": detection.confidence,
                "template": detection.template, "tracked": detection.tracked}

    return {
        "player": item(observation.player) if observation.player else None,
        "monsters": [item(monster) for monster in observation.monsters],
        "failures": observation.failures,
        "camera": [round(float(value), 3) for value in observation.camera_shift],
    }


def differences(expected: dict, actual: dict, tolerance: float) -> list[str]:
    found = []
    for key in ("failures", "camera"):
        if expected[key] != actual[key]:
            found.append(f"{key}: {expected[key]} != {actual[key]}")
    pairs = [("player", expected["player"], actual["player"])] + [
        (f"monster[{index}]", a, b)
        for index, (a, b) in enumerate(zip(expected["monsters"], actual["monsters"], strict=False))]
    if len(expected["monsters"]) != len(actual["monsters"]):
        found.append(f"monster count {len(expected['monsters'])} != {len(actual['monsters'])}")
    for name, a, b in pairs:
        if (a is None) != (b is None):
            found.append(f"{name}: {a} != {b}")
        elif a is not None and (
                a["box"] != b["box"] or a["template"] != b["template"]
                or a["tracked"] != b["tracked"]
                or abs(a["confidence"] - b["confidence"]) > tolerance):
            found.append(f"{name}: {a} != {b}")
    return found


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * fraction))], 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--limit", type=int, help="At most this many frames per source")
    parser.add_argument("--write", type=Path, help="Save outputs as the reference (JSONL)")
    parser.add_argument("--compare", type=Path, help="Compare outputs with a saved reference")
    parser.add_argument("--tolerance", type=float, default=1e-4)
    parser.add_argument("--stages", action="store_true", help="Also time detector stages")
    parser.add_argument("--report", type=Path, help="Write the timing summary as JSON")
    args = parser.parse_args()

    began = time.perf_counter()
    detector = TemplateDetector(args.data / "templates", perception_config(args.config))
    load_seconds = time.perf_counter() - began
    stage_ms: dict[str, float] = defaultdict(float)
    if args.stages:
        for name in STAGES:
            original = getattr(detector, name)

            def timed(*items, _original=original, _name=name, **options):
                start = time.perf_counter()
                try:
                    return _original(*items, **options)
                finally:
                    stage_ms[_name] += (time.perf_counter() - start) * 1000

            setattr(detector, name, timed)

    expected = []
    if args.compare:
        expected = [json.loads(line) for line in args.compare.read_text("utf-8").splitlines()]
    outputs, mismatches, per_source = [], [], {}
    all_ms: list[float] = []
    for name, frames in sources(args.data, args.limit):
        reset(detector)
        timings = []
        for path, now, monsters in frames:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            detector.taught_map = True
            settle_map(detector, image)
            start = time.perf_counter()
            observation = detector.detect(image, now, monsters=monsters)
            timings.append((time.perf_counter() - start) * 1000)
            record = {"frame": f"{name}/{path.name}", **summary(observation)}
            if expected:
                index = len(outputs)
                reference = expected[index] if index < len(expected) else None
                if reference is None or reference["frame"] != record["frame"]:
                    mismatches.append({"frame": record["frame"], "differences": ["frame order"]})
                else:
                    found = differences(reference, record, args.tolerance)
                    if found:
                        mismatches.append({"frame": record["frame"], "differences": found})
            outputs.append(record)
        all_ms += timings
        per_source[name] = {"frames": len(timings), "p50_ms": percentile(timings, 0.5),
                            "p90_ms": percentile(timings, 0.9)}
    report = {
        "frames": len(all_ms),
        "load_seconds": round(load_seconds, 2),
        "mean_ms": round(statistics.fmean(all_ms), 1),
        "p50_ms": percentile(all_ms, 0.5),
        "p90_ms": percentile(all_ms, 0.9),
        "stages_ms_per_frame": {key: round(value / len(all_ms), 1)
                                for key, value in stage_ms.items()},
        "sources": per_source,
    }
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text("".join(json.dumps(item) + "\n" for item in outputs), "utf-8")
    if args.compare:
        report["compared"] = len(expected)
        report["mismatched_frames"] = len(mismatches)
        report["first_mismatches"] = mismatches[:10]
        if len(expected) != len(outputs):
            report["frame_count"] = f"reference {len(expected)} != replay {len(outputs)}"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2))
    detector.map_filter.close()
    if args.compare and (mismatches or len(expected) != len(outputs)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
