"""Independent-label screenshot evaluation; never captures or constructs an input backend.

Manifest paths are workspace-relative. Config, template inventory, source files and raw
frames must match their frozen SHA-256 values. Semantic results exclude measured timing.
Sparse samples do not establish a recovery delay or runtime resume behavior.
"""

import argparse
import hashlib
import json
import math
import re
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
VISIBILITY = {"visible", "partial", "hidden", "unknown"}


def workspace_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Paths must be workspace-relative")
    target = (root / value).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Path escapes workspace")
    return target


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_hash(path: Path, expected: str) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"Invalid SHA-256: {path.name}")
    if not path.is_file() or digest(path) != expected:
        raise ValueError(f"Hash mismatch or missing file: {path}")


def finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate(manifest: dict, root: Path) -> set[Path]:
    """Validate all inputs before creating a detector or writing any output."""
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("Manifest version must be 1")
    protected = set()
    config = workspace_path(root, manifest["config_path"])
    check_hash(config, manifest["config_sha256"])
    protected.add(config)
    templates = workspace_path(root, manifest["templates_path"])
    expected = manifest["templates_sha256"]
    if not templates.is_dir() or not isinstance(expected, dict):
        raise ValueError("Templates need an exact frozen inventory")
    actual = {p.relative_to(templates).as_posix() for p in templates.rglob("*") if p.is_file()}
    if actual != set(expected):
        raise ValueError("Template inventory changed")
    for relative, sha in expected.items():
        path = workspace_path(templates, relative)
        check_hash(path, sha)
        protected.add(path)
    source = manifest.get("source_sha256")
    if not isinstance(source, dict) or not source:
        raise ValueError("Frozen source_sha256 is required")
    for relative, sha in source.items():
        path = workspace_path(root, relative)
        check_hash(path, sha)
        protected.add(path)
    aliases = manifest.get("identities")
    if not isinstance(aliases, dict):
        raise ValueError("Explicit identity aliases are required")
    tokens = []
    for name, values in aliases.items():
        if (not isinstance(name, str) or not name or not isinstance(values, list) or not values
                or any(not isinstance(v, str) or not v.startswith("nametag:")
                       or v.endswith(":tag-only") for v in values)):
            raise ValueError("Identity aliases must be explicit nametag tokens")
        tokens.extend(values)
    if len(tokens) != len(set(tokens)):
        raise ValueError("Identity aliases must be unique")
    sequences = manifest.get("sequences")
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("At least one sequence is required")
    seen_ids, frame_splits = set(), {}
    for sequence in sequences:
        sequence_id = sequence.get("id")
        if not isinstance(sequence_id, str) or not sequence_id or sequence_id in seen_ids:
            raise ValueError("Sequence IDs must be unique nonempty strings")
        seen_ids.add(sequence_id)
        if sequence.get("split") not in {"development", "held_out"}:
            raise ValueError("Invalid split")
        if sequence.get("kind", "real") not in {"real", "synthetic"}:
            raise ValueError("Sequence kind must be real or synthetic")
        if type(sequence.get("complete_contiguous", False)) is not bool:
            raise ValueError("complete_contiguous must be boolean")
        frames = sequence.get("frames")
        if not isinstance(frames, list) or not frames:
            raise ValueError("Each sequence needs frames")
        previous = float("-inf")
        for frame in frames:
            path = workspace_path(root, frame["path"])
            check_hash(path, frame["sha256"])
            protected.add(path)
            old_split = frame_splits.setdefault(frame["sha256"], sequence["split"])
            if old_split != sequence["split"]:
                raise ValueError("Identical frame leaks across splits")
            if not finite(frame.get("at")) or frame["at"] <= previous:
                raise ValueError("Frame timestamps must strictly increase and be finite")
            previous = frame["at"]
            if frame.get("visibility") not in VISIBILITY:
                raise ValueError("Invalid visibility")
            provenance = ("independent-visual" if sequence.get("kind", "real") == "real"
                          else "synthetic-transform")
            if frame.get("provenance") != provenance:
                raise ValueError("Independent real labels cannot use interpolated truth")
            identity = frame.get("identity")
            if identity is not None and identity not in aliases:
                raise ValueError("Label identity has no explicit alias")
            box = frame.get("box")
            if frame["visibility"] in {"hidden", "unknown"} and box is not None:
                raise ValueError("Hidden/unknown positions must not have exact boxes")
            if box is not None and (not isinstance(box, list) or len(box) != 4
                                    or not all(finite(v) for v in box)
                                    or box[2] <= 0 or box[3] <= 0):
                raise ValueError("Invalid label box")
            if not finite(frame.get("tolerance_px")) or frame["tolerance_px"] < 0:
                raise ValueError("tolerance_px must be finite and nonnegative")
    for key in ("monsters", "taught_map"):
        if key in manifest and type(manifest[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    return protected


def score(frame: dict, player: dict | None, threshold: float, identities: dict) -> dict:
    visible = frame["visibility"] in {"visible", "partial"}
    identity_evaluable = visible and frame.get("identity") is not None
    position_evaluable = visible and frame.get("box") is not None
    fresh = bool(player and not player["tracked"] and finite(player["confidence"])
                 and player["confidence"] >= threshold)
    token = None
    if player:
        token = player.get("identity")
        if token is None and player["template"].startswith("nametag:"):
            token = player["template"].removesuffix(":tag-only")
    observed_identity = next((name for name, aliases in identities.items()
                              if token in aliases), None)
    error = None
    if position_evaluable and player:
        x, y, w, h = player["box"]
        tx, ty, tw, th = frame["box"]
        error = math.hypot(x + w / 2 - tx - tw / 2, y + h - ty - th)
    identity_match = (observed_identity == frame["identity"] if identity_evaluable
                      and observed_identity is not None else None)
    within = error <= frame["tolerance_px"] if error is not None else None
    if not fresh:
        outcome = "abstained"
    elif not visible or (not identity_evaluable and not position_evaluable):
        outcome = "unsupported_fresh"
    elif identity_match is False or within is False:
        outcome = "wrong_fresh"
    elif identity_match is True:
        outcome = "correct_fresh_identity"
    else:
        outcome = "unsupported_fresh_identity"
    return {"visibility": frame["visibility"], "identity_evaluable": identity_evaluable,
            "position_evaluable": position_evaluable, "fresh": fresh,
            "observed_identity": observed_identity, "identity_match": identity_match,
            "position_error_px": error, "within_tolerance": within, "outcome": outcome}


def aggregate(rows: list[dict]) -> dict:
    evaluations = [r["evaluation"] for r in rows]
    counts = {key: sum(e["outcome"] == key for e in evaluations) for key in
              ("abstained", "correct_fresh_identity", "wrong_fresh", "unsupported_fresh",
               "unsupported_fresh_identity")}
    return {"frames": len(rows), "visible_labelled": sum(e["visibility"] in
            {"visible", "partial"} for e in evaluations),
            "identity_evaluable": sum(e["identity_evaluable"] for e in evaluations),
            "position_evaluable": sum(e["position_evaluable"] for e in evaluations),
            "position_unscorable": sum(not e["position_evaluable"] for e in evaluations),
            "missed_visible": sum(e["visibility"] in {"visible", "partial"} and not e["fresh"]
                                  for e in evaluations), **counts}


def recovery_delays(rows: list[dict], complete_contiguous: bool) -> list[dict] | None:
    if not complete_contiguous:
        return None
    episodes, hidden, reappeared = [], False, None
    for row in rows:
        if row["evaluation"]["visibility"] in {"hidden", "unknown"}:
            hidden = True
            reappeared = None
        elif hidden and row["evaluation"]["identity_evaluable"]:
            reappeared = row["at"] if reappeared is None else reappeared
            if row["evaluation"]["outcome"] == "correct_fresh_identity":
                episodes.append({"reappeared_at": reappeared,
                                 "fresh_identity_delay_seconds": row["at"] - reappeared})
                hidden, reappeared = False, None
    if hidden:
        episodes.append({"reappeared_at": reappeared, "fresh_identity_delay_seconds": None})
    return episodes


def evaluate(manifest: dict, root: Path = ROOT, *, detector_factory=None) -> dict:
    validate(manifest, root)
    from maplebot.config import Config

    config = Config.load(workspace_path(root, manifest["config_path"]))
    if detector_factory is None:
        from maplebot.perception import TemplateDetector

        detector_factory = TemplateDetector
    semantics, timings, all_rows = [], [], []
    for sequence in manifest["sequences"]:
        started = time.perf_counter()
        detector = detector_factory(workspace_path(root, manifest["templates_path"]),
                                    config.perception)
        load_ms = (time.perf_counter() - started) * 1000
        rows, elapsed = [], []
        try:
            detector.taught_map = manifest.get("taught_map", True)
            for frame in sequence["frames"]:
                image = cv2.imread(str(workspace_path(root, frame["path"])), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError(f"Could not decode frame: {frame['path']}")
                began = time.perf_counter()
                # Finish any asynchronous title work before detection so the same pixels
                # cannot select different catalogs according to worker completion timing.
                if hasattr(detector, "map_filter"):
                    for _ in range(3):
                        detector.map_filter.select(image, detector.taught_map)
                        pending = detector.map_filter.pending
                        if pending is None:
                            break
                        pending.result()
                map_ms = (time.perf_counter() - began) * 1000
                began = time.perf_counter()
                observed = detector.detect(image, frame["at"],
                                           monsters=manifest.get("monsters", False))
                elapsed.append({"map_ms": map_ms,
                                "detect_ms": (time.perf_counter() - began) * 1000})
                player = observed.player
                prediction = None if player is None else {
                    "box": [player.box.x, player.box.y, player.box.width, player.box.height],
                    "confidence": player.confidence, "tracked": player.tracked,
                    "template": player.template, "identity": player.identity}
                rows.append({"path": frame["path"], "at": frame["at"], "player": prediction,
                             "evaluation": score(frame, prediction, config.perception.confidence,
                                                 manifest["identities"])})
        finally:
            if hasattr(detector, "map_filter"):
                detector.map_filter.close()
            if hasattr(detector, "pool"):
                detector.pool.shutdown(wait=True, cancel_futures=True)
        all_rows.extend(rows)
        semantics.append({"id": sequence["id"], "split": sequence["split"],
                          "kind": sequence.get("kind", "real"), "frames": rows,
                          "counts": aggregate(rows), "sampled_recovery": recovery_delays(
                              rows, sequence.get("complete_contiguous", False))})
        timings.append({"id": sequence["id"], "load_ms": load_ms, "frames": elapsed})
    return {"version": 1, "input_sent": False, "capture_started": False,
            "semantic": {"sequences": semantics, "counts": aggregate(all_rows)},
            "timing": timings,
            "limitations": ["Independent labels are asserted by the manifest author.",
                            "Named identity evidence is distinct from geometric proximity.",
                            "Sampled fresh identity is not runtime resume or native acceptance."]}


def run(manifest_path: Path, output: Path, root: Path = ROOT, *, detector_factory=None) -> dict:
    manifest_path, output = manifest_path.resolve(), output.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protected = validate(manifest, root) | {manifest_path}
    if (output in protected or output.exists()
            or output.is_relative_to(workspace_path(root, manifest["templates_path"]))):
        raise ValueError("Output must be a new file, never a frozen input")
    report = evaluate(manifest, root, detector_factory=detector_factory)
    report["manifest_sha256"] = digest(manifest_path)
    report["config_sha256"] = manifest["config_sha256"]
    report["source_sha256"] = manifest["source_sha256"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.manifest, args.output)
    print(json.dumps(report["semantic"]["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
