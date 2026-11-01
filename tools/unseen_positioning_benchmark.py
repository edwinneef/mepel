"""Frozen whole-map positioning benchmark. Saved files only; no capture or input."""

import argparse
import hashlib
import json
from pathlib import Path

from maplebot.meowdb import cached_source
from maplebot.profiles import AreaStore
from maplebot.public_map import cached


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract(path):
    contract = json.loads(path.read_text("utf-8"))
    development, evaluation = contract["development_maps"], contract["evaluation_maps"]
    if (not development or len(set(evaluation)) < 2 or set(development) & set(evaluation)
            or len(development) != len(set(development))
            or len(evaluation) != len(set(evaluation))):
        raise ValueError("Benchmark needs disjoint whole maps and at least two evaluation maps")
    if (contract["criteria"]["minimum_observable_scene_coverage"] <= 0
            or contract["criteria"]["maximum_false_ready"] != 0):
        raise ValueError("Refusing everything or confidently wrong output cannot pass")
    return contract


def source_for(store, public):
    def missing(_):
        raise ValueError("Source is not cached; network access is disabled")

    source, actual = (cached_source(store.directory, public)
                      if public.get("provider") == "meowdb-classic"
                      else cached(store.directory, public["id"], missing))
    if actual != public["sha256"]:
        raise ValueError("Source digest differs from saved map")
    return source


def inventory(areas, recordings, contract_path):
    contract = load_contract(contract_path)
    store = AreaStore(areas)
    maps, area_ids = {}, {}
    listing = store.list()
    for item in listing["areas"]:
        profile = store.load(item["id"])["profile"]
        public = profile.get("public_map")
        if not public:
            continue
        key = public["id"]
        split = ("development" if key in contract["development_maps"] else
                 "evaluation" if key in contract["evaluation_maps"] else "excluded")
        area_ids[item["id"]] = key
        row = {"map_id": key, "name": profile["name"], "split": split,
               "source_sha256": public["sha256"], "provider": public.get("provider", "dreamms"),
               "source_compatibility": "collision_geometry_unverified",
               "profile": str(areas / f"{item['id']}.json"), "views": [], "clips": []}
        try:
            source = source_for(store, public)
            row["geometry"] = {"footholds": len(source["footholds"]),
                               "ropes": len(source["ladderRopes"])}
        except (ValueError, OSError) as error:
            row["source_error"] = str(error)
        for view in profile["views"]:
            frame = areas / "frames" / f"{view['image']}.png"
            row["views"].append({"path": str(frame), "sha256": digest(frame)})
        maps[key] = row
    excluded = []
    for path in sorted(recordings.glob("*/decisions.jsonl")):
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        keys = {area_ids.get((r.get("position") or {}).get("area_id")) for r in rows}
        if len(keys) != 1 or None in keys:
            excluded.append({"path": str(path), "reason": "unmapped or mixed-map recording"})
            continue
        key = next(iter(keys))
        available = [r for r in rows if (path.parent / r["frame"]).is_file()]
        maps[key]["clips"].append({"path": str(path.parent), "decisions_sha256": digest(path),
                                   "rows": len(rows), "png_frames": len(available)})
    return {"schema_version": 1, "input_sent": False, "native_acceptance": False,
            "contract_sha256": digest(contract_path), "contract": contract,
            "maps": list(maps.values()), "excluded_recordings": excluded,
            "load_errors": listing["errors"], "ready_for_accuracy_acceptance": False,
            "missing": ["Independent held-out XY/feet labels and collision-source verification"],
            "scope": "Frozen inventory; no detector fitting or image-specific runtime resources"}


def assess(contract, results):
    """Fail closed on missing truth, empty predictions, or an absent held-out map."""
    import numpy as np

    def xy(value):
        return (isinstance(value, (list, tuple)) and len(value) == 2
                and all(type(v) in (int, float) and np.isfinite(v) for v in value))

    criteria = contract["criteria"]
    summary, reasons = [], []
    for key in contract["evaluation_maps"]:
        rows = [r for r in results if r["map_id"] == key]
        labelled = [r for r in rows if xy(r.get("truth_xy"))
                    and r.get("independent_truth") is True
                    and r.get("source_verified") is True
                    and 0 <= r.get("label_uncertainty_px", float("inf"))
                    <= criteria["maximum_label_uncertainty_px"]]
        observable = [r for r in labelled if r.get("observable") is True]
        accepted = [r for r in observable if xy(r.get("predicted_xy"))]
        errors = [max(abs(a - b) for a, b in zip(r["predicted_xy"], r["truth_xy"], strict=True))
                  + r["label_uncertainty_px"] for r in accepted]
        false_ready = sum(r.get("predicted_xy") is not None and r.get("observable") is False
                          for r in labelled)
        coverage = len(accepted) / len(observable) if observable else 0
        p95 = float(np.percentile(errors, 95)) if errors else None
        passed = bool(observable and coverage >= criteria["minimum_observable_scene_coverage"]
                      and p95 is not None and p95 <= criteria["p95_error_px"] and not false_ready)
        if not passed:
            reasons.append(f"Map {key}: missing independent XY truth or failed accuracy/coverage")
        summary.append({"map_id": key, "labelled": len(labelled), "coverage": coverage,
                        "p95_with_label_uncertainty_px": p95, "false_ready": false_ready,
                        "passed": passed})
    return {"passed": bool(summary) and all(s["passed"] for s in summary),
            "maps": summary, "reasons": reasons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--recordings", type=Path, default=Path("data/recordings"))
    parser.add_argument("--contract", type=Path,
                        default=Path("tests/fixtures/unseen-positioning-benchmark.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    if (target.is_relative_to(protected) or target.is_relative_to(args.areas.resolve())
            or target.is_relative_to(args.recordings.resolve())):
        parser.error("Reports must stay outside saved data")
    report = inventory(args.areas, args.recordings, args.contract)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({"maps": len(report["maps"]), "report": str(target),
                      "ready_for_accuracy_acceptance": False}))


if __name__ == "__main__":
    main()
