"""Render Southperry's copied scenery offline; never reads installed WZ or controls the game."""

import argparse
import hashlib
import json
import math
import zlib
from pathlib import Path

import cv2
import numpy as np

from tools.export_classic_assets import check_output


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load(path):
    return json.loads(path.read_text("utf-8"))


def safe_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix not in {".png", ".bin"}:
        raise ValueError("Picture path escapes source")
    return path


def decode_picture(pictures, metadata):
    width, height = metadata["width"], metadata["height"]
    if metadata["format"] != 1 or min(width, height) <= 0 or width * height > 8000000:
        raise ValueError("Unsupported picture format/size")
    data = safe_file(pictures, metadata["compressed"]).read_bytes()
    if data[:2] != b"\x78\x9c":
        raise ValueError("Unsupported compressed header")
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    packed = inflater.decompress(data[2:], width * height * 2 + 1)
    if len(packed) != width * height * 2 or inflater.unconsumed_tail or inflater.unused_data:
        raise ValueError("Packed pixel size/trailing data mismatch")
    words = np.frombuffer(packed, dtype="<u2")
    expected = np.stack([(words >> shift & 15) * 17 for shift in (0, 4, 8, 12)], axis=1)
    expected = expected.astype("uint8").reshape(height, width, 4)
    image = cv2.imread(str(safe_file(pictures, metadata["file"])), cv2.IMREAD_UNCHANGED)
    if image is None or not np.array_equal(expected, image):
        raise ValueError("Independent pixel decoder mismatch")
    return image, {"pixels": width * height, "different_pixels": 0,
                   "packed_sha256": hashlib.sha256(packed).hexdigest(),
                   "raw_deflate_stream_complete": inflater.eof,
                   "zlib_footer_checksum_verified": False}


def composite(canvas, sprite, x, y, *, opacity=255):
    """Clipped straight-alpha BGRA over BGRA; preserve a transparent foreground export."""
    height, width = sprite.shape[:2]
    left, top = max(0, x), max(0, y)
    right, bottom = min(canvas.shape[1], x + width), min(canvas.shape[0], y + height)
    if left >= right or top >= bottom:
        return
    source = sprite[top - y:bottom - y, left - x:right - x].astype(np.float32) / 255
    destination = canvas[top:bottom, left:right].astype(np.float32) / 255
    alpha = source[:, :, 3:4] * opacity / 255
    out_alpha = alpha + destination[:, :, 3:4] * (1 - alpha)
    rgb = source[:, :, :3] * alpha + destination[:, :, :3] * destination[:, :, 3:4] * (1 - alpha)
    np.divide(rgb, out_alpha, out=rgb, where=out_alpha > 0)
    canvas[top:bottom, left:right] = np.rint(np.concatenate((rgb, out_alpha), axis=2) * 255)


def first_frame(report, branch):
    branches = {row["image"] + "/" + row["property"]: row["sprites"]
                for row in report["branches"]}
    names = branches.get(branch)
    if not names:
        raise ValueError("Missing scenery branch: " + branch)
    # An unnumbered tile/background is already a frame; objects contain frame 0.
    name = branch if branch in names else branch + "/0"
    if name not in names:
        raise ValueError("Missing initial animation frame: " + branch)
    return name, report["sprites"][name]


def scene_items(raw, report):
    sections = raw["render_sections"]
    items = []
    for layer in range(8):
        section = sections[str(layer)]
        for kind in ("tile", "obj"):
            for number, row in section[kind].items():
                if kind == "tile":
                    branch = f"Map/Tile/{section['info']['tS']}.img/{row['u']}/{row['no']}"
                else:
                    branch = f"Map/Obj/{row['oS']}.img/{row['l0']}/{row['l1']}/{row['l2']}"
                name, sprite = first_frame(report, branch)
                z = (sprite["z"] or 0) if kind == "tile" else row["z"]
                if type(z) is not int:
                    raise ValueError("Unsupported scenery depth")
                items.append({"placement": f"{layer}/{kind}/{number}", "kind": kind,
                              "layer": layer, "z": z, "number": int(number),
                              "x": row["x"], "y": row["y"], "flip": bool(row.get("f", 0)),
                              "sprite": name})
    return sorted(items, key=lambda item: (item["layer"], item["z"],
                                          item["kind"] == "tile", item["number"]))


def place(canvas, sprite, metadata, point, bounds, flip=False, opacity=255):
    ox, oy = metadata["origin"]
    if flip:
        sprite, ox = sprite[:, ::-1], sprite.shape[1] - ox
    x, y = round(point[0] - ox - bounds[0]), round(point[1] - oy - bounds[1])
    composite(canvas, sprite, x, y, opacity=opacity)


def render(raw_path, pictures, receipt_path, output):
    raw_path, pictures, receipt_path, output = [p.resolve() for p in
                                               (raw_path, pictures, receipt_path, output)]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output)
                              for p in (pictures, raw_path.parent, receipt_path.parent / "assets")):
        raise ValueError("Use a new output folder outside inputs")
    raw, report, receipt = load(raw_path), load(pictures / "pictures.json"), load(receipt_path)
    if raw.get("map_id") != "000000060" or report.get("map_id") != "000000060":
        raise ValueError("Southperry only")
    output = check_output(output, pictures, [Path(row["original"]) for row in receipt["files"]])
    for row in receipt["files"]:
        path = Path(row["copy"])
        if digest(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ValueError("Copied artwork changed")
    info = raw["raw"]["info"]
    bounds = [info[key] for key in ("VRLeft", "VRTop", "VRRight", "VRBottom")]
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    if width <= 0 or height <= 0 or width * height > 30000000:
        raise ValueError("Invalid map bounds")
    sprites, checks = {}, {}
    for name, metadata in report["sprites"].items():
        path = safe_file(pictures, metadata["file"])
        packed = safe_file(pictures, metadata["compressed"])
        if packed.stem != path.stem + ".compressed":
            raise ValueError("Mismatched compressed picture")
        sprites[name], checks[name] = decode_picture(pictures, metadata)
        if sprites[name].shape != (metadata["height"], metadata["width"], 4):
            raise ValueError("Changed picture dimensions")
    items = scene_items(raw, report)
    foreground = np.zeros((height, width, 4), dtype="uint8")
    for item in items:
        metadata = report["sprites"][item["sprite"]]
        place(foreground, sprites[item["sprite"]], metadata, (item["x"], item["y"]),
              bounds, item["flip"])
    overview = np.zeros_like(foreground)
    background_rows = []
    backgrounds = sorted(raw["render_sections"]["back"].items(), key=lambda pair: int(pair[0]))
    for number, row in backgrounds:
        if row["front"] or row["ani"] or row["type"] not in (1, 3, 4):
            raise ValueError("Unsupported background placement")
        name, metadata = first_frame(report, f"Map/Back/{row['bS']}.img/back/{row['no']}")
        sprite = sprites[name]
        step_x, step_y = row["cx"] or metadata["width"], row["cy"] or metadata["height"]
        # Static world-zero snapshot only: parallax/scroll phase cannot be represented
        # by one whole-world picture. The transparent foreground is exported separately.
        x0 = row["x"] - metadata["origin"][0]
        y0 = row["y"] - metadata["origin"][1]
        xs = range(math.floor((bounds[0] - x0 - metadata["width"]) / step_x),
                   math.ceil((bounds[2] - x0) / step_x) + 1)
        ys = range(math.floor((bounds[1] - y0 - metadata["height"]) / step_y),
                   math.ceil((bounds[3] - y0) / step_y) + 1) if row["type"] == 3 else (0,)
        for ix in xs:
            for iy in ys:
                place(overview, sprite, metadata, (row["x"] + ix * step_x, row["y"] + iy * step_y),
                      bounds, bool(row["f"]), row["a"])
        background_rows.append({"placement": "back/" + number, "sprite": name,
                                "type": row["type"], "rx": row["rx"], "ry": row["ry"]})
    composite(overview, foreground, 0, 0)
    output.mkdir(parents=True)
    for name, image in (("foreground.png", foreground), ("overview.png", overview)):
        if not cv2.imwrite(str(output / name), image):
            raise OSError("Cannot write preview")
    thumbnail = cv2.resize(overview, (1417, round(height * 1417 / width)),
                           interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(output / "overview-small.png"), thumbnail)
    (output / "placements.json").write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    summary = {"schema": 1, "map_id": 60, "dimensions": [width, height], "world_bounds": bounds,
               "placement_counts": {"tile": sum(i["kind"] == "tile" for i in items),
                                    "object": sum(i["kind"] == "obj" for i in items),
                                    "background": len(background_rows)},
               "branches": len(report["branches"]), "decoded_pictures": len(sprites),
               "resolved_links": len(report["links"]), "unresolved_links": [],
               "copied_archives_opened": report["opened_archives"],
               "independent_pixel_checks": checks, "backgrounds": background_rows,
               "source_pins": {"raw": digest(raw_path),
                               "pictures": digest(pictures / "pictures.json"),
                               "receipt": digest(receipt_path),
                               "renderer": digest(Path(__file__))},
               "output_pins": {name: digest(output / name) for name in
                               ("foreground.png", "overview.png", "overview-small.png",
                                "placements.json")},
               "input_sent": False, "native_acceptance": False,
               "limitations": ["Initial animation frames only; no live animation or timing.",
                               "Static backgrounds; no live parallax/scroll.",
                               "No actors, portals, client-drawn ropes, HUD or player.",
                               "Diagnostic depth assembly; no native certification.",
                               "No actor position, collision, route or client-identity proof."]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("raw", "pictures", "receipt", "output"):
        parser.add_argument("--" + argument, required=True, type=Path)
    args = parser.parse_args()
    result = render(args.raw, args.pictures, args.receipt, args.output)
    print({key: result[key] for key in ("dimensions", "placement_counts", "decoded_pictures",
                                       "resolved_links", "unresolved_links")})


if __name__ == "__main__":
    main()
