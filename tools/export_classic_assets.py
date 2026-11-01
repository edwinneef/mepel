"""Bounded, copied-assets-only Southperry diagnostic exporter. No runtime imports."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zlib
from pathlib import Path

import cv2
import numpy as np

PARSER_COMMIT = "04570d43cd90e1b42f613226dd0be22ce58abd1c"
PROJECT = Path(__file__).resolve().parents[1]
MAX_INPUT = 64 * 1024 * 1024
MAX_OUTPUT = 16 * 1024 * 1024
REQUIRED = {"Map/Map/Map0/Map0_000.wz", "Map/Map_000.wz",
            "Map/Map/Map0/_Canvas/_Canvas_000.wz", "Map/_Canvas/_Canvas_000.wz"}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def safe_path(path):
    """Reject junctions/symlinks before resolving; never follow a saved-path alias."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0)
                                 & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("Reparse/symlink paths are forbidden")
    return path.resolve()


def relative(value):
    if not isinstance(value, str):
        raise ValueError("Invalid relative path")
    parts = value.replace("\\", "/").split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise ValueError("Unsafe relative path")
    return "/".join(parts)


def load_json(path, limit=1024 * 1024):
    if Path(path).stat().st_size > limit:
        raise ValueError("JSON size budget exceeded")
    return json.loads(Path(path).read_text("utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8")


def copied_inputs(source_root, receipt):
    root = safe_path(source_root)
    if root.is_relative_to(PROJECT / "data"):
        raise ValueError("Saved data is not a copied-asset root")
    # Installed locations are never discovered or read. The receipt is declarative only.
    rows = load_json(safe_path(receipt))
    if not isinstance(rows, list) or not 4 <= len(rows) <= 32:
        raise ValueError("Invalid receipt")
    found, originals, total = {}, [], 0
    for row in rows:
        name = relative(row["relative"])
        if name.casefold() in {n.casefold() for n in found}:
            raise ValueError("Duplicate receipt path")
        original = Path(os.path.abspath(row["original"]))
        originals.append(original)
        if (not isinstance(row["copy"], str)
                or safe_path(row["copy"]) != root / name):
            raise ValueError("Receipt copy does not match copied root")
        path = safe_path(root / name)
        if (not path.is_relative_to(root) or path == original
                or root.is_relative_to(original.parent)):
            raise ValueError("Installed/source path is forbidden")
        if not path.is_file() or type(row["bytes"]) is not int or row["bytes"] < 0:
            raise ValueError("Missing archive/invalid size")
        total += row["bytes"]
        if total > MAX_INPUT or path.stat().st_size != row["bytes"]:
            raise ValueError("Input byte budget/size mismatch")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", row["sha256"]):
            raise ValueError("Invalid receipt hash")
        if digest(path) != row["sha256"].lower():
            raise ValueError("Input hash mismatch")
        found[name] = {"path": path, "bytes": row["bytes"], "sha256": digest(path)}
    if not REQUIRED <= found.keys():
        raise ValueError("Missing required archive")
    return root, found, originals


def check_output(output, root, originals):
    output = safe_path(output)
    if output.exists():
        raise ValueError("Output collision: use a new directory")
    if output.is_relative_to(PROJECT) and not output.is_relative_to(PROJECT / "artifacts"):
        raise ValueError("Protected project destination")
    forbidden = [root, PROJECT / "src", PROJECT / "data", PROJECT / "tools", PROJECT / "tests"]
    forbidden += [p.parent for p in originals]
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in forbidden):
        raise ValueError("Protected source/installed/saved-data destination")
    if not output.parent.is_dir():
        raise ValueError("Output parent must already exist")
    return output


def parser_files(extractor):
    extractor = safe_path(extractor)
    receipt = load_json(extractor.parent / "parser-receipt.json")
    if receipt.get("commit") != PARSER_COMMIT or receipt.get("schema") != 1:
        raise ValueError("Parser identity mismatch")
    sources = PROJECT / "tools/classic_asset_extractor"
    expected_sources = {name: digest(sources / name)
                        for name in ("Program.cs", "ClassicAssetExtractor.csproj")}
    if receipt.get("extractor_sources") != expected_sources:
        raise ValueError("Extractor source changed; rebuild before exporting")
    pins = receipt.get("files", {})
    if extractor.name not in pins or "MapleLib.dll" not in pins:
        raise ValueError("Incomplete parser receipt")
    actual = {p.name for p in extractor.parent.iterdir() if p.is_file()
              and p.suffix in (".dll", ".json") and p.name != "parser-receipt.json"}
    if actual != set(pins):
        raise ValueError("Parser dependencies changed")
    for name, expected in pins.items():
        path = safe_path(extractor.parent / relative(name))
        if path.parent != extractor.parent or digest(path) != expected:
            raise ValueError("Parser hash mismatch")
    return receipt


def decode_canvas(output, name, metadata):
    width, height = metadata["width"], metadata["height"]
    if (metadata["format"] != 1 or type(width) is not int or type(height) is not int
            or min(width, height) <= 0 or width * height > 1000000):
        raise ValueError("Unsupported image format/size")
    compressed = (output / (name + ".compressed.bin")).read_bytes()
    if compressed[:2] != b"\x78\x9c":
        raise ValueError("Unsupported compressed header")
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    packed = inflater.decompress(compressed[2:], width * height * 2 + 1)
    if (len(packed) != width * height * 2 or inflater.unconsumed_tail
            or inflater.unused_data):
        raise ValueError("Packed pixel size/trailing data mismatch")
    words = np.frombuffer(packed, dtype="<u2")
    bgra = np.stack([(words >> shift & 15) * 17 for shift in (0, 4, 8, 12)], axis=1)
    expected = bgra.astype("uint8").reshape(height, width, 4)
    decoded = cv2.imread(str(output / (name + ".png")), cv2.IMREAD_UNCHANGED)
    if decoded is None or not np.array_equal(decoded, expected):
        raise ValueError("Independent pixel decoder mismatch")
    return {"pixels": width * height, "different_pixels": 0,
            "packed_sha256": hashlib.sha256(packed).hexdigest(),
            "raw_deflate_stream_complete": inflater.eof,
            "zlib_footer_checksum_verified": False}


def link_chain(metadata):
    chain = metadata["chain"]
    if not 1 <= len(chain) <= 16:
        raise ValueError("Invalid link depth")
    seen = set()
    for row in chain:
        key = (relative(row["archive"]), relative(row["image"]), relative(row["property"]))
        if key in seen:
            raise ValueError("Link cycle")
        seen.add(key)
        if row["archive"] not in REQUIRED:
            raise ValueError("Unreceipted link archive")
    for index, row in enumerate(chain):
        props = row["metadata"]["properties"]
        targets = [props[key] for key in ("_outlink", "_inlink") if key in props]
        if len(targets) > 1 or bool(targets) != (index < len(chain) - 1):
            raise ValueError("Incomplete/ambiguous link chain")
        if targets:
            target = relative(targets[0])
            following = chain[index + 1]
            expected = (following["archive"].rsplit("/", 1)[0] + "/"
                        + following["image"] + "/" + following["property"])
            if "_outlink" in props and target != expected:
                raise ValueError("Changed link identity")
            if "_inlink" in props and (target != following["property"]
                                      or row["archive"] != following["archive"]
                                      or row["image"] != following["image"]):
                raise ValueError("Changed local link identity")
    return chain


def validate_bundle(output):
    source = load_json(output / "raw.json", MAX_OUTPUT)
    if source.get("schema") != 1 or source.get("map_id") != "000000060":
        raise ValueError("Changed map identity")
    raw = source["raw"]
    footholds = [{"layer": layer, "group": group, "id": identity, **values}
                 for layer, groups in raw["foothold"].items()
                 for group, segments in groups.items() for identity, values in segments.items()]
    for row in footholds:
        if not {"x1", "y1", "x2", "y2", "prev", "next", "piece"} <= row.keys():
            raise ValueError("Foothold metadata loss")
    ladders = [{"id": key, **value} for key, value in raw["ladderRope"].items()]
    portals = [{"id": key, **value} for key, value in raw["portal"].items()]
    if (len(footholds), len(ladders), len(portals)) != (205, 7, 10):
        raise ValueError("Southperry geometry count mismatch")
    if any(not {"pn", "pt", "x", "y"} <= row.keys() for row in portals):
        raise ValueError("Portal metadata loss")
    mini = raw["miniMap"]
    if [mini[k] for k in ("centerX", "centerY", "mag")] != [652, 1505, 4]:
        raise ValueError("Minimap metadata mismatch")
    origin = raw["miniMap"]["canvas"]["properties"].get("origin")
    marker_origin = source["marker"]["properties"].get("origin")
    if marker_origin != {"type": "vector", "x": 6, "y": 6} or origin is not None:
        raise ValueError("Unexpected origin metadata")
    checks = {}
    for key, name, size in (("minimap_canvas", "minimap-canvas", (295, 138)),
                            ("player_marker", "player-marker", (12, 12))):
        meta = source[key]
        if (meta["width"], meta["height"]) != size:
            raise ValueError("Canvas dimensions changed")
        chain = link_chain(meta)
        original = mini["canvas"] if key == "minimap_canvas" else source["marker"]
        if chain[0]["metadata"] != original:
            raise ValueError("Original canvas metadata loss")
        checks[name] = decode_canvas(output, name, meta)
    write_json(output / "geometry.json", {"schema": 1, "map_id": "000000060",
               "footholds": footholds, "ladderRope": ladders, "portals": portals,
               "miniMap": mini, "canvas_origin": origin, "user_origin": marker_origin})
    return source, checks


def export(source_root, receipt, map_id, output, extractor, timeout=30):
    if str(map_id) not in ("60", "000000060"):
        raise ValueError("This diagnostic exporter supports Southperry 60 only")
    if not 1 <= timeout <= 60:
        raise ValueError("Parser timeout must be 1..60 seconds")
    root, inputs, originals = copied_inputs(source_root, receipt)
    output = check_output(output, root, originals)
    parser = parser_files(extractor)
    receipt_hash = digest(receipt)
    # A private staging tree contains only receipt-pinned copies, never installed paths.
    with tempfile.TemporaryDirectory(prefix=".classic-export-", dir=output.parent) as scratch:
        scratch = Path(scratch)
        assets = scratch / "assets"
        for name, row in inputs.items():
            target = assets / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row["path"], target)
            if digest(target) != row["sha256"]:
                raise ValueError("Copied input changed while staging")
        bundle = scratch / "bundle"
        subprocess.run(["dotnet", str(safe_path(extractor)), str(assets), "60", str(bundle)],
                       check=True, timeout=timeout, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, env={**os.environ,
                       "DOTNET_CLI_TELEMETRY_OPTOUT": "1"})
        files = list(bundle.rglob("*"))
        if (len(files) > 16 or any(not p.is_file() or p.is_symlink() for p in files)
                or sum(p.stat().st_size for p in files) > MAX_OUTPUT):
            raise ValueError("Output budget exceeded")
        expected = {"raw.json", "minimap-canvas.png", "player-marker.png",
                    "minimap-canvas.compressed.bin", "player-marker.compressed.bin"}
        if {p.name for p in files} != expected:
            raise ValueError("Unexpected parser output")
        source, checks = validate_bundle(bundle)
        for row in inputs.values():
            if digest(row["path"]) != row["sha256"]:
                raise ValueError("Source changed during parsing")
        if digest(receipt) != receipt_hash or parser_files(extractor) != parser:
            raise ValueError("Receipt/parser changed during parsing")
        write_json(bundle / "manifest.json", {
            "schema": 1, "scope": "Southperry diagnostic only", "map_id": "000000060",
            "parser": {"commit": PARSER_COMMIT, "format": "MapleLib WZ", "receipt": parser,
                       "archives": source["archives"]},
            "inputs": {name: {"path": str(row["path"]), "sha256": row["sha256"],
                              "bytes": row["bytes"]} for name, row in sorted(inputs.items())},
            "asset_receipt_sha256": receipt_hash,
            "outputs": {p.name: digest(p) for p in sorted(bundle.iterdir())},
            "independent_pixel_checks": checks,
            "origins_and_links": {k: source[k] for k in ("minimap_canvas", "player_marker")},
            "native_build_identity": None, "recording_build_identity": None,
            "footage_coverage": "Separate nine-frame check; 210x138 visible, 85 columns unobserved",
            "fixture_admission_ready": False, "native_acceptance": False, "input_sent": False,
            "gaps": ["full-world render", "independent placements/XY/contact",
                     "native/client build identity", "six reserve bundles", "105 unnamed rows"]})
        # rename refuses an existing destination on Windows; never merge or replace.
        if output.exists():
            raise ValueError("Output collision during publication")
        bundle.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--map-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extractor", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(export(args.source_root, args.receipt, args.map_id, args.output, args.extractor))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Export refused: {error}\n")


if __name__ == "__main__":
    main()
