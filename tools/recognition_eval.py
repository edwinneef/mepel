"""Measure player recognition on saved clips against reviewed ground-truth labels.

Offline only: frames come from data/recordings and replay through TemplateDetector with
their recorded clock, as tools/perception_benchmark.py does. No capture or input backend is
created.

Labels (data/recognition-labels.json) hold reviewed segments: pose, facing and occlusion for
sequence ranges of one engine run. Boxes come from recorded frames whose name tag confirmed
the player; a segment with "box": "recorded" accepts the recorded box after visual review.

The report gives, per clip and per pose x facing: identity recall, wrong identities, position
error, the longest gap without a fresh confirmed identity, and a simulated recognition
recovery that follows navigation_runtime (2 fresh agreeing frames within 2 s, else stop).

    python -m tools.recognition_eval --report artifacts/recognition-eval/baseline.json
"""

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2

from maplebot.navigation_runtime import RECOGNITION_RECOVERY_SECONDS
from maplebot.perception import TemplateDetector
from tools.perception_benchmark import perception_config, reset, settle_map

POSES = ("stand", "walk", "air", "climb", "hit")
FACINGS = ("left", "right", "back")
OCCLUSIONS = ("none", "tag", "player")
# Detected centre x and feet within this many pixels of the label count as the same place.
POSITION_TOLERANCE = 16
RESUME_MATCHES = 2
RESUME_SPACING = 0.15
# A pose/facing pair is verified with at least this many uncovered labeled frames, nearly all
# recognized by name tag in every clip that replays them.
COVERAGE_FRAMES = 5
COVERAGE_RECALL = 0.9
# Pairs the taught routes can need (see maplebot.navigation.required_poses).
ROUTE_POSES = ("walk/left", "walk/right", "air/left", "air/right", "air/back", "climb/back")


@dataclass(frozen=True)
class Label:
    box: tuple[int, int, int, int] | None
    pose: str
    facing: str
    occlusion: str


def key(record: dict) -> str:
    return f"{float(record['captured_at']):.3f}"


def clips(data: Path) -> dict[str, list[dict]]:
    found = {}
    for log in sorted((data / "recordings").glob("session-*/decisions.jsonl")):
        records = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
        records = [r for r in records if (log.parent / r["frame"]).exists()]
        if records:
            found[log.parent.name] = records
    return found


def runs(found: dict[str, list[dict]]) -> dict[str, int]:
    """Engine run per clip: clips that share any frame belong to the same run."""
    owner: dict[str, int] = {}
    parent: list[int] = []

    def root(item: int) -> int:
        while parent[item] != item:
            item = parent[item]
        return item

    for index, records in enumerate(found.values()):
        parent.append(index)
        for record in records:
            other = owner.setdefault(key(record), index)
            parent[root(index)] = root(other)
    return {name: root(index) for index, name in enumerate(found)}


def build_labels(found: dict[str, list[dict]], spec: dict, confidence: float
                 ) -> tuple[dict[str, Label], list[str]]:
    """Labels per frame key, and the frame keys no reviewed segment covers."""
    run_of = runs(found)
    identity = f"nametag:{spec['identity']}"
    for segment in spec["segments"]:
        if (segment["pose"] not in POSES or segment["facing"] not in FACINGS
                or segment["occlusion"] not in OCCLUSIONS or segment["clip"] not in run_of):
            raise ValueError(f"Invalid label segment: {segment}")
    labels, missing = {}, []
    for name, records in found.items():
        for record in records:
            frame = key(record)
            if frame in labels:
                continue
            sequence = record["sequence"]
            matches = [s for s in spec["segments"]
                       if run_of[s["clip"]] == run_of[name]
                       and s["sequences"][0] <= sequence <= s["sequences"][1]]
            if not matches:
                missing.append(f"{name}/{record['frame']}")
                continue
            segment = matches[-1]  # Later, narrower segments refine a broad range.
            player = record.get("player") or {}
            confirmed = (player.get("template", "").removesuffix(":tag-only") == identity
                         and not player.get("tracked")
                         and player.get("confidence", 0) >= confidence)
            box = None
            if player and (confirmed or segment.get("box") == "recorded"):
                b = player["box"]
                box = (b["x"], b["y"], b["width"], b["height"])
            labels[frame] = Label(box, segment["pose"], segment["facing"],
                                  segment["occlusion"])
    return labels, missing


def place(box) -> tuple[float, float]:
    x, y, width, height = box
    return x + width / 2, y + height


def score_frame(label: Label, detection: dict | None, identity: str, confidence: float
                ) -> dict:
    """Classify one detector output against its label."""
    identified = bool(detection and not detection["tracked"]
                      and detection["confidence"] >= confidence)
    found = detection["template"].removesuffix(":tag-only") if identified else None
    error = None
    if detection and label.box:
        (ax, af), (bx, bf) = place(detection["box"]), place(label.box)
        error = round(max(abs(ax - bx), abs(af - bf)), 1)
    near = error is not None and error <= POSITION_TOLERANCE
    wrong = bool(found and found.startswith("nametag:")
                 and (found != identity or (label.box and not near)))
    return {
        "identified": identified,
        "identity": found,
        # Fresh name-tag identity of the right player in the right place.
        "correct": bool(found == identity and near),
        "wrong_identity": wrong,
        "sprite_only": bool(found and not found.startswith("nametag:")),
        "tracked": bool(detection and detection["tracked"]),
        "error": error,
    }


def simulate_recovery(frames: list[dict], ended: float | None = None) -> dict:
    """Navigation's bounded recovery replayed on detector outputs (minimap and focus gates
    are not simulated). frames: [{"now", "frame", "identified", "identity", "occlusion"}].
    ended is when the clip's recorded stop happened on the same clock, if after the frames."""
    identity, recovery, events = None, None, []
    for frame in frames:
        now = frame["now"]
        if recovery:
            if now - recovery["started"] >= RECOGNITION_RECOVERY_SECONDS:
                return finish(events, recovery, "timeout", now)
            if frame["identity"] != identity:
                if frame["identity"] and frame["identity"].startswith("nametag:"):
                    return finish(events, recovery, "different_identity", now)
                recovery["matches"], recovery["first"] = 0, None
                recovery["frames"].append(frame)
                continue
            recovery["matches"] += 1
            recovery["first"] = now if recovery["first"] is None else recovery["first"]
            recovery["frames"].append(frame)
            if (recovery["matches"] >= RESUME_MATCHES
                    and now - recovery["first"] >= RESUME_SPACING):
                events.append({"result": "resumed", "frame": recovery["frame"],
                               "seconds": round(now - recovery["started"], 3)})
                recovery = None
            continue
        if not frame["identified"]:
            if identity is None:
                continue  # Nothing confirmed yet; live arming would not start.
            recovery = {"started": now, "matches": 0, "first": None, "frames": [frame],
                        "frame": frame["frame"]}
            continue
        if (identity and identity.startswith("nametag:")
                and frame["identity"].startswith("nametag:") and frame["identity"] != identity):
            events.append({"result": "stopped", "reason": "identity_changed", "at": now})
            return {"events": events, "stopped": True}
        if not identity or frame["identity"].startswith("nametag:"):
            identity = frame["identity"]
    if recovery and ended is not None and ended - recovery["started"] >= (
            RECOGNITION_RECOVERY_SECONDS):
        return finish(events, recovery, "timeout", ended)
    if recovery:
        events.append({"result": "unfinished", "frame": recovery["frame"],
                       "seconds": round(frames[-1]["now"] - recovery["started"], 3)})
    return {"events": events, "stopped": False}


def finish(events: list[dict], recovery: dict, reason: str, now: float) -> dict:
    lost = [f for f in recovery["frames"] if not f["identified"]]
    events.append({"result": "stopped", "reason": reason, "frame": recovery["frame"],
                   "seconds": round(now - recovery["started"], 3),
                   # A stop is justified when every unrecognized frame was really covered.
                   "justified": bool(lost) and all(f["occlusion"] != "none" for f in lost)})
    return {"events": events, "stopped": True}


def gap_lengths(frames: list[dict]) -> dict:
    """Longest run of frames without a correct fresh identity."""
    best, run, start = {"frames": 0, "seconds": 0.0}, 0, None
    for frame in frames:
        if frame["correct"]:
            run, start = 0, None
            continue
        run += 1
        start = frame["now"] if start is None else start
        if run > best["frames"]:
            best = {"frames": run, "seconds": round(frame["now"] - start, 3)}
    return best


def aggregate(frames: list[dict]) -> dict:
    visible = [f for f in frames if f["occlusion"] == "none"]
    errors = [f["error"] for f in frames if f["error"] is not None]
    fresh = [f["error"] for f in frames if f["error"] is not None and f["identified"]]
    return {
        "frames": len(frames),
        "visible_frames": len(visible),
        "identity_recall": (round(sum(f["correct"] for f in visible) / len(visible), 3)
                            if visible else None),
        "occluded_identified": sum(f["correct"] for f in frames if f["occlusion"] != "none"),
        "wrong_identity": sum(f["wrong_identity"] for f in frames),
        "sprite_only": sum(f["sprite_only"] for f in frames),
        "tracked": sum(f["tracked"] for f in frames),
        "missing": sum(f["detected"] is False for f in frames),
        "error_median": round(statistics.median(errors), 1) if errors else None,
        "error_max": max(errors) if errors else None,
        "fresh_error_max": max(fresh) if fresh else None,
        "longest_gap": gap_lengths(frames),
    }


def recorded_stop(clip: Path, records: list[dict]) -> dict | None:
    """The stop that ended the clip, on the frames' clock, when it came after the last frame."""
    events = clip / "events.jsonl"
    lines = events.read_text("utf-8").splitlines() if events.exists() else []
    if not lines:
        return None
    event, last = json.loads(lines[-1]), records[-1]
    delay = float(event["time"]) - float(last["captured_at"])
    if delay < 0:
        return None
    return {"now": float(last["policy_input"]["now"]) + delay, "reason": event["reason"]}


def evaluate(detector: TemplateDetector, found: dict[str, list[dict]], data: Path,
             labels: dict[str, Label], identity: str, confidence: float) -> dict:
    per_clip, every, outputs = {}, [], []
    for name, records in found.items():
        reset(detector)
        frames = []
        for record in records:
            label = labels.get(key(record))
            image = cv2.imread(str(data / "recordings" / name / record["frame"]),
                               cv2.IMREAD_COLOR)
            detector.taught_map = True
            settle_map(detector, image)
            now = float(record["policy_input"]["now"])
            player = detector.detect(image, now, monsters=False).player
            detection = player and {
                "box": (player.box.x, player.box.y, player.box.width, player.box.height),
                "confidence": player.confidence, "template": player.template,
                "tracked": player.tracked}
            outputs.append([name, record["frame"], detection])
            if label is None:
                continue
            frames.append({"now": now, "frame": record["frame"], "key": key(record),
                           "template": detection and detection["template"],
                           "pose": label.pose,
                           "facing": label.facing, "occlusion": label.occlusion,
                           "detected": detection is not None,
                           **score_frame(label, detection, identity, confidence)})
        stop = recorded_stop(data / "recordings" / name, records)
        recovery = simulate_recovery(frames, stop and stop["now"])
        per_clip[name] = {**aggregate(frames), "recorded_stop": stop and stop["reason"],
                          "recovery": recovery,
                          "wrong_frames": [f["frame"] for f in frames if f["wrong_identity"]]}
        every += frames
    by_pose = defaultdict(list)
    for frame in every:
        by_pose[f"{frame['pose']}/{frame['facing']}"].append(frame)
    digest = hashlib.sha256(json.dumps(outputs, sort_keys=True).encode()).hexdigest()
    return {"total": aggregate(every), "clips": per_clip,
            "poses": {name: aggregate(items) for name, items in sorted(by_pose.items())},
            "coverage": coverage(every), "output_digest": digest}


def coverage(frames: list[dict]) -> dict:
    """Verified pose/facing pairs over unique frames, and the poses each sprite matched."""
    unique: dict[str, dict] = {}
    for frame in frames:
        if frame["occlusion"] != "none":
            continue
        seen = unique.setdefault(frame["key"], {**frame})
        seen["correct"] = seen["correct"] and frame["correct"]  # Every replay must agree.
    poses: dict[str, dict] = {}
    for frame in unique.values():
        item = poses.setdefault(f"{frame['pose']}/{frame['facing']}", {"frames": 0, "correct": 0})
        item["frames"] += 1
        item["correct"] += frame["correct"]
    for item in poses.values():
        item["recall"] = round(item["correct"] / item["frames"], 3)
        item["verified"] = (item["frames"] >= COVERAGE_FRAMES
                            and item["recall"] >= COVERAGE_RECALL)
    templates: dict[str, set[str]] = defaultdict(set)
    for frame in frames:
        if frame["sprite_only"] and frame["error"] is not None and (
                frame["error"] <= POSITION_TOLERANCE):
            templates[frame["template"]].add(f"{frame['pose']}/{frame['facing']}")
    verified = sorted(name for name, item in poses.items() if item["verified"])
    return {"thresholds": {"frames": COVERAGE_FRAMES, "recall": COVERAGE_RECALL},
            "poses": dict(sorted(poses.items())), "verified": verified,
            "gaps": [pose for pose in ROUTE_POSES if pose not in verified],
            "templates": {name: sorted(items) for name, items in sorted(templates.items())}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--labels", type=Path, default=Path("data/recognition-labels.json"))
    parser.add_argument("--report", type=Path, help="Write the report as JSON")
    parser.add_argument("--clip", action="append", help="Only these clips (repeatable)")
    parser.add_argument("--coverage", type=Path,
                        help="Save verified poses for route readiness, normally "
                             "data/recognition-coverage.json")
    args = parser.parse_args()

    config = perception_config(args.config)
    spec = json.loads(args.labels.read_text("utf-8"))
    found = clips(args.data)
    labels, missing = build_labels(found, spec, config.confidence)
    if args.clip:
        found = {name: records for name, records in found.items() if name in args.clip}
    detector = TemplateDetector(args.data / "templates", config)
    try:
        report = evaluate(detector, found, args.data, labels,
                          f"nametag:{spec['identity']}", config.confidence)
    finally:
        detector.map_filter.close()
    report = {"labels": str(args.labels), "labeled_frames": len(labels),
              "unlabeled_frames": missing, "position_tolerance": POSITION_TOLERANCE,
              "recovery_seconds": RECOGNITION_RECOVERY_SECONDS, **report}
    if args.coverage:
        if args.clip or missing:
            raise SystemExit("Coverage needs every clip and every frame labeled")
        args.coverage.write_text(json.dumps(
            {"identity": spec["identity"], "labels": str(args.labels),
             "output_digest": report["output_digest"], **report["coverage"]}, indent=2),
            "utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps({k: report[k] for k in ("labeled_frames", "total", "output_digest")}
                     | {"verified": report["coverage"]["verified"],
                        "gaps": report["coverage"]["gaps"]}
                     | {"unlabeled": len(missing),
                        "stops": {n: c["recovery"]["events"] for n, c in report["clips"].items()
                                  if c["recovery"]["stopped"]}}, indent=2))


if __name__ == "__main__":
    main()
