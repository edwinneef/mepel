"""Compare a saved pre-change reader with the current reader on saved PNGs only."""

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from maplebot.minimap_reader import AreaMinimap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--recordings", type=Path, default=Path("data/recordings"))
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--controls-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output file")
    spec = importlib.util.spec_from_file_location("maplebot._minimap_before", args.before)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    readers = {}
    references = {}
    source_hashes = {}

    def read_image(path: Path) -> np.ndarray:
        content = path.read_bytes()
        source_hashes[str(path)] = hashlib.sha256(content).hexdigest()
        frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Invalid image: {path}")
        return frame

    for path in sorted(args.areas.glob("*.json")):
        profile = json.loads(path.read_text("utf-8"))
        reference = read_image(args.areas / "frames" / f"{profile['views'][0]['image']}.png")
        readers[profile["name"]] = (module.AreaMinimap(reference), AreaMinimap(reference))
        references[profile["name"]] = reference
    records = []
    regressions = []
    directories = [] if args.controls_only else sorted(args.recordings.iterdir())
    directories.append(args.areas / "teaching")
    for directory in directories:
        if not directory.is_dir():
            continue
        paths = sorted(directory.glob("*.png"))
        if not paths:
            continue
        counts = {name: Counter() for name in readers}
        for path in paths:
            frame = read_image(path)
            for name, (before, after) in readers.items():
                old, new = before.read(frame), after.read(frame)
                counts[name][f"before:{old.reason}"] += 1
                counts[name][f"after:{new.reason}"] += 1
                if old.dot is not None and old.dot != new.dot:
                    regressions.append({"file": str(path), "map": name,
                                        "before": old.dot, "after": new.dot})
        records.append({"recording": directory.name, "pngs": len(paths),
                        "maps": {name: dict(count) for name, count in counts.items()}})
        print(directory.name, len(paths), flush=True)
    controls = []
    for reference_name, reference in references.items():
        for map_name, (_, after) in readers.items():
            fix = after.read(reference)
            controls.append({"reference": reference_name, "reader": map_name,
                             "expected_match": reference_name == map_name,
                             "matched": fix.dot is not None, "agreement": fix.agreement})
    failed_controls = [row for row in controls if row["matched"] != row["expected_match"]]
    # Hash verification covers every PNG read, including overlapping incident clips.
    changed = [path for path, digest in source_hashes.items()
               if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError(f"Source images changed: {changed}")
    result = {"recordings": records, "regressions": regressions,
              "reference_controls": controls,
              "source_sha256": source_hashes, "input_sent": False,
              "limits": "Overlapping clips are not independent accuracy samples. "
                        "Unsupported capture sizes remain rejected."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"recordings": len(records), "pngs": sum(r["pngs"] for r in records),
                      "lost_or_changed_detections": len(regressions), "input_sent": False}))
    if regressions or failed_controls:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
