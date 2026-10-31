import copy

import numpy as np
import pytest
from test_map_import import store

from maplebot.map_import import import_map
from maplebot.profiles import validate_profile


def test_automatic_import_needs_no_walk_samples_and_preserves_collision_ends(tmp_path):
    saved, body = store(tmp_path)
    del saved.profile["minimap_calibration"]
    import_map(saved, "Test", tmp_path / "catalog", map_id=7, fetch=lambda _: body)
    profile, _ = validate_profile(saved.saved)
    assert "minimap_calibration" not in profile
    assert profile["public_map"]["world"] == {"x": [1, 0], "y": [1, 0]}
    assert profile["automatic_alignment"]["uncertainty_px"] == 16
    floor = next(p for p in profile["platforms"] if p["id"] == "fh1")
    assert floor["start"]["x"] == 0 and floor["end"]["x"] == 600
    for edit in ("source", "reference", "uncertainty", "scale"):
        bad = copy.deepcopy(profile)
        if edit == "source":
            bad["public_map"]["sha256"] = "c" * 64
        elif edit == "reference":
            bad["views"][0]["image"] = "c" * 64
        elif edit == "uncertainty":
            bad["automatic_alignment"]["uncertainty_px"] = 0
        else:
            bad["automatic_alignment"]["transform"]["scale_x"] = 15.82
        with pytest.raises(ValueError):
            validate_profile(bad)


def test_dry_run_and_wrong_map_do_not_change_profile(tmp_path):
    saved, body = store(tmp_path)
    original = copy.deepcopy(saved.profile)
    import_map(saved, "Test", tmp_path / "catalog", map_id=7, fetch=lambda _: body, dry_run=True)
    assert saved.saved is None and saved.profile == original
    wrong = np.random.default_rng(40).integers(0, 255, (120, 160, 3), dtype=np.uint8)
    import cv2

    saved.body = cv2.imencode(".png", wrong)[1].tobytes()
    with pytest.raises(ValueError, match="minimap|terrain"):
        import_map(saved, "Test", tmp_path / "catalog", map_id=7)
    assert saved.saved is None
