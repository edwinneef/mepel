"""Trace Southperry artwork from receipt-pinned copies only; never read installed files."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from tools.export_classic_assets import (
    MAX_INPUT,
    MAX_OUTPUT,
    check_output,
    digest,
    load_json,
    parser_files,
    relative,
    safe_path,
    write_json,
)
from tools.southperry_render_dependencies import dependencies

EXPECTED = {f"Map/{category}/{name}" for category in ("Tile", "Obj", "Back")
            for name in (f"{category}_000.wz", f"{category}.ini", f"{category}.wz")}


def validate_copies(root, receipt):
    root = safe_path(root)
    rows = load_json(safe_path(receipt))
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        raise ValueError("Expected nine artwork archives/index copies")
    total, found, originals = 0, {}, []
    for row in rows:
        name = relative(row["relative"])
        if name not in EXPECTED or name in found:
            raise ValueError("Unexpected/duplicate artwork copy")
        path = safe_path(root / name)
        original = Path(row["original"])
        if (safe_path(row["copy"]) != path or not path.is_relative_to(root)
                or not original.is_absolute() or original == path
                or root.is_relative_to(original.parent)):
            raise ValueError("Invalid copy/original boundary")
        if type(row["bytes"]) is not int or not 0 <= row["bytes"] <= MAX_INPUT:
            raise ValueError("Invalid copy size")
        total += row["bytes"]
        if (total > MAX_INPUT or path.stat().st_size != row["bytes"]
                or digest(path) != row["sha256"]):
            raise ValueError("Artwork size/hash mismatch")
        originals.append(original)
        found[name] = row
    return root, found, originals


def summarize(report, indexes):
    if report.get("map_id") != "000000060" or report.get("schema") != 1:
        raise ValueError("Changed trace identity")
    if indexes.get("map_id") != "000000060" or indexes.get("schema") != 1:
        raise ValueError("Changed archive index identity")
    missing = {}
    graph = {}
    for row in report["links"]:
        source = relative(row["image"] + "/" + row["property"])
        target = relative(row["target"])
        parts = target.split("/")
        split = next((i for i, part in enumerate(parts) if part.endswith(".img")), -1)
        if split not in (2, 3) or parts[0] != "Map" or parts[1] not in ("Tile", "Obj", "Back"):
            raise ValueError("Out-of-scope artwork link")
        if split == 3:
            if parts[2] != "_Canvas" or row["target_is_copied"] is not False:
                raise ValueError("Invalid missing-canvas link")
            archive = f"Map/{parts[1]}/_Canvas/_Canvas_000.wz"
            candidates = [a for a in indexes["archives"] if a["category"] == parts[1]
                          and a["canvas"] is True]
            if (len(candidates) != 1 or candidates[0]["index_text"] != "LastWzIndex|0"
                    or not candidates[0]["path"].replace("\\", "/").endswith(archive)
                    or parts[split] not in candidates[0]["matching_images"]):
                raise ValueError("Bitmap archive/image not backed by observed directory index")
            missing.setdefault(archive, set()).add(target)
        elif row["target_is_copied"] is not True:
            raise ValueError("Copied artwork target misclassified")
        graph.setdefault(source, []).append(target)

    def visit(node, trail):
        if len(trail) > 16 or node in trail:
            raise ValueError("Artwork link cycle/depth exceeded")
        for target in graph.get(node, []):
            visit(target, trail | {node})

    for node in graph:
        visit(node, set())
    return {"missing_bitmap_archives": {k: sorted(v) for k, v in sorted(missing.items())},
            "link_count": len(report["links"]), "branch_count": len(report["branches"]),
            "bitmap_link_closure_verified": not missing}


def trace(root, receipt, bundle, extractor, output, indexes):
    root, inputs, originals = validate_copies(root, receipt)
    bundle = safe_path(bundle)
    output = check_output(output, root, originals)
    if output.is_relative_to(bundle):
        raise ValueError("Output must stay outside reference bundle")
    manifest = load_json(bundle / "manifest.json")
    raw = bundle / "raw.json"
    if digest(raw) != manifest["outputs"]["raw.json"]:
        raise ValueError("Reference bundle changed")
    request = dependencies(load_json(raw, MAX_OUTPUT))
    indexes = safe_path(indexes)
    index_report = load_json(indexes)
    parser = parser_files(extractor)
    pins = {"receipt": digest(receipt), "raw": digest(raw),
            "manifest": digest(bundle / "manifest.json"), "indexes": digest(indexes)}
    with tempfile.TemporaryDirectory(prefix=".artwork-links-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        assets = temporary / "assets"
        for name, row in inputs.items():
            target = assets / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
            if digest(target) != row["sha256"]:
                raise ValueError("Artwork copy changed during staging")
        write_json(temporary / "request.json", request)
        parsed = temporary / "trace.json"
        try:
            subprocess.run(["dotnet", str(safe_path(extractor)), "--trace-artwork", str(assets),
                            str(temporary / "request.json"), str(parsed)], check=True, timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as error:
            raise ValueError("Artwork parser refused: " + error.stderr.decode(errors="replace")) \
                from error
        report = load_json(parsed, MAX_OUTPUT)
        seeds = {(row["image"], path) for row in request["core_scenery"] for path in row["entries"]}
        if not seeds <= {(row["image"], row["property"]) for row in report["branches"]}:
            raise ValueError("Trace omitted a required artwork entry")
        report["summary"] = summarize(report, index_report)
        for name, row in inputs.items():
            if digest(root / name) != row["sha256"]:
                raise ValueError("Artwork input changed during trace")
        if (pins != {"receipt": digest(receipt), "raw": digest(raw),
                     "manifest": digest(bundle / "manifest.json"), "indexes": digest(indexes)}
                or parser_files(extractor) != parser):
            raise ValueError("Trace references/parser changed")
        report["provenance"] = {"inputs": inputs, "parser": parser, "reference_hashes": pins}
        report["native_acceptance"] = report["input_sent"] = False
        report["pixels_decoded"] = False
        write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "receipt", "bundle", "extractor", "output", "indexes"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = trace(args.source_root, args.receipt, args.bundle, args.extractor, args.output,
                   args.indexes)
    summary = report["summary"]
    print({"branches": summary["branch_count"], "links": summary["link_count"],
           "missing_bitmap_archives": list(summary["missing_bitmap_archives"])})


if __name__ == "__main__":
    main()
