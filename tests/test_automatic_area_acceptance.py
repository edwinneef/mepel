"""Local saved-frame acceptance; never attaches to the engine or sends input."""

import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from maplebot.automatic_area import create_area
from maplebot.map_filter import MapFilter
from maplebot.profiles import AreaStore

ROOT = Path(__file__).resolve().parents[1] / "data"


def test_recorded_frame_recognizes_aligns_saves_and_preserves(tmp_path):
    original = ROOT / "areas"
    profile = json.loads((original / "362bc0749cdc41efb045ecc06b483633.json").read_text())
    image = cv2.imread(str(original / "frames" / (profile["views"][0]["image"] + ".png")))
    assert image is not None
    (tmp_path / "catalog").mkdir()
    shutil.copy2(ROOT / "templates/catalog/maps.json", tmp_path / "catalog/maps.json")
    store = AreaStore(tmp_path / "areas")
    (store.directory / "public").mkdir(parents=True)
    shutil.copy2(original / "public/103030200.json", store.directory / "public/103030200.json")
    router = MapFilter(tmp_path, [])
    try:
        assert create_area(store, image, router) is None
        router.select(image)
        assert router.pending is not None
        text = router.pending.result(timeout=15)
        router.select(image)
        assert router.map_id == 103030200
        selected = next(p for p in router.profiles if p["id"] == router.map_id)
        duplicate = {**selected, "id": 999999999}
        router.profiles.append(duplicate)
        router.match(text)
        assert router.map_id is None
        assert create_area(store, image, router) is None
        assert store.list()["areas"] == []
        router.profiles.remove(duplicate)
        router.match(text)
        # Real alignment must reject a frame without matching terrain, without writes.
        try:
            create_area(store, np.zeros_like(image), router)
        except ValueError:
            pass
        assert store.list()["areas"] == []
        assert not list(store.directory.rglob("*.png"))
        area_id = create_area(store, image, router)
        assert area_id is not None
        loaded = store.load(area_id)["profile"]
        assert loaded["public_map"]["id"] == 103030200
        assert loaded["automatic_alignment"]["view_image"] == loaded["views"][0]["image"]
        assert loaded["platforms"]
        assert store.frame(loaded["views"][0]["image"]) is not None
        before = {p.relative_to(store.directory): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in store.directory.rglob("*") if p.is_file()}
        assert create_area(store, image, router) is None
        after = {p.relative_to(store.directory): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in store.directory.rglob("*") if p.is_file()}
        assert before == after
        assert len(store.list()["areas"]) == 1
        router.match("unreadable title")
        assert router.map_id is None
        assert create_area(store, image, router) is None
    finally:
        router.close()
