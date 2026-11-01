"""Compare three copied inline scenery assets with nine existing copied screenshots."""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

from tools.export_classic_assets import (
    check_output,
    decode_canvas,
    digest,
    load_json,
    safe_path,
    write_json,
)


def agreement(observed, template, mask):
    delta = np.max(np.abs(observed.astype("int16") - template.astype("int16")), axis=2)[mask]
    if not delta.size:
        raise ValueError("Empty comparison mask")
    return {"pixels": int(delta.size), "exact_fraction": float(np.mean(delta == 0)),
            "within_one_fraction": float(np.mean(delta <= 1)),
            "median_channel_error": float(np.median(delta)),
            "maximum_channel_error": int(delta.max())}


def match(frame, sprite):
    opaque = sprite[:, :, 3] == 255
    scores = cv2.matchTemplate(frame, sprite[:, :, :3], cv2.TM_SQDIFF_NORMED,
                               mask=opaque.astype("uint8") * 255)
    scores[~np.isfinite(scores)] = np.inf
    _, _, (x, y), _ = cv2.minMaxLoc(scores)
    height, width = sprite.shape[:2]
    observed = frame[y:y + height, x:x + width]
    score = agreement(observed, sprite[:, :, :3], opaque)
    controls = {}
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        if x + dx < 0 or y + dy < 0 or x + dx + width > frame.shape[1] \
                or y + dy + height > frame.shape[0]:
            raise ValueError("Displacement control lies outside screenshot")
        controls[f"{dx},{dy}"] = agreement(
            frame[y + dy:y + dy + height, x + dx:x + dx + width], sprite[:, :, :3], opaque)
    return {"top_left": [x, y], "scale": 1, "opaque": score,
            "one_pixel_controls": controls,
            "all_controls_worse": all(v["exact_fraction"] < score["exact_fraction"]
                                      for v in controls.values())}, observed


def compare(assets, footage, bundle, output):
    started = time.perf_counter()
    assets, footage, bundle = (safe_path(p) for p in (assets, footage, bundle))
    output = check_output(output, assets, [])
    if output.is_relative_to(footage) or output.is_relative_to(bundle):
        raise ValueError("Output must stay outside input roots")
    pins = load_json(assets / "provenance.json")
    for name, expected in pins["outputs"].items():
        path = safe_path(assets / name)
        if path.parent != assets or digest(path) != expected:
            raise ValueError("Extracted asset hash mismatch")
    metadata = load_json(assets / "assets.json")
    if {a["name"] for a in metadata} != {"house", "house-decoration", "platform-edge"}:
        raise ValueError("Expected the three preselected source assets")
    receipt_path = footage / "receipt.json"
    receipt = load_json(receipt_path)
    if len(receipt) != 9 or len({r["recording"] for r in receipt}) != 3:
        raise ValueError("Expected nine recorded frames from three sessions")
    manifest = load_json(bundle / "manifest.json")
    raw_path = bundle / "raw.json"
    if digest(raw_path) != manifest["outputs"]["raw.json"]:
        raise ValueError("Map placement hash mismatch")
    raw = load_json(raw_path)
    if raw["map_id"] != "000000060":
        raise ValueError("Southperry only")
    world_top_left = {}
    for name, branch in (("house", "basic"), ("house-decoration", "deco")):
        candidates = [obj for layer, section in raw["render_sections"].items() if layer.isdigit()
                      for obj in section["obj"].values() if obj.get("oS") == "obj_housePT"
                      and obj.get("l0") == "house0" and obj.get("l1") == branch
                      and str(obj.get("l2")) == "0"]
        if len(candidates) != 1 or candidates[0]["f"] != 0:
            raise ValueError("Missing/ambiguous/unexpected mirrored placement")
        meta = next(a for a in metadata if a["name"] == name)
        world_top_left[name] = [candidates[0][key] - meta["origin"][axis]
                                for axis, key in enumerate(("x", "y"))]
    frames = []
    for row in receipt:
        path = safe_path(footage / Path(row["copy"]).name)
        if path.parent != footage or digest(path) != row["sha256"]:
            raise ValueError("Recorded-frame hash mismatch")
        frame = cv2.imread(str(path))
        if frame is None or frame.shape != (768, 1366, 3):
            raise ValueError("Unexpected recorded frame dimensions")
        frames.append((row, frame))
    output.mkdir()
    results, decoding = {}, {}
    for meta in metadata:
        name = meta["name"]
        decoding[name] = decode_canvas(assets, name, meta)
        sprite = cv2.imread(str(assets / (name + ".png")), cv2.IMREAD_UNCHANGED)
        per_frame = []
        for i, (row, frame) in enumerate(frames):
            result, crop = match(frame, sprite)
            result.update({"frame": Path(row["copy"]).name, "sha256": row["sha256"],
                           "recording": row["recording"]})
            if name in world_top_left:
                result["screen_minus_map_translation"] = [a - b for a, b in
                    zip(result["top_left"], world_top_left[name], strict=True)]
            per_frame.append(result)
            if i == 0:
                cv2.imwrite(str(output / (name + "-recorded.png")), crop)
                opaque = sprite[:, :, 3] == 255
                delta = np.max(np.abs(crop.astype("int16") - sprite[:, :, :3]), axis=2)
                residual = np.zeros_like(crop)
                residual[~opaque] = [110, 110, 110]
                residual[opaque & (delta > 0)] = [30, 30, 235]
                cv2.imwrite(str(output / (name + "-differences.png")), residual)
        fractions = [r["opaque"]["exact_fraction"] for r in per_frame]
        results[name] = {"exact_range": [min(fractions), max(fractions)], "frames": per_frame,
                         "repeated_pattern": name == "platform-edge"}
    offsets = [np.subtract(a["screen_minus_map_translation"], b["screen_minus_map_translation"])
               .tolist() for a, b in zip(results["house"]["frames"],
                                         results["house-decoration"]["frames"], strict=True)]
    report = {"scope": "Three preselected scenery pieces; nine existing screenshots",
              "mask": "All source pixels with alpha=255; no residual-based exclusions",
              "search": "Whole screenshot; fixed 1:1 scale; no logged positions/calibration",
              "assets": results, "independent_pixel_decoding": decoding,
              "house_decoration_translation_disagreement": offsets,
              "source_world_top_left": world_top_left,
              "source_assets_provenance_sha256": digest(assets / "provenance.json"),
              "footage_receipt_sha256": digest(receipt_path), "raw_map_sha256": digest(raw_path),
              "native_build_verified": False, "native_position_accuracy_verified": False,
              "native_acceptance": False, "input_sent": False,
              "runtime_seconds": round(time.perf_counter() - started, 3)}
    write_json(output / "comparison.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "footage", "bundle", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.assets, args.footage, args.bundle, args.output)
    print({name: row["exact_range"] for name, row in report["assets"].items()})
