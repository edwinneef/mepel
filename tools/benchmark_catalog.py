"""Measure cached sprite matching on composites and saved negative screenshots, without input."""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from maplebot.config import PerceptionConfig
from maplebot.geometry import Rect
from maplebot.perception import TemplateDetector, annotate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--negatives",
        nargs="*",
        type=Path,
        default=[],
        help="Explicitly labeled screenshots containing no enemies",
    )
    parser.add_argument("--background", type=Path, help="Optional background for composite frames")
    args = parser.parse_args()
    templates = Path("data/templates")
    root = Path("artifacts/catalog-benchmark")
    root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((templates / "catalog" / "manifest.json").read_text("utf-8"))
    detector = TemplateDetector(templates, PerceptionConfig())
    negative_frames = args.negatives
    background = args.background or (negative_frames[0] if negative_frames else None)
    base = (
        cv2.imread(str(background))
        if background
        else np.full((768, 1024, 3), (100, 65, 35), dtype=np.uint8)
    )
    if base is None:
        raise ValueError("Cannot read the composite background")
    rows, timings = [], []
    tp = fp = fn = 0
    for path in negative_frames:
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError(f"Cannot read negative screenshot: {path}")
        began = time.perf_counter()
        result = detector.detect(frame)
        timings.append(1000 * (time.perf_counter() - began))
        strong = [item for item in result.monsters if item.confidence >= 0.9]
        fp += len(strong)
        rows.append(
            {
                "frame": str(path),
                "type": "saved town negative",
                "detections": [asdict(item) for item in strong],
            }
        )
    entries = manifest["entries"]
    for mirrored in (False, True):
        for start in range(0, len(entries), 12):
            frame, expected = base.copy(), []
            for index, entry in enumerate(entries[start : start + 12]):
                sprite = cv2.imread(
                    str(templates / "catalog" / entry["file"]), cv2.IMREAD_UNCHANGED
                )
                if mirrored:
                    sprite = cv2.flip(sprite, 1)
                height, width = sprite.shape[:2]
                x, y = 231 + (index % 4) * 180, 65 + (index // 4) * 160
                alpha = sprite[:, :, 3:4].astype(np.float32) / 255
                patch = frame[y : y + height, x : x + width]
                patch[:] = np.round(sprite[:, :, :3] * alpha + patch * (1 - alpha)).astype(np.uint8)
                expected.append((entry["name"], Rect(x, y, width, height)))
            began = time.perf_counter()
            result = detector.detect(frame)
            timings.append(1000 * (time.perf_counter() - began))
            strong = [item for item in result.monsters if item.confidence >= 0.9]
            unmatched = list(strong)
            misses = []
            for name, box in expected:
                match = next(
                    (
                        item
                        for item in unmatched
                        if item.template.split(":")[1] == name and item.box.iou(box) >= 0.5
                    ),
                    None,
                )
                if match:
                    tp += 1
                    unmatched.remove(match)
                else:
                    fn += 1
                    misses.append({"name": name, "box": asdict(box)})
            fp += len(unmatched)
            filename = f"composite-{int(mirrored)}-{start:03d}.png"
            cv2.imwrite(
                str(root / filename),
                annotate(
                    frame,
                    result,
                    None,
                    "OFFLINE COMPOSITE",
                    "Downloaded reference sprites composited on a screenshot; not live gameplay",
                ),
            )
            rows.append(
                {
                    "frame": filename,
                    "type": "composited reference sprites",
                    "expected": len(expected),
                    "misses": misses,
                    "extra": [asdict(item) for item in unmatched],
                }
            )
    metrics = {
        "input_sent": False,
        "catalog": detector.catalog_info,
        "frames": len(rows),
        "composited_positive_instances": len(entries) * 2,
        "saved_town_negatives": len(negative_frames),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "mean_processing_ms": round(float(np.mean(timings)), 2),
        "p95_processing_ms": round(float(np.percentile(timings, 95)), 2),
        "processing_fps": round(1000 / float(np.mean(timings)), 2),
        "note": "Reference self-consistency and saved negatives; not native enemy accuracy.",
    }
    (root / "frames.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (root / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    if fp or fn:
        raise SystemExit("Catalog validation found misses or false positives; see frames.json")


if __name__ == "__main__":
    main()
