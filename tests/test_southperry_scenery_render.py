import zlib

import cv2
import numpy as np
import pytest

from tools.render_southperry_scenery import (
    composite,
    decode_picture,
    first_frame,
    place,
    safe_file,
    scene_items,
)


def test_transparent_compositing_clips_and_preserves_alpha():
    canvas = np.zeros((2, 2, 4), dtype="uint8")
    source = np.full((2, 2, 4), (20, 40, 60, 128), dtype="uint8")
    composite(canvas, source, -1, -1)
    assert canvas[0, 0].tolist() == [20, 40, 60, 128]
    assert np.count_nonzero(canvas[1]) == 0
    composite(canvas, np.full((1, 1, 4), (100, 200, 50, 255), dtype="uint8"), 0, 0)
    assert canvas[0, 0].tolist() == [100, 200, 50, 255]


def test_flip_preserves_declared_world_anchor():
    canvas = np.zeros((4, 8, 4), dtype="uint8")
    source = np.array([[[10, 0, 0, 255], [20, 0, 0, 255], [30, 0, 0, 255]]], dtype="uint8")
    place(canvas, source, {"origin": [1, 0]}, (4, 2), [0, 0, 8, 4], flip=True)
    assert canvas[2, 2:5, 0].tolist() == [30, 20, 10]
    assert canvas[2, 5, 3] == 0


def test_frame_zero_is_explicit_and_missing_frames_are_refused():
    branch = "Map/Obj/example.img/a"
    report = {"branches": [{"image": "Map/Obj/example.img", "property": "a",
                             "sprites": [branch + "/1", branch + "/0"]}],
              "sprites": {branch + "/0": {"file": "first.png"}}}
    assert first_frame(report, branch) == (branch + "/0", {"file": "first.png"})
    report["branches"][0]["sprites"].remove(branch + "/0")
    with pytest.raises(ValueError, match="initial animation"):
        first_frame(report, branch)


def test_tile_and_object_depth_share_the_same_layer_order():
    raw = {"render_sections": {str(i): {"tile": {}, "obj": {}, "info": {}} for i in range(8)}}
    raw["render_sections"]["1"] = {
        "info": {"tS": "t"}, "tile": {"0": {"u": "edge", "no": 0, "x": 0, "y": 0}},
        "obj": {"0": {"oS": "o", "l0": "a", "l1": "b", "l2": "c", "z": 1,
                       "x": 0, "y": 0}}}
    rows = [("Map/Tile/t.img", "edge/0", -3), ("Map/Obj/o.img", "a/b/c", 0)]
    report = {"branches": [{"image": image, "property": path,
                             "sprites": [image + "/" + path]} for image, path, _ in rows],
              "sprites": {image + "/" + path: {"z": z} for image, path, z in rows}}
    assert [(i["kind"], i["z"]) for i in scene_items(raw, report)] == [("tile", -3), ("obj", 1)]


def test_independent_decode_detects_png_corruption(tmp_path):
    words = np.array([0xF123, 0x804F], dtype="<u2")
    png = np.array([[[51, 34, 17, 255], [255, 68, 0, 136]]], dtype="uint8")
    metadata = {"file": "pic.png", "compressed": "pic.compressed.bin",
                "format": 1, "width": 2, "height": 1}
    (tmp_path / metadata["compressed"]).write_bytes(zlib.compress(words.tobytes())[:-4])
    cv2.imwrite(str(tmp_path / "pic.png"), png)
    image, evidence = decode_picture(tmp_path, metadata)
    assert np.array_equal(image, png) and evidence["different_pixels"] == 0
    png[0, 0, 0] += 1
    cv2.imwrite(str(tmp_path / "pic.png"), png)
    with pytest.raises(ValueError, match="decoder mismatch"):
        decode_picture(tmp_path, metadata)


def test_picture_paths_cannot_escape_the_copy(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        safe_file(tmp_path, "../outside.png")
