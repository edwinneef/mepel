"""Read-only movement-proof provenance comparison; never grants movement authority.

Optional recorded provenance uses ``source_sha256`` (relative-path/hash mapping),
``controls_sha256`` and ``physics_sha256``. This tool does not add those fields to
legacy proofs. A hash match means matching declared bytes/settings, not native proof.
"""

import argparse
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path

from maplebot.config import Config
from maplebot.profiles import validate_profile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = tuple(f"src/maplebot/{name}.py" for name in (
    "navigation", "navigation_executor", "navigation_runtime", "moves", "move_proofs",
    "keyboard", "scheduler", "input_timing", "windows", "config",
))
HASH = re.compile(r"[a-f0-9]{64}")
AREA = re.compile(r"[a-f0-9]{32}")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_hash(value):
    # Same canonical JSON convention as navigation.map_hash.
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read_object(path):
    if path.stat().st_size > 1_000_000:
        raise ValueError("JSON evidence exceeds one megabyte")
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def current_context(root, config, physics=None):
    """Snapshot current files without importing controllers or changing settings."""
    root, config = Path(root).resolve(), Path(config).resolve()
    sources, errors = {}, []
    for name in SOURCE_FILES:
        try:
            sources[name] = digest(root / name)
        except OSError as error:
            errors.append(f"{name}: {error}")
    controls_hash = config_hash = physics_hash = None
    try:
        config_hash = digest(config)
        loaded = Config.load(config)
        controls_hash = object_hash({"input": asdict(loaded.input),
                                     "timing": asdict(loaded.timing)})
    except (OSError, ValueError, TypeError, AttributeError) as error:
        errors.append(f"Configuration unavailable/invalid: {error}")
    if physics is not None:
        try:
            physics_hash = digest(physics)
        except OSError as error:
            errors.append(f"Physics evidence unavailable: {error}")
    return {"source_sha256": sources, "controls_sha256": controls_hash,
            "config_path": str(config), "config_sha256": config_hash,
            "physics_path": str(Path(physics).resolve()) if physics is not None else None,
            "physics_sha256": physics_hash, "errors": errors}


def compare_hash(recorded, current):
    if (not isinstance(recorded, str) or HASH.fullmatch(recorded) is None
            or not isinstance(current, str) or HASH.fullmatch(current) is None):
        return "unknown"
    return "match" if recorded == current else "mismatch"


def comparison(provenance, current):
    provenance = provenance if isinstance(provenance, dict) else {}
    recorded = provenance.get("source_sha256")
    recorded = recorded if isinstance(recorded, dict) else {}
    sources = {name: compare_hash(recorded.get(name), current["source_sha256"].get(name))
               for name in SOURCE_FILES}
    controls = compare_hash(provenance.get("controls_sha256"), current["controls_sha256"])
    physics = compare_hash(provenance.get("physics_sha256"), current["physics_sha256"])
    states = [*sources.values(), controls, physics]
    status = ("mismatch" if "mismatch" in states else
              "unknown" if "unknown" in states else "match")
    return {"status": status, "sources": sources, "controls": controls, "physics": physics,
            "unknown": [name for name, state in sources.items() if state == "unknown"]
            + [name for name, state in (("controls", controls), ("physics", physics))
               if state == "unknown"]}


def audit(areas, current):
    areas = Path(areas).resolve()
    reports = []
    for path in sorted((areas / "proofs").glob("*.json")):
        row = {"path": str(path), "file_status": "valid", "moves": [],
               "map_status": "unknown", "current_map_hash": None}
        try:
            row["sha256"] = digest(path)
            value = read_object(path)
            area_id = value.get("area_id")
            if (not isinstance(area_id, str) or AREA.fullmatch(area_id) is None
                    or path.stem != area_id):
                raise ValueError("Invalid area ID or proof filename mismatch")
            if (not isinstance(value.get("map_hash"), str)
                    or HASH.fullmatch(value["map_hash"]) is None
                    or not isinstance(value.get("moves"), dict)):
                raise ValueError("Invalid proof map hash or move collection")
            row["area_id"], row["recorded_map_hash"] = area_id, value["map_hash"]
            area_path = areas / f"{area_id}.json"
            row["area_path"] = str(area_path)
            try:
                profile, _ = validate_profile(read_object(area_path))
                if profile["id"] != area_id:
                    raise ValueError("Area profile ID differs from proof")
                if any(view.get("minimap") is None for view in profile["views"]):
                    raise ValueError("Profile needs image-derived minimap normalization")
                row["area_sha256"] = digest(area_path)
                row["current_map_hash"] = object_hash(profile)
                row["map_status"] = compare_hash(value["map_hash"], row["current_map_hash"])
            except (OSError, ValueError, TypeError, KeyError) as error:
                row["map_reason"] = str(error)
            for move_id, record in sorted(value["moves"].items()):
                if (not isinstance(move_id, str) or not move_id or not isinstance(record, dict)
                        or type(record.get("proved_at")) not in (int, float)
                        or not math.isfinite(record["proved_at"]) or record["proved_at"] < 0):
                    row["moves"].append({"move_id": move_id, "status": "invalid",
                                         "reason": "Invalid move record/timestamp"})
                    continue
                row["moves"].append({"move_id": move_id, "proved_at": record["proved_at"],
                                     **comparison(record.get("provenance"), current)})
        except (OSError, ValueError, TypeError, KeyError) as error:
            row["file_status"], row["reason"] = "invalid", str(error)
        reports.append(row)
    return {"schema_version": 1, "scope": "Read-only declared provenance comparison",
            "input_sent": False, "proofs_modified": False, "native_acceptance": False,
            "current": current, "proof_files": reports,
            "summary": {"files": len(reports),
                        "invalid_files": sum(r["file_status"] == "invalid" for r in reports),
                        "moves": sum(len(r["moves"]) for r in reports),
                        "map_status": {state: sum(r["map_status"] == state for r in reports)
                                       for state in ("match", "mismatch", "unknown")},
                        **{state: sum(m["status"] == state for r in reports for m in r["moves"])
                           for state in ("match", "mismatch", "unknown", "invalid")}},
            "limitations": ["Matching hashes compare declarations, not gameplay or input delivery",
                            "Legacy missing provenance stays unknown; no proof is invalidated",
                            "Physics hash equality does not establish identified parameters",
                            "Current source/configuration does not establish the running engine",
                            "No recording or actual native controls are certified by this audit"]}


def write_report(path, report, *, root, areas, config, physics=None):
    path, root, areas = Path(path).resolve(), Path(root).resolve(), Path(areas).resolve()
    protected = [base / name for base in (root, ROOT)
                 for name in ("data", "src", "tools", "tests")]
    inputs = [Path(config).resolve(), *([Path(physics).resolve()] if physics is not None else [])]
    if (path.suffix != ".json" or any(path.is_relative_to(p) for p in [areas, *protected])
            or path in inputs):
        raise ValueError("Output must be a new JSON report outside saved data and source inputs")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--areas", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--physics", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    areas, config = args.areas or root / "data/areas", args.config or root / "config.toml"
    report = audit(areas, current_context(root, config, args.physics))
    write_report(args.output, report, root=root, areas=areas, config=config, physics=args.physics)
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
