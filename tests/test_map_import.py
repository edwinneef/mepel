import base64
import copy
import json

import cv2
import numpy as np
import pytest
from test_public_map import public_picture, source

from maplebot.map_import import candidates, engine_running, import_map


def test_candidates_prefer_exact_titles(tmp_path):
    catalog = tmp_path / "maps.json"
    catalog.write_text(json.dumps([{"id": 1, "name": "Over the Wall"},
                                   {"id": 2, "name": "Over the Wall II"},
                                   {"id": 3, "name": "Pig Park"}]))
    assert candidates(catalog, "Over the Wall") == [1]
    assert candidates(catalog, "over the") == [1, 2]
    assert candidates(tmp_path / "missing.json", "x") == []


def test_engine_running_is_false_on_a_closed_port():
    assert engine_running(1) is False


class Store:
    def __init__(self, directory, profile, frame):
        self.directory, self.profile, self.body, self.saved = directory, profile, frame, None

    def list(self):
        return {"areas": [{"id": self.profile["id"], "name": self.profile["name"], "revision": 3}]}

    def load(self, area_id):
        assert area_id == self.profile["id"]
        return {"profile": copy.deepcopy(self.profile)}

    def frame(self, image_id):
        return self.body

    def save(self, value):
        self.saved = value
        return {"profile": {**value, "revision": value["revision"] + 1}}


def store(tmp_path):
    image = public_picture()
    reference = np.zeros((120, 160, 3), np.uint8)
    reference[30:65, 25:85] = image[5:, :, :3]
    view = {"id": "view", "name": "View", "width": 160, "height": 120,
            "origin": {"x": 0, "y": 0}, "scale": 1, "image": "b" * 64,
            "minimap": {"canvas": {"x": 20, "y": 25, "width": 80, "height": 50}, "dot": None}}
    profile = {"schema_version": 2, "id": "a" * 32, "revision": 3, "name": "Test",
               "boundary": {"x": 0, "y": 0, "width": 10, "height": 10}, "views": [view],
               "zones": [], "platforms": [], "ropes": [], "links": [],
               "minimap_calibration": {
                   "view_id": "view", "view_image": "b" * 64, "pairs": 10, "captured_at": 1.0,
                   "transform": {"scale_x": 16, "offset_x": 0, "scale_y": 16, "offset_y": 0},
                   "residual_px": {a: {"p50": 0, "p95": 0, "max": 0} for a in ("x", "y")}}}
    minimap = {"canvas": base64.b64encode(cv2.imencode(".png", image)[1]).decode(),
               "centerX": 0, "centerY": 0, "magnification": 4}
    body = json.dumps(source(minimap)).encode()
    return Store(tmp_path, profile, cv2.imencode(".png", reference)[1].tobytes()), body


def test_import_by_name_saves_api_geometry_and_dry_run_does_not(tmp_path):
    fake, body = store(tmp_path)
    catalog = tmp_path / "maps.json"
    catalog.write_text(json.dumps([{"id": 7, "name": "Test"}]))
    preview = import_map(fake, "Test", catalog, dry_run=True, fetch=lambda url: body)
    assert fake.saved is None and preview["map_id"] == 7 and "Floor" in preview["names"]
    result = import_map(fake, "a" * 32, catalog, fetch=lambda url: pytest.fail("cached"))
    assert result["revision"] == 4 and fake.saved["public_map"]["id"] == 7
    assert fake.saved["links"] == []


def test_import_needs_a_map_id_when_no_title_matches(tmp_path):
    fake, body = store(tmp_path)
    with pytest.raises(ValueError, match="--map-id"):
        import_map(fake, "Test", tmp_path / "missing.json", fetch=lambda url: body)
    assert import_map(fake, "Test", tmp_path / "missing.json", map_id=7, dry_run=True,
                      fetch=lambda url: body)["map_id"] == 7
