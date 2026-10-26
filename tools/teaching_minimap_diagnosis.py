"""Replay saved teaching failures without capture, input or changes to saved data."""

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from maplebot.minimap_reader import MIN_AGREEMENT, AreaMinimap, _dots, _markers


def diagnose(areas: Path, area_id: str) -> dict:
    sources = {}

    def read(path: Path) -> bytes:
        content = path.read_bytes()
        sources[str(path)] = hashlib.sha256(content).hexdigest()
        return content

    def image(path: Path) -> np.ndarray:
        result = cv2.imdecode(np.frombuffer(read(path), np.uint8), cv2.IMREAD_COLOR)
        if result is None:
            raise ValueError(f"Unreadable saved image: {path}")
        return result

    profile = json.loads(read(areas / f"{area_id}.json"))
    reference = image(areas / "frames" / f"{profile['views'][0]['image']}.png")
    reader = AreaMinimap(reference)
    hsv = cv2.cvtColor(reader.template, cv2.COLOR_BGR2HSV)
    failures = []
    for path in sorted((areas / "teaching").glob(f"{area_id}-miss-*.png")):
        frame = image(path)
        fix = reader.read(frame)
        home = reader.home
        crop = frame[home.y:home.feet, home.x:home.x + home.width]
        keep = reader.static & ~_markers(crop)
        mismatched = keep & (cv2.absdiff(crop, reader.template).max(axis=2) >= 24)
        trials = {}
        for minimum in (80, 100, 120, 140):
            candidate = keep & (hsv[..., 2] >= minimum)
            trials[str(minimum)] = {
                "reference_pixels": int((reader.static & (hsv[..., 2] >= minimum)).sum()),
                "agreement": float((candidate & ~mismatched).sum() / candidate.sum()),
            }
        failures.append({
            "file": str(path), "actual": asdict(fix),
            "fixed_crop_agreement": reader._agreement(frame, home),
            "fixed_crop_dots": _dots(crop), "mismatched_pixels": int(mismatched.sum()),
            "mismatched_reference_value_below_80": int((mismatched & (hsv[..., 2] < 80)).sum()),
            "experimental_minimum_reference_value": trials,
        })

    logs = []
    for path in sorted((areas / "teaching").glob(f"{area_id}-*.jsonl")):
        rows = [json.loads(line) for line in read(path).splitlines()]
        checks = [row for row in rows if "reason" in row]
        misses = [row for row in checks if row.get("dot") is None]
        longest, current = 0, 0
        for row in checks:
            current = current + 1 if row.get("dot") is None else 0
            longest = max(longest, current)
        logs.append({"file": str(path), "checks": len(checks), "misses": len(misses),
                     "misses_with_name_tag": sum(row.get("tag") is not None for row in misses),
                     "longest_missing_run": longest,
                     "reasons": dict(Counter(row["reason"] for row in checks))})

    # Negative controls for this mask experiment, not a validation of a production fix.
    negatives = {"blank": np.zeros_like(reference),
                 "covered_minimap": reference.copy()}
    negatives["covered_minimap"][:300, :400] = 90
    for path in sorted(areas.glob("*.json")):
        if path.stem == area_id:
            continue
        other = json.loads(read(path))
        negatives[other["name"]] = image(areas / "frames" / f"{other['views'][0]['image']}.png")
    negative_results = {}
    for minimum in (0, 80):
        trial = AreaMinimap(reference)
        trial.static &= hsv[..., 2] >= minimum
        trial.weights = trial.static.astype(np.uint8)
        negative_results[str(minimum)] = {
            name: asdict(trial.read(frame)) for name, frame in negatives.items()
        }
    changed = [path for path, digest in sources.items()
               if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError(f"Source changed during diagnosis: {changed}")
    return {"area": profile["name"], "threshold": MIN_AGREEMENT,
            "reference_canvas": asdict(reader.home),
            "reference_static_pixels": int(reader.static.sum()),
            "logs": logs, "saved_failures": failures, "negative_controls": negative_results,
            "source_sha256": sources, "input_sent": False,
            "limits": "Five retained miss images cannot establish the cause of every logged miss. "
                      "Mask trials are diagnostic; no production reader or saved map was changed."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--area-id", default="98a20c69939d450fb46e5e9342b83734")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expect-readable", action="store_true",
                        help="Exit nonzero while any retained miss frame is rejected")
    args = parser.parse_args()
    result = diagnose(args.areas, args.area_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
    failed = sum(row["actual"]["dot"] is None for row in result["saved_failures"])
    print(json.dumps({"saved_images": len(result["saved_failures"]), "rejected": failed,
                      "logs": result["logs"], "input_sent": False}, indent=2))
    if args.expect_readable and (not result["saved_failures"] or failed):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
