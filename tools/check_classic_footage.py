"""Compare copied recorded frames to copied-asset textures; no bot imports."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from export_classic_assets import check_output, digest, load_json, safe_path, write_json


def read(path):
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Cannot read {path}")
    return image


def errors(observed, expected, mask):
    delta = np.max(np.abs(observed.astype(int) - expected.astype(int)), axis=2)[mask]
    return {"pixels": int(delta.size), "exact_fraction": float(np.mean(delta == 0)),
            "within_one_fraction": float(np.mean(delta <= 1)),
            "max_channel_error": int(delta.max()),
            "median_channel_error": float(np.median(delta))}


def composite(texture, background):
    alpha = texture[:, :, 3:4].astype(float) / 255
    return np.rint(texture[:, :, :3] * alpha + background * (1 - alpha)).astype("uint8")


def check(bundle, reference, output):
    started = time.perf_counter()
    bundle, reference = safe_path(bundle), safe_path(reference)
    manifest = load_json(bundle / "manifest.json")
    if manifest.get("map_id") != "000000060":
        raise ValueError("Changed bundle identity")
    for name, expected in manifest["outputs"].items():
        path = safe_path(bundle / name)
        if path.parent != bundle or digest(path) != expected:
            raise ValueError("Bundle output hash mismatch")
    output = check_output(output, reference, [])
    if output.is_relative_to(bundle):
        raise ValueError("Report must stay outside the bundle")
    pins = load_json(reference / "provenance.json")
    for name, expected in pins.items():
        path = safe_path(reference / name)
        if not path.is_relative_to(reference) or digest(path) != expected:
            raise ValueError("Reference provenance mismatch")
    receipt_path = reference / "footage/receipt.json"
    if "footage/receipt.json" not in pins or "previous-minimap.png" not in pins:
        raise ValueError("Missing reference provenance")
    receipt = json.loads(receipt_path.read_text())
    current = read(bundle / "minimap-canvas.png")
    cached = read(reference / "previous-minimap.png")
    marker = read(bundle / "player-marker.png")
    assert current.shape == cached.shape == (138, 295, 4)
    assert marker.shape == (12, 12, 4)
    # Fixed source patch, chosen before scoring; opaque pixels avoid alpha ambiguity.
    patch = current[:, 10:195, :3]
    opaque = current[:, 10:195, 3] == 255
    common = opaque & (cached[:, 10:195, 3] == 255)
    landmarks = [("raised_platform", 63, 85, 65, 9),
                 ("lighthouse", 146, 79, 23, 35),
                 ("stone_ground", 115, 125, 70, 13)]
    frames = []
    for entry in receipt:
        path = safe_path(reference / "footage" / Path(entry["copy"]).name)
        assert path.is_relative_to(reference / "footage")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        frame = read(path)
        assert frame.shape == (768, 1366, 3)
        # Manually inspected UI neighborhood; do not consume recorded alignments,
        # calibration, world coordinates, marker coordinates or production code.
        search = frame[65:220, :225]
        scores = cv2.matchTemplate(search, patch, cv2.TM_SQDIFF,
                                   mask=opaque.astype("uint8") * 255)
        _, _, location, _ = cv2.minMaxLoc(scores)
        x, y = location[0] - 10, location[1] + 65
        assert (x, y) == (6, 72)
        observed = frame[y:y + 138, x:x + 210]
        current_score = errors(observed[:, 10:195], patch, common)
        cached_score = errors(observed[:, 10:195], cached[:, 10:195, :3], common)
        shifted = {}
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            shifted[f"{dx},{dy}"] = errors(
                frame[y + dy:y + dy + 138, x + 10 + dx:x + 195 + dx], patch, common)
        landmark_scores = {}
        for name, lx, ly, width, height in landmarks:
            source = current[ly:ly + height, lx:lx + width]
            landmark_scores[name] = errors(
                observed[ly:ly + height, lx:lx + width], source[:, :, :3],
                source[:, :, 3] == 255)
        # Background is observed in the transparent upper-left of the canvas.
        predicted = composite(current[:, :210], observed[0, 0])
        composition_score = errors(observed, predicted, np.ones((138, 210), bool))
        delta = np.max(np.abs(observed.astype(int) - predicted.astype(int)), axis=2)
        _, _, stats, _ = cv2.connectedComponentsWithStats((delta > 2).astype("uint8"), 8)
        clusters = stats[1:][stats[1:, 4] > 3].tolist()
        marker_mask = marker[:, :, 3] == 255
        marker_scores = cv2.matchTemplate(observed, marker[:, :, :3], cv2.TM_SQDIFF,
                                         mask=marker_mask.astype("uint8") * 255)
        _, _, (mx, my), _ = cv2.minMaxLoc(marker_scores)
        marker_score = errors(observed[my:my + 12, mx:mx + 12],
                              marker[:, :, :3], marker_mask)
        underlying = predicted[my:my + 12, mx:mx + 12]
        full_marker_score = errors(observed[my:my + 12, mx:mx + 12],
                                   composite(marker, underlying), np.ones((12, 12), bool))
        result = {"file": path.name, "recording": entry["recording"],
                  "sha256": entry["sha256"], "canvas_screen_xy": [x, y],
                  "scale": 1, "current_common_opaque": current_score,
                  "cached_common_opaque": cached_score,
                  "one_pixel_shift_controls": shifted, "landmarks": landmark_scores,
                  "whole_visible_composite": composition_score,
                  "residual_clusters_xywh_area": clusters,
                  "marker_screen_top_left": [x + mx, y + my],
                  "marker_opaque": marker_score, "marker_composite": full_marker_score}
        frames.append(result)
        assert current_score["exact_fraction"] > .90
        assert cached_score["exact_fraction"] < .40
        assert marker_score["pixels"] == 52 and marker_score["exact_fraction"] == 1
        assert all(s["exact_fraction"] < current_score["exact_fraction"] for s in shifted.values())
    landmark_exact_counts = {
        name: sum(f["landmarks"][name]["exact_fraction"] == 1 for f in frames)
        for name, *_ in landmarks}
    assert all(count > 0 for count in landmark_exact_counts.values())
    unobscured_marker_frames = [f["file"] for f in frames
                               if f["marker_composite"]["within_one_fraction"] == 1]
    assert unobscured_marker_frames
    report = {"input_sent": False, "native_acceptance": False,
              "fixture_admission_ready": False, "exporter_built": True,
              "scope": "Offline comparison of copied existing screenshots; no game access",
              "archive_directory_parser_independent": False,
              "pixel_decoder_independently_checked_previously": True,
              "visible_raster_supported_by_recorded_game_pixels": True,
              "whole_asset_verified_against_footage": False,
              "visible_source_rectangle": [0, 0, 210, 138],
              "unseen_right_columns": 85,
              "screen_placement_is_recorded_UI_only": True,
              "coordinate_contact_build_identity_verified": False,
              "comparison_mask": ("Same mutually opaque pixels for current/cache; "
                                  "no residual-derived exclusion"),
              "compositing": ("Rounded straight alpha over sampled dark-blue background; "
                              "diagnostic model"),
              "recordings": len(set(e["recording"] for e in receipt)),
              "landmark_exact_frame_counts": landmark_exact_counts,
              "marker_full_composite_within_one_frames": unobscured_marker_frames,
              "visual_residual_interpretation": (
                  "Clusters coincide with portal, NPC and character markers. Two lighthouse "
                  "samples have 12 opaque pixels covered by another character marker. "
                  "Overlapping markers prevent full-sprite compositing checks in eight frames; "
                  "no residual-derived mask was used."),
              "frames": frames, "runtime_seconds": round(time.perf_counter() - started, 3)}
    report["provenance"] = {"reference_root": str(reference), "reference_pins": pins,
                            "bundle_manifest_sha256": digest(bundle / "manifest.json")}
    if len(frames) != 9 or report["recordings"] != 3:
        raise ValueError("Expected nine pinned frames from three recordings")
    write_json(output, report)
    print(json.dumps({"frames": len(frames), "recordings": report["recordings"],
                      "current_exact_range": [
                          min(f["current_common_opaque"]["exact_fraction"] for f in frames),
                          max(f["current_common_opaque"]["exact_fraction"] for f in frames)],
                      "cached_exact_range": [
                          min(f["cached_common_opaque"]["exact_fraction"] for f in frames),
                          max(f["cached_common_opaque"]["exact_fraction"] for f in frames)],
                      "marker_opaque_exact_all": True,
                      "runtime_seconds": report["runtime_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check(args.bundle, args.reference_root, args.output)
