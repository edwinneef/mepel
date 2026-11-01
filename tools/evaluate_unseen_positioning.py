"""Evaluate frozen shared structures on held-out saved maps; no engine or input access."""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

from maplebot.first_visit import FirstVisitLocator
from maplebot.profiles import AreaStore
from tools.unseen_positioning_benchmark import assess, digest, load_contract, source_for


def cases(map_row, limit):
    candidates, seen = [], set()
    for clip in map_row["clips"]:
        directory = Path(clip["path"])
        path = directory / "decisions.jsonl"
        if digest(path) != clip["decisions_sha256"]:
            raise ValueError("Recording changed since benchmark inventory")
        for line in path.read_text("utf-8").splitlines():
            row = json.loads(line)
            frame = directory / row["frame"]
            if frame.parent != directory:
                raise ValueError("Frame escaped recording")
            key = ((row.get("input_timing") or {}).get("history_id"), row["capture_clock"])
            if frame.is_file() and key not in seen:
                seen.add(key)
                candidates.append((frame, row))
    selected = []
    if candidates:
        indices = sorted({round(i * (len(candidates) - 1) / max(1, limit - 1))
                          for i in range(min(limit, len(candidates)))})
        selected.extend(candidates[i] for i in indices)
    for view in map_row["views"]:
        path = Path(view["path"])
        if digest(path) != view["sha256"]:
            raise ValueError("Reference changed since inventory")
        if path not in {p for p, _ in selected}:
            selected.append((path, None))
    return selected


def apply_labels(results, labels):
    """Attach independent answers after prediction; the locator never receives them."""
    by_frame = {(r["map_id"], r["sha256"]): r for r in labels}
    if len(by_frame) != len(labels):
        raise ValueError("Duplicate evaluation labels")
    protected = {"truth_xy", "independent_truth", "source_verified", "label_uncertainty_px",
                 "observable"}
    output = []
    for result in results:
        label = by_frame.get((result["map_id"], result["sha256"]), {})
        if label and label.get("method") != "independent_world_landmarks_and_feet":
            raise ValueError("Labels must establish independent world landmarks and feet")
        output.append({**result, **{k: label[k] for k in protected if k in label}})
    return output


def evaluate(manifest_path, contract_path, areas, limit=8, labels_path=None):
    root = Path(__file__).resolve().parents[1]
    implementation_files = [root / "src" / "maplebot" / name for name in (
        "structure_detection.py", "geometry_anchors.py", "first_visit.py")]
    implementation_files += [Path(__file__).resolve(),
                             root / "tools" / "unseen_positioning_benchmark.py"]
    implementation = {str(path.relative_to(root)): digest(path) for path in implementation_files}
    contract = load_contract(contract_path)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if digest(contract_path) != manifest["contract_sha256"]:
        raise ValueError("Benchmark contract changed after inventory")
    store = AreaStore(areas)
    results = []
    for item in manifest["maps"]:
        if item["split"] != "evaluation":
            continue
        profile = store.load(Path(item["profile"]).stem)["profile"]
        public = profile["public_map"]
        if public["sha256"] != item["source_sha256"]:
            raise ValueError("Map source changed since inventory")
        source = source_for(store, public)
        model = FirstVisitLocator(source)
        for path, telemetry in cases(item, limit):
            player = telemetry.get("player") if telemetry else None
            began = time.perf_counter()
            row = {"map_id": item["map_id"], "frame": str(path), "sha256": digest(path),
                   "truth_xy": None, "independent_truth": False, "source_verified": False,
                   "predicted_xy": None, "reason": "Independent XY truth/source check missing"}
            image = cv2.imread(str(path))
            if image is None:
                row["reason"] = "Frame missing or corrupt"
                results.append(row)
                continue
            try:
                motion = {}
                if telemetry:
                    motion = {"now": telemetry["capture_clock"],
                              "camera": telemetry.get("camera_shift")
                              if telemetry.get("camera_confidence", 0) >= .60 else None,
                              "identity": str(path.parent)}
                result = model.locate(image, player, **motion)
                row.update(observation=result, structures=result["structures"],
                           predicted_xy=result.get("xy"))
                row["reason"] = result["reason"]
            except (ValueError, cv2.error) as error:
                row["reason"] = str(error)
            row["analysis_ms"] = round((time.perf_counter() - began) * 1000, 3)
            results.append(row)
    if labels_path is not None:
        labels = json.loads(labels_path.read_text("utf-8"))
        if labels["contract_sha256"] != manifest["contract_sha256"]:
            raise ValueError("Labels belong to another frozen benchmark")
        results = apply_labels(results, labels["frames"])
    if implementation != {str(path.relative_to(root)): digest(path)
                          for path in implementation_files}:
        raise ValueError("Implementation changed during evaluation; report refused")
    return {"schema_version": 1, "input_sent": False, "native_acceptance": False,
            "contract_sha256": digest(contract_path), "manifest_sha256": digest(manifest_path),
            "implementation_sha256": implementation,
            "samples_per_map": limit, "results": results, "assessment": assess(contract, results),
            "labels_sha256": digest(labels_path) if labels_path else None,
            "ignored_runtime_evidence": ["saved walk calibration", "logged world feet",
                                         "per-map image banks", "independent evaluation labels"],
            "limitations": ["Candidate shapes are not collision/contact/true-feet truth",
                            "Reference-only maps lack frame-matched player detections",
                            "Missing independent XY labels/source verification block acceptance"]}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "synthetic":
        from tools.evaluate_alignment_corpus import main as synthetic_main

        synthetic_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path,
                        default=Path("tests/fixtures/unseen-positioning-benchmark.json"))
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--diagnostic", action="store_true",
                        help="Previously inspected maps cannot certify a revised model")
    args = parser.parse_args()
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    if args.output.resolve().is_relative_to(protected):
        parser.error("Report must stay outside saved data")
    report = evaluate(args.manifest, args.contract, args.areas, labels_path=args.labels)
    report["acceptance_eligible"] = not args.diagnostic
    if args.diagnostic:
        report["assessment"]["passed"] = False
        report["assessment"]["reasons"].append("Diagnostic reuse; fresh reserved maps required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({"frames": len(report["results"]), "assessment": report["assessment"]}))


if __name__ == "__main__":
    main()
