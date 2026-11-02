from types import SimpleNamespace

import numpy as np
import pytest

from maplebot.automatic_area import create_area
from maplebot.profiles import AreaStore


def recognition(map_id=1):
    return SimpleNamespace(map_id=map_id, title="Test", error=None,
                           source_error=None, held=False)


def test_unknown_and_uncached_maps_write_nothing(tmp_path):
    store = AreaStore(tmp_path)
    assert create_area(store, None, recognition(None)) is None
    assert create_area(store, None, recognition()) is None
    assert not list(tmp_path.rglob("*.png"))
    assert store.list()["areas"] == []


def test_alignment_failure_does_not_save_profile(tmp_path, monkeypatch):
    store = AreaStore(tmp_path)
    (tmp_path / "public").mkdir()
    (tmp_path / "public/1.json").write_text("{}")
    monkeypatch.setattr("maplebot.automatic_area.cached", lambda *a: ({}, "digest"))
    monkeypatch.setattr(store, "capture_view", lambda image: {})

    def refuse(*args, **kwargs):
        raise ValueError("Ambiguous alignment")

    monkeypatch.setattr("maplebot.automatic_area.build_area", refuse)
    with pytest.raises(ValueError, match="Ambiguous"):
        create_area(store, np.zeros((100, 100, 3), dtype=np.uint8), recognition())
    assert store.list()["areas"] == []


def test_confident_frame_saved_once_and_existing_area_preserved(tmp_path, monkeypatch):
    from test_map_import import store as fixture

    store, _ = fixture(tmp_path)
    (tmp_path / "public").mkdir()
    (tmp_path / "public/1.json").write_text("{}")
    monkeypatch.setattr(store, "capture_view",
                        lambda image: store.profile["views"][0], raising=False)
    monkeypatch.setattr("maplebot.automatic_area.cached", lambda *a: ({}, "digest"))
    candidate = {**store.profile, "public_map": {"id": 1}, "automatic_alignment": {}}
    monkeypatch.setattr("maplebot.automatic_area.build_area", lambda *a, **kw: candidate)
    import threading

    store.lock = threading.RLock()
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    assert create_area(store, image, recognition()) == candidate["id"]
    saved = store.saved
    store.profile = candidate
    assert create_area(store, None, recognition()) is None
    assert store.saved is saved


