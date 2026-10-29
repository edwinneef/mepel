import base64
import hashlib
import json

import cv2
import numpy as np
import pytest

from maplebot.profiles import validate_profile
from maplebot.public_map import (
    MARKER_BIAS,
    build_area,
    cached,
    identify,
    layout,
    locate,
    match_score,
    picture_offset,
    world_transform,
)


def public_picture():
    rng = np.random.default_rng(3)
    image = np.zeros((40, 60, 4), np.uint8)
    image[..., :3] = rng.integers(40, 255, (40, 60, 3))
    image[..., 3] = 255
    image[:5, :, 3] = 0  # transparent top rows are ignored by the match
    return image


def test_picture_offset_finds_the_picture_even_when_it_overhangs():
    image = public_picture()
    captured = np.zeros((45, 80, 3), np.uint8)
    captured[:37, 12:72] = image[3:, :, :3]  # placed at (12, -3): top rows cut off
    assert picture_offset(captured, image) == pytest.approx((12, -3), abs=.25)


def clipped_picture():
    image = np.random.default_rng(41).integers(20, 240, (80, 300, 4), dtype=np.uint8)
    image[..., 3] = 255
    return image, image[20:60, 110:240, :3].copy()


def test_client_clipped_public_picture_registers_without_resizing():
    image, captured = clipped_picture()
    assert picture_offset(captured, image) == (-110, -20)
    assert match_score(captured, image) == 0


def test_clipped_wrong_map_has_no_registration_or_identity_score():
    image, captured = clipped_picture()
    captured = np.random.default_rng(81).integers(0, 255, captured.shape, dtype=np.uint8)
    with pytest.raises(ValueError, match="Clipped minimap"):
        picture_offset(captured, image)
    assert match_score(captured, image) == float("inf")


def test_clipped_repeated_terrain_is_ambiguous():
    patch = np.random.default_rng(4).integers(20, 240, (14, 14, 4), dtype=np.uint8)
    patch[..., 3] = 255
    image = np.tile(patch, (6, 22, 1))
    captured = image[14:70, 112:252, :3].copy()
    with pytest.raises(ValueError, match="unique public terrain"):
        picture_offset(captured, image)


def test_one_local_clipped_landmark_cannot_place_a_map():
    image, _ = clipped_picture()
    image[..., 3] = 0
    image[28:56, 140:168, 3] = 255
    captured = image[20:60, 110:240, :3].copy()
    with pytest.raises(ValueError, match="three separate"):
        picture_offset(captured, image)


def test_conflicting_clipped_landmark_offsets_are_rejected():
    image, captured = clipped_picture()
    captured[:, 65:] = image[25:65, 175:240, :3]
    with pytest.raises(ValueError, match="landmarks disagree"):
        picture_offset(captured, image)


def test_world_transform_follows_minimap_math():
    walk = {"scale_x": 16, "offset_x": 10, "scale_y": 15, "offset_y": -5}
    minimap = {"centerX": 32, "centerY": 160, "magnification": 4}
    fit = world_transform(walk, minimap, (2, -1))
    assert fit["x"] == pytest.approx((1, 16 * (2 + 2 + MARKER_BIAS[0]) + 10))
    assert fit["y"] == pytest.approx((15 / 16, 15 * (10 - 1 + MARKER_BIAS[1]) - 5))


def test_locate_reads_the_view_canvas():
    image = public_picture()
    reference = np.zeros((120, 160, 3), np.uint8)
    reference[30:65, 25:85] = image[5:, :, :3]  # picture at (5, 0) in a canvas at (20, 25)
    minimap = {"canvas": base64.b64encode(cv2.imencode(".png", image)[1]).decode(),
               "centerX": 0, "centerY": 0, "magnification": 4}
    walk = {"scale_x": 16, "offset_x": 0, "scale_y": 16, "offset_y": 0}
    fit = locate(reference, {"x": 20, "y": 25, "width": 80, "height": 50}, walk, minimap)
    assert fit["x"][1] == pytest.approx(16 * (5 + MARKER_BIAS[0]), abs=4)
    assert fit["y"][1] == pytest.approx(16 * MARKER_BIAS[1], abs=4)


IDENTITY = {"x": (1.0, 0.0), "y": (1.0, 0.0)}


def source(minimap=None):
    rows = [(1, 0, 300, 400, 400, 0, 2), (2, 300, 600, 400, 460, 1, 0),  # sloped floor
            (3, 600, 600, 460, 300, 0, 0),  # wall, dropped
            (10, 50, 200, 300, 300, 0, 0), (11, 400, 550, 305, 305, 0, 0),  # one level, two sides
            (20, 250, 350, 200, 200, 0, 0), (21, 360, 450, 200, 200, 0, 0)]  # 10 px apart
    footholds = {str(i): {"id": i, "x1": x1, "x2": x2, "y1": y1, "y2": y2, "prev": a, "next": b}
                 for i, x1, x2, y1, y2, a, b in rows}
    return {"id": 7, "name": "Test", "miniMap": minimap or {"magnification": 4},
            "footholds": footholds,
            "ladderRopes": [{"x": 100, "y1": 310, "y2": 390, "isLadder": True},
                            {"x": 590, "y1": 100, "y2": 160, "isLadder": False}],
            "portals": [{"portalName": "sp", "type": 0, "x": 20, "y": 400},
                        {"portalName": "out00", "type": 2, "x": 60, "y": 400}]}


def test_layout_names_places_plainly_and_keeps_api_ids():
    out = layout(source(), IDENTITY, (16, 16))
    names = {p["id"]: p["name"] for p in out["platforms"]}
    assert names == {"fh1": "Floor", "fh10": "Level 1 left", "fh11": "Level 1 right",
                     "fh20": "Level 2 center", "fh21": "Level 2 right"}
    assert [r["name"] for r in out["ropes"]] == ["Ladder to Level 1 left", "Far right rope"]
    assert layout(source(), IDENTITY, (16, 16)) == out  # stable on re-import


def test_layout_pads_ends_snaps_ropes_and_marks_visible_portals():
    out = layout(source(), IDENTITY, (16, 16))
    by = {p["id"]: p for p in out["platforms"]}
    assert by["fh10"]["start"]["x"] == 34 and by["fh10"]["end"]["x"] == 216
    assert by["fh20"]["end"]["x"] == 355 and by["fh21"]["start"]["x"] == 355  # gap halved
    assert by["fh1"]["points"][-2:] == [{"x": 600, "y": 460}, {"x": 616, "y": 460}]
    ladder = out["ropes"][0]
    assert ladder["start"]["y"] == 300 - 8 and ladder["end"]["y"] == 400 + 8
    assert out["zones"] == [{"id": "portal1", "kind": "portal",
                             "rect": {"x": 35, "y": 330, "width": 50, "height": 70}}]
    box = out["boundary"]
    assert box["x"] <= -16 - 40 + 1 and box["y"] + box["height"] >= 460 + 40


def test_cached_fetches_once_and_hashes_exact_bytes(tmp_path):
    body = json.dumps(source()).encode()
    calls = []

    def fetch(url):
        calls.append(url)
        return body

    first = cached(tmp_path, 7, fetch)
    assert cached(tmp_path, 7, fetch) == first and len(calls) == 1
    assert first[1] == hashlib.sha256(body).hexdigest() and calls[0].endswith("/map/7")
    with pytest.raises(ValueError, match="no usable layout"):
        cached(tmp_path, 8, lambda url: json.dumps({"id": 9}).encode())


def test_identify_needs_a_clear_winner():
    image = public_picture()
    other = public_picture()[::-1].copy()
    captured = np.zeros((45, 80, 3), np.uint8)
    captured[:35, 10:70] = image[5:, :, :3]
    encode = {key: {"canvas": base64.b64encode(cv2.imencode(".png", item)[1]).decode()}
              for key, item in ((1, image), (2, other))}
    assert identify(captured, {k: {"miniMap": v} for k, v in encode.items()}) == 1
    with pytest.raises(ValueError, match="Several maps"):
        identify(captured, {1: {"miniMap": encode[1]}, 3: {"miniMap": encode[1]}})


def test_build_area_replaces_geometry_and_records_its_source():
    image = public_picture()
    reference = np.zeros((120, 160, 3), np.uint8)
    reference[30:65, 25:85] = image[5:, :, :3]
    minimap = {"canvas": base64.b64encode(cv2.imencode(".png", image)[1]).decode(),
               "centerX": 0, "centerY": 0, "magnification": 4}
    view = {"id": "view", "name": "View", "width": 160, "height": 120,
            "origin": {"x": 0, "y": 0}, "scale": 1, "image": "b" * 64,
            "minimap": {"canvas": {"x": 20, "y": 25, "width": 80, "height": 50}, "dot": None}}
    profile = {"schema_version": 2, "id": "a" * 32, "revision": 3, "name": "Spot",
               "boundary": {"x": 0, "y": 0, "width": 10, "height": 10}, "views": [view],
               "zones": [], "platforms": [], "ropes": [], "links": [{"id": "old"}],
               "minimap_calibration": {
                   "view_id": "view", "view_image": "b" * 64, "pairs": 10, "captured_at": 1.0,
                   "transform": {"scale_x": 16, "offset_x": 0, "scale_y": 16, "offset_y": 0},
                   "residual_px": {a: {"p50": 0, "p95": 0, "max": 0} for a in ("x", "y")}}}
    area = build_area(profile, reference, source(minimap), "c" * 64)
    saved, _ = validate_profile(area)
    assert saved["links"] == [] and saved["revision"] == 3
    assert saved["public_map"]["id"] == 7 and saved["public_map"]["sha256"] == "c" * 64
    assert saved["public_map"]["world"]["x"][0] == 1
    with pytest.raises(ValueError, match="public map ID"):
        validate_profile({**area, "public_map": {**area["public_map"], "id": "7"}})
