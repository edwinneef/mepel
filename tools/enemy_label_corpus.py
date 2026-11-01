"""Prepare independent annotations from a saved clip; never infer ground truth."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(clip):
    clip = Path(clip).resolve()
    decisions = clip / "decisions.jsonl"
    frames = []
    seen = set()
    for line in decisions.read_text("utf-8").splitlines():
        row = json.loads(line)
        name = row["frame"]
        if (not isinstance(name, str) or Path(name).name != name
                or not name.endswith(".png") or "/" in name or "\\" in name):
            raise ValueError("Frame must be a local PNG filename")
        if name in seen:
            raise ValueError(f"Duplicate frame: {name}")
        seen.add(name)
        path = clip / name
        if not path.resolve().is_relative_to(clip):
            raise ValueError("Frame must remain inside clip")
        available = path.is_file()
        candidates = []
        for index, monster in enumerate(row.get("monsters", [])):
            score = monster.get("confidence")
            if type(score) not in (int, float) or not .80 <= score < .85:
                continue
            candidates.append({
                "detection_index": index, "raw_score": score,
                "box": monster["box"], "template": monster.get("template"),
                "recorded_track_id": monster.get("track_id"),
                "recorded_predicted": monster.get("tracked", False),
                "annotation": {"identity": None, "species": None, "floor": None,
                               "live_sprite": None, "ambiguous": None,
                               "world_x": None, "world_y": None,
                               "expected_eligible": None, "note": ""},
            })
        # Include empty and missing frames: omitting them could fabricate continuity.
        frames.append({"frame": name, "captured_at": row.get("captured_at"),
                       "capture_clock": row.get("capture_clock"),
                       "available": available,
                       "sha256": digest(path) if available else None,
                       "camera_shift": row.get("camera_shift"),
                       "camera_confidence": row.get("camera_confidence"),
                       "candidates": candidates})
    return {"version": 1, "clip": str(clip), "decisions_sha256": digest(decisions),
            "purpose": "Independent annotations; detector output is not a label",
            "annotator": None, "label_method": None, "frames": frames,
            "summary": {"frames": len(frames),
                        "missing_images": sum(not f["available"] for f in frames),
                        "candidates": sum(len(f["candidates"]) for f in frames)},
            "acceptance": "unlabelled; no gameplay admission or validation claim"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    corpus = prepare(args.clip)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite annotations from a previous pass.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(corpus, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(corpus["summary"]))


if __name__ == "__main__":
    main()
