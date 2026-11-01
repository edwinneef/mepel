"""Coordinate-checked synthetic evaluation material. No network, capture or input."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

RESERVE = {
    "000001000": "The Field West of Amherst",
    "010000020": "3-Way Road-Split",
    "010004020": "West Rocky Mountain I",
    "010005010": "Swampy Land in a Deep Forest",
    "010002000": "Ellinia",
    "010000000": "Lith Harbor",
}
CRITERIA = {"minimum_maps": 2, "p95_error_px": 4,
            "minimum_observable_coverage": .8, "maximum_label_uncertainty_px": 2,
            "maximum_false_ready": 0}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in value)):
        raise ValueError("Expected a finite XY pair")
    return np.array(value, dtype=float)


def coordinate_check(anchors):
    """Check a unit-scale translation; never silently fit rotation, scaling or a warp."""
    if len(anchors) < 3 or len({a["name"] for a in anchors}) != len(anchors):
        raise ValueError("Need at least three uniquely named independent anchors")
    world = np.array([point(a["world"]) for a in anchors])
    rendered = np.array([point(a["render"]) for a in anchors])
    uncertainty = [a["uncertainty_px"] for a in anchors]
    if any(type(v) not in (float, int) or not 0 <= v <= 2 for v in uncertainty):
        raise ValueError("Anchor uncertainty exceeds two pixels")
    if np.linalg.matrix_rank(world - world[0]) != 2:
        raise ValueError("Anchors must span both axes, not one line")
    training = [i for i, a in enumerate(anchors) if a.get("withheld") is not True]
    withheld = [i for i, a in enumerate(anchors) if a.get("withheld") is True]
    if len(training) < 2 or not withheld:
        raise ValueError("Keep an independent anchor withheld from the transform")
    offset = np.mean((rendered - world)[training], axis=0)
    errors = np.linalg.norm(rendered - world - offset, axis=1)
    bound = float(max(errors[i] + uncertainty[i] for i in range(len(anchors))))
    if bound > 2:
        raise ValueError("Source/render origin, scale or orientation mismatch")
    return {"translation": offset.tolist(), "scale": 1, "label_uncertainty_px": bound,
            "maximum_residual_px": float(max(errors)), "withheld": len(withheld)}


def read_asset(asset, root):
    path = (root / asset["path"]).resolve()
    if digest(path) != asset["sha256"]:
        raise ValueError("Asset hash changed")
    return path


def write_report(path, value):
    path = Path(path).resolve()
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    if path.is_relative_to(protected):
        raise ValueError("Evaluation output must stay outside saved data")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def canonical(name):
    return "".join(c for c in name.casefold() if c.isalnum())


def inventory(root):
    """Pin metadata without decoding reserved render images or touching saved settings."""
    root = Path(root).resolve()
    exports = {}
    paths = list((root / "artifacts").glob("meowdb-*-export.json"))
    paths += list((root / "data/areas/public/meowdb-classic").glob("*.json"))
    for path in sorted(set(paths)):
        source = json.loads(path.read_text("utf-8"))
        identity = str(source["id"]).zfill(9)
        exports.setdefault(identity, {"path": str(path), "sha256": digest(path),
                                      "build": None})
    clips, unknown, observed = [], 0, set()
    for path in sorted((root / "data/recordings").glob("*/decisions.jsonl")):
        count, unnamed = 0, 0
        for line in path.read_text("utf-8").splitlines():
            row = json.loads(line)
            title = (row.get("catalog") or {}).get("active_map")
            if not title:
                unnamed += 1
            else:
                observed.add(canonical(title))
            count += 1
        unknown += unnamed
        clips.append({"path": str(path), "sha256": digest(path), "rows": count,
                      "unresolved_rows": unnamed})
    metadata = [{"path": str(p), "sha256": digest(p)} for p in
                sorted((root / "data/spawn-metadata").rglob("classic-source-maps.json"))]
    return {"schema_version": 1, "evidence_kind": "synthetic_reference_render",
            "input_sent": False, "native_acceptance": False, "criteria": dict(CRITERIA),
            "metadata": metadata, "recordings": clips,
            "split_audit": {"unresolved_rows": unknown, "observed_aliases": sorted(observed)},
            "diagnostic_maps": sorted(set(exports) - RESERVE.keys()),
            "maps": [{"map_id": key, "name": name, "aliases": [name],
                      "split": "evaluation", "raw": exports.get(key), "render": None,
                      "placements": None, "anchors": []} for key, name in RESERVE.items()]}


def portals(source):
    result = {}
    for item in source["portals"]:
        name = item["name"]
        if name in result:
            raise ValueError("Duplicate portal identity")
        result[name] = [item["x"], item["y"]]
    return result


def audit(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if manifest.get("evidence_kind") != "synthetic_reference_render":
        raise ValueError("A separate synthetic manifest is required")
    rows, identities, aliases = [], set(), set()
    for row in manifest["maps"]:
        identity = row["map_id"]
        if identity in identities:
            raise ValueError("Duplicate map identity")
        identities.add(identity)
        names = {canonical(v) for v in row["aliases"]}
        if not names or names & aliases:
            raise ValueError("Map aliases overlap or are missing")
        aliases.update(names)
        problems = []
        result = {"map_id": identity, "admitted": False, "problems": problems}
        if row.get("split") != "evaluation" or identity not in RESERVE:
            problems.append("Not a reserved evaluation map; diagnostic only")
        elif canonical(RESERVE[identity]) not in names:
            problems.append("Reserved map name missing from aliases")
        if manifest.get("split_audit", {}).get("unresolved_rows") != 0:
            problems.append("Unresolved recording aliases; held-out split unverified")
        observed = manifest.get("split_audit", {}).get("observed_aliases", [])
        if any(name in seen or seen in name for name in names for seen in observed if seen):
            problems.append("Reserved map alias already observed")
        try:
            assets = [row.get(key) for key in ("raw", "render", "placements")]
            if any(not asset for asset in assets):
                raise ValueError("Missing raw terrain, full render or placement metadata")
            builds = {asset.get("build") for asset in assets}
            if len(builds) != 1 or not next(iter(builds)):
                raise ValueError("Compatible source/render build provenance missing")
            raw, rendered, placements = [read_asset(a, manifest_path.parent) for a in assets]
            picture = cv2.imread(str(rendered))
            if picture is None:
                raise ValueError("Full render is not a readable image")
            geometry = json.loads(raw.read_text("utf-8"))
            placement = json.loads(placements.read_text("utf-8"))
            if (str(geometry["id"]).zfill(9) != identity
                    or str(placement["id"]).zfill(9) != identity):
                raise ValueError("Source/placement map identity mismatch")
            world, image = portals(geometry), portals(placement)
            for anchor in row["anchors"]:
                if (anchor["name"] not in world or anchor["name"] not in image
                        or not np.array_equal(point(anchor["world"]), point(world[anchor["name"]]))
                        or not np.array_equal(point(anchor["render"]),
                                              point(image[anchor["name"]]))):
                    raise ValueError("Anchor not backed by independent named placement records")
                x, y = point(anchor["render"])
                if not (0 <= x < picture.shape[1] and 0 <= y < picture.shape[0]):
                    raise ValueError("Anchor lies outside full render")
            result["transform"] = coordinate_check(row["anchors"])
            result["assets"] = {k: str(p) for k, p in
                                zip(("raw", "render", "placements"),
                                    (raw, rendered, placements), strict=True)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            problems.append(str(error))
        result["admitted"] = not problems
        rows.append(result)
    missing = sorted(RESERVE.keys() - identities)
    return {"schema_version": 1, "evidence_kind": "synthetic_reference_render",
            "manifest_sha256": digest(manifest_path), "input_sent": False,
            "native_acceptance": False, "native_build_verified": False,
            "maps": rows, "missing_reserved_maps": missing,
            "admitted_maps": sum(r["admitted"] for r in rows),
            "ready_for_generation": not missing and any(r["admitted"] for r in rows)}


def marker_projection(world, center, magnification):
    """Declared reference convention, including the larger zero bin of signed truncation."""
    if type(magnification) is not int or not 0 <= magnification <= 8:
        raise ValueError("Invalid declared minimap magnification")
    scale = 2 ** magnification
    dot, intervals = [], []
    for value, origin in zip(point(world), point(center), strict=True):
        rounded = math.floor(value + .5) if value >= 0 else math.ceil(value - .5)
        q = math.trunc((rounded + origin) / scale)
        lo = (q - 1) * scale + 1 if q <= 0 else q * scale
        hi = (q + 1) * scale - 1 if q >= 0 else q * scale
        dot.append(q)
        intervals.append([lo - origin, hi - origin])
    return dot, intervals


def _png(path, image):
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Cannot encode synthetic frame")
    with path.open("xb") as handle:
        handle.write(encoded.tobytes())


def generate(manifest_path, output, seed=0):
    """Independent drawing coordinates are answers, never obtained from a locator."""
    from maplebot.meowdb import normalize
    from maplebot.public_map import picture

    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    checked = audit(manifest_path)
    if not checked["ready_for_generation"]:
        raise ValueError("No sealed, coordinate-admitted corpus; inspect the source audit")
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    if output.is_relative_to(protected):
        raise ValueError("Corpus output must stay outside saved data")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    admitted = [r for r in checked["maps"] if r["admitted"]]
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("frames", "geometry"):
        (output / folder).mkdir()
    rng, inputs, labels = np.random.default_rng(seed), [], []
    sources = {}
    for item in admitted:
        raw = json.loads(Path(item["assets"]["raw"]).read_text("utf-8"))
        source = normalize(raw) if "terrain" in raw else raw
        # No render paths, origins, camera poses or evaluation answers reach the predictor.
        source = {k: source[k] for k in ("id", "miniMap", "footholds", "ladderRopes")}
        sources[item["map_id"]] = source
        write_report(output / "geometry" / f"{item['map_id']}.json", source)
    cases = ("baseline", "scaled", "scroll", "occluded", "repeated", "blank",
             "wrong-source", "clipped")
    for item in admitted:
        key = item["map_id"]
        source = sources[key]
        render = cv2.imread(item["assets"]["render"])
        minimap = picture(source["miniMap"])
        mh, mw = minimap.shape[:2]
        if mw > 600 or mh > 330:
            raise ValueError("Reference minimap exceeds the declared synthetic layout")
        center = [source["miniMap"]["centerX"], source["miniMap"]["centerY"]]
        mag = source["miniMap"].get("magnification", source["miniMap"].get("mag"))
        offset = point(item["transform"]["translation"])
        points = manifest["maps"][[r["map_id"] for r in manifest["maps"]].index(key)]
        requested = point(points["anchors"][0]["world"]) + rng.integers(8, 24, 2)
        for sequence, case in enumerate(cases):
            scale = .75 if case == "scaled" else 1.
            foot = np.array([512., 480.])
            camera = requested + offset - foot / scale
            if case == "scroll":
                camera += [15, -12]
            if case == "clipped":
                camera = requested + offset - [4, 480]
            foot = np.rint((requested + offset - camera) * scale)
            truth = foot / scale + camera - offset
            image = cv2.warpAffine(render, np.array([[scale, 0, -camera[0] * scale],
                                                     [0, scale, -camera[1] * scale]]),
                                   (1024, 768))
            x, y = (int(v) for v in foot)
            cv2.rectangle(image, (max(0, x - 12), y - 36), (x + 11, y - 1), (80, 190, 90), -1)
            box = {"x": max(0, x - 12), "y": y - 36,
                   "width": x + 12 - max(0, x - 12), "height": 36}
            dot, intervals = marker_projection(truth.tolist(), center, mag)
            # Fixed canvas/marker asset origins are declared synthetic values, not native facts.
            image[28:28 + mh, 8:8 + mw] = minimap[..., :3]
            cv2.rectangle(image, (7, 27), (8 + mw, 28 + mh), (210, 210, 210), 1)
            mx, my = 8 + dot[0], 28 + dot[1]
            cv2.rectangle(image, (mx - 2, my - 5), (mx + 2, my - 1), (0, 255, 255), -1)
            visible = []
            for anchor in points["anchors"]:
                ax, ay = (point(anchor["world"]) + offset - camera) * scale
                if (0 <= ax < 1024 and 0 <= ay < 768
                        and not (8 <= ax < 8 + mw and 28 <= ay < 28 + mh)):
                    visible.append(anchor["world"])
            spread = len(visible) >= 3 and np.linalg.matrix_rank(
                np.array(visible) - visible[0]) == 2
            observable = case in {"baseline", "scaled", "scroll"} and bool(spread)
            if case == "occluded":
                cv2.rectangle(image, (x - 15, y - 40), (x + 15, y + 2), (0, 0, 0), -1)
            elif case == "repeated":
                image[:, 512:] = image[:, :512]
                cv2.rectangle(image, (x - 12, y - 36), (x + 11, y - 1), (80, 190, 90), -1)
            elif case == "blank":
                image[:] = 0
            geometry_key = key
            if case == "wrong-source":
                others = [k for k in sources if k != key]
                if not others:
                    continue
                geometry_key = others[0]
            name = f"{key}-{case}"
            frame = output / "frames" / f"{name}.png"
            _png(frame, image)
            geometry = output / "geometry" / f"{geometry_key}.json"
            inputs.append({"id": name, "map_id": key, "case": case,
                           "frame": str(frame.relative_to(output)), "sha256": digest(frame),
                           "geometry": str(geometry.relative_to(output)),
                           "geometry_sha256": digest(geometry), "sequence": sequence,
                           "oracle_player": {"box": box, "confidence": 1., "kind": "player"}
                           if case not in {"blank", "occluded", "clipped"} else None})
            labels.append({"id": name, "sha256": digest(frame), "truth_xy": truth.tolist(),
                           "method": "constructed_drawing_coordinates",
                           "observable": observable, "camera": camera.tolist(), "scale": scale,
                           "label_uncertainty_px": item["transform"]["label_uncertainty_px"],
                           "marker_bin_integer_world": intervals, "marker_center": dot,
                           "actor_foot_origin": [12, 36], "marker_origin": [2, 5],
                           "source_pair_verified": True, "contact_verified": False})
    if audit(manifest_path) != checked:
        raise ValueError("Source manifest or assets changed during generation")
    common = {"schema_version": 1, "evidence_kind": "synthetic_reference_render",
              "input_sent": False, "native_acceptance": False,
              "source_manifest_sha256": checked["manifest_sha256"],
              "generator_sha256": digest(__file__), "seed": seed, "frame_interval_s": .1}
    write_report(output / "labels.json", {**common, "frames": labels})
    write_report(output / "inputs.json", {**common, "maps": list(RESERVE),
                                         "criteria": dict(CRITERIA), "frames": inputs,
                                         "labels_sha256": digest(output / "labels.json")})
    return {**common, "frames": len(inputs), "admitted_maps": len(admitted),
            "inputs_sha256": digest(output / "inputs.json"),
            "labels_sha256": digest(output / "labels.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("inventory")
    scan.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    scan.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("audit")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("generate")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.command == "generate":
        print(json.dumps(generate(args.manifest, args.output, args.seed)))
        return
    result = inventory(args.root) if args.command == "inventory" else audit(args.manifest)
    write_report(args.output, result)
    print(json.dumps({"report": str(args.output), "input_sent": False,
                      "native_acceptance": False, "admitted_maps": result.get("admitted_maps")}))


if __name__ == "__main__":
    main()
