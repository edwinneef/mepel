"""List Southperry artwork references from a pinned exported bundle, without opening WZ."""

import argparse
from pathlib import Path

from tools.export_classic_assets import (
    check_output,
    digest,
    load_json,
    relative,
    safe_path,
    write_json,
)


def component(value):
    if type(value) not in (str, int) or not str(value):
        raise ValueError("Missing artwork reference component")
    value = str(value)
    if "/" in relative(value):
        raise ValueError("Artwork reference must be one path component")
    return value


def dependencies(source):
    if source.get("map_id") != "000000060":
        raise ValueError("Southperry only; do not inspect reserve maps")
    sections = source["render_sections"]
    sets, entities = {}, []
    counts = {"tile": 0, "object": 0, "background": 0}

    def add(category, name, entry, placement, kind):
        image = f"Map/{category}/{component(name)}.img"
        row = sets.setdefault(image, {"image": image, "category": category,
                                    "placements": [], "entries": set(),
                                    "physical_archive": None,
                                    "bitmap_links_resolved": False})
        row["entries"].add("/".join(component(v) for v in entry))
        row["placements"].append(placement)
        counts[kind] += 1

    for layer_id, layer in sections.items():
        if layer_id == "back":
            for key, bg in layer.items():
                if type(bg["ani"]) is not int or bg["ani"] not in (0, 1):
                    raise ValueError("Unsupported background animation flag")
                add("Back", bg["bS"], ["ani" if bg["ani"] else "back", bg["no"]],
                    f"back/{component(key)}", "background")
            continue
        if layer_id not in {str(i) for i in range(8)}:
            raise ValueError("Unexpected scene section")
        for key, tile in layer["tile"].items():
            add("Tile", layer["info"]["tS"], [tile["u"], tile["no"]],
                f"{layer_id}/tile/{component(key)}", "tile")
        for key, obj in layer["obj"].items():
            add("Obj", obj["oS"], [obj["l0"], obj["l1"], obj["l2"]],
                f"{layer_id}/obj/{component(key)}", "object")
    for kind, rows in source.get("scene_entities", {}).items():
        for key, row in (rows or {}).items():
            if kind == "life":
                category = {"n": "Npc", "m": "Mob"}.get(row.get("type"))
                if category is None:
                    raise ValueError("Unknown map entity type")
            elif kind == "reactor":
                category = "Reactor"
            else:
                raise ValueError("Unknown map entity section")
            identity = component(row["id"])
            if not identity.isdecimal():
                raise ValueError("Entity ID must be decimal")
            entities.append({"placement": f"{kind}/{component(key)}",
                             "image": f"{category}/{identity.zfill(7)}.img",
                             "physical_archive": None})
    images = []
    for _, row in sorted(sets.items()):
        row["entries"] = sorted(row["entries"])
        row["placements"].sort()
        images.append(row)
    return {"schema": 1, "map_id": "000000060", "scope": "Southperry diagnostic references",
            "core_scenery": images, "placement_counts": counts,
            "optional_entities": entities,
            "portal_helper_present": source.get("portal_helper") is not None,
            "physical_archive_resolution_complete": False,
            "missing_index_categories": ["Map/Back", "Map/Obj", "Map/Tile"],
            "next_required_evidence": (
                "Copied per-category .ini and archive-directory/image-name indexes to map these "
                "logical images to physical .wz shards; then inspect only their referenced "
                "properties for _inlink/_outlink targets before requesting canvas shards."),
            "input_sent": False, "native_acceptance": False, "fixture_admission_ready": False}


def inspect(bundle, output):
    bundle = safe_path(bundle)
    output = check_output(output, bundle, [])
    manifest = load_json(bundle / "manifest.json")
    raw = bundle / "raw.json"
    if manifest.get("map_id") != "000000060" or digest(raw) != manifest["outputs"]["raw.json"]:
        raise ValueError("Export identity/hash mismatch")
    report = dependencies(load_json(raw, 16 * 1024 * 1024))
    report["source_raw_sha256"] = digest(raw)
    report["source_manifest_sha256"] = digest(bundle / "manifest.json")
    report["copied_archive_paths"] = sorted(manifest["inputs"])
    report["artwork_categories_present_in_copies"] = {
        category: any(name.startswith(category + "/") for name in manifest["inputs"])
        for category in report["missing_index_categories"]}
    write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.bundle, args.output)
    print(f"{len(report['core_scenery'])} artwork sets; physical archive filenames unresolved")


if __name__ == "__main__":
    main()
