import copy
import json

import numpy as np
import pytest

from maplebot.localization import ViewTransform
from maplebot.profiles import AreaStore, validate_profile


@pytest.fixture
def area(tmp_path):
    store = AreaStore(tmp_path / "areas")
    view = store.capture_view(np.zeros((80, 120, 3), dtype=np.uint8))
    profile = {
        "schema_version": 1, "id": "a" * 32, "name": "Taught spot", "revision": 0,
        "boundary": {"x": 0, "y": 0, "width": 120, "height": 80},
        "views": [view], "zones": [], "ropes": [], "links": [],
        "platforms": [
            {"id": "lower", "start": {"x": 10, "y": 60}, "end": {"x": 110, "y": 60}},
            {"id": "upper", "start": {"x": 10, "y": 20}, "end": {"x": 50, "y": 20}},
        ],
    }
    return store, profile


def test_atomic_area_revisions_back_up_previous_and_reject_stale_writers(area, tmp_path):
    store, profile = area
    untouched = tmp_path / "calibration.json"
    untouched.write_text("keep this")
    saved = store.save(profile)["profile"]
    assert saved["revision"] == 1 and profile["revision"] == 0
    old = (store.directory / f"{profile['id']}.json").read_bytes()
    saved["name"] = "Expanded spot"
    assert store.save(saved)["profile"]["revision"] == 2
    assert list(store.directory.glob("*.bak"))[0].read_bytes() == old
    with pytest.raises(ValueError, match="changed elsewhere"):
        store.save(saved)
    assert store.load(profile["id"])["profile"]["name"] == "Expanded spot"
    assert untouched.read_text() == "keep this"


def test_failed_replace_preserves_last_good_area_and_cleans_own_temporary(area, monkeypatch):
    store, profile = area
    saved = store.save(profile)["profile"]
    path = store.directory / f"{profile['id']}.json"
    previous = path.read_bytes()

    def fail(*args):
        raise OSError("Interrupted write")

    monkeypatch.setattr("maplebot.profiles.os.replace", fail)
    with pytest.raises(OSError, match="Interrupted write"):
        store.save(saved)
    assert path.read_bytes() == previous
    assert not list(store.directory.glob(".area-*"))


def test_corrupt_area_is_reported_and_cannot_be_overwritten(area):
    store, profile = area
    path = store.directory / f"{profile['id']}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text("broken user data")
    with pytest.raises(ValueError, match="unreadable"):
        store.save(profile)
    assert path.read_text() == "broken user data"
    listing = store.list()
    assert listing["areas"] == [] and len(listing["errors"]) == 1


@pytest.mark.parametrize("problem", [
    "version", "boolean_version", "path", "nan", "zero", "outside", "duplicate",
    "diagonal_rope", "dangling", "self", "duplicate_link", "wrong_image_size",
])
def test_invalid_geometry_or_references_never_replace_a_saved_area(area, problem):
    store, profile = area
    saved = store.save(profile)["profile"]
    path = store.directory / f"{profile['id']}.json"
    previous = path.read_bytes()
    candidate = copy.deepcopy(saved)
    if problem == "version":
        candidate["schema_version"] = 99
    elif problem == "boolean_version":
        candidate["schema_version"] = True
    elif problem == "path":
        candidate["id"] = "../calibration"
    elif problem == "nan":
        candidate["boundary"]["width"] = float("nan")
    elif problem == "zero":
        candidate["platforms"][0]["end"] = candidate["platforms"][0]["start"]
    elif problem == "outside":
        candidate["zones"] = [{"id": "hazard", "kind": "portal",
                               "rect": {"x": 115, "y": 10, "width": 20, "height": 20}}]
    elif problem == "duplicate":
        candidate["platforms"][1]["id"] = "lower"
    elif problem == "diagonal_rope":
        candidate["ropes"] = [{"id": "rope", "start": {"x": 20, "y": 20},
                               "end": {"x": 30, "y": 60}}]
    elif problem == "wrong_image_size":
        candidate["views"][0]["width"] += 1
    else:
        link = {"id": "link", "from": "lower", "to": "upper", "kind": "jump"}
        if problem == "dangling":
            link["to"] = "missing"
        elif problem == "self":
            link["to"] = "lower"
        candidate["links"] = [link]
        if problem == "duplicate_link":
            candidate["links"].append({**link, "id": "other"})
    with pytest.raises(ValueError):
        store.save(candidate)
    assert path.read_bytes() == previous


def test_directed_reachability_is_reported_without_claiming_movement_safety(area):
    _, profile = area
    _, warnings = validate_profile(profile)
    assert any("Unreachable" in warning for warning in warnings)
    profile["links"] = [{"id": "back", "from": "upper", "to": "lower", "kind": "drop"}]
    assert any("Unreachable" in w for w in validate_profile(profile)[1])
    profile["links"].append({"id": "forward", "from": "lower", "to": "upper", "kind": "jump"})
    _, warnings = validate_profile(profile)
    assert not any("Unreachable" in warning for warning in warnings)
    assert any("not verified" in warning for warning in warnings)


def test_multiple_views_preserve_manual_scrolling_transforms(area):
    store, profile = area
    second = {**profile["views"][0], "id": "scrolled", "origin": {"x": 300, "y": -50},
              "scale": 2}
    profile["views"].append(second)
    saved = store.save(profile)["profile"]
    assert json.loads(json.dumps(store.load(saved["id"])["profile"])) == saved
    transform = ViewTransform(300, -50, 2)
    assert transform.to_area(80, 100) == (340, 0)
    assert transform.to_view(*transform.to_area(80, 100)) == (80, 100)


@pytest.mark.parametrize("scale", [0, -1, float("inf"), True])
def test_invalid_manual_transforms_are_rejected(scale):
    with pytest.raises(ValueError):
        ViewTransform(0, 0, scale)


def test_capture_stores_minimap_and_save_ignores_client_minimap(tmp_path):
    from test_minimap_reader import view

    store = AreaStore(tmp_path / "areas")
    captured = store.capture_view(view())
    assert captured["minimap"]["dot"] == {"x": 62.5, "y": 22.5}
    profile = {
        "schema_version": 2, "id": "c" * 32, "name": "Minimap spot", "revision": 0,
        "boundary": {"x": 0, "y": 0, "width": 1366, "height": 768},
        "views": [{**captured, "minimap": None}], "zones": [], "platforms": [], "ropes": [],
        "links": [],
    }
    result = store.save(profile)
    assert result["profile"]["views"][0]["minimap"] == captured["minimap"]
    assert not any("No minimap" in warning for warning in result["warnings"])


def test_schema_1_area_upgrades_on_load_and_backs_up_on_save(area):
    store, profile = area
    saved = store.save(profile)["profile"]
    path = store.directory / f"{profile['id']}.json"
    legacy = {**saved, "schema_version": 1,
              "views": [{k: v for k, v in item.items() if k != "minimap"}
                        for item in saved["views"]]}
    path.write_text(json.dumps(legacy))
    loaded = store.load(profile["id"])
    assert loaded["profile"]["schema_version"] == 2
    assert loaded["profile"]["views"][0]["minimap"] is None
    assert any("Upgraded from schema 1" in w for w in loaded["warnings"])
    assert any("No minimap" in w for w in loaded["warnings"])
    assert json.loads(path.read_text())["schema_version"] == 1
    store.save(loaded["profile"])
    assert json.loads(path.read_text())["schema_version"] == 2
    assert json.loads(list(store.directory.glob("*.bak"))[0].read_text()) == legacy


def test_minimap_outside_its_view_is_rejected(area):
    _, profile = area
    profile["schema_version"] = 2
    profile["views"][0]["minimap"] = {
        "canvas": {"x": 100, "y": 0, "width": 50, "height": 20}, "dot": None,
    }
    with pytest.raises(ValueError, match="inside its reference view"):
        validate_profile(profile)


def test_new_view_aligns_to_an_overlapping_view_and_reports_its_evidence(tmp_path):
    scene = np.random.default_rng(3).integers(0, 256, (768, 2400, 3), dtype=np.uint8)
    store = AreaStore(tmp_path / "areas")
    first = store.capture_view(scene[:, :1366].copy())
    first.update(origin={"x": 100, "y": 50}, scale=2)
    moved = scene[:, 300:1666].copy()
    result = store.align_view(moved, [first])
    assert result["aligned"] and result["view_id"] == first["id"] and result["scale"] == 2
    assert result["origin"] == pytest.approx({"x": 250, "y": 50})
    assert result["agree"] >= 3 and result["agree"] <= result["patches"]
    other = np.random.default_rng(4).integers(0, 256, (768, 1366, 3), dtype=np.uint8)
    apart = store.align_view(other, [first])
    assert not apart["aligned"] and apart["origin"] is None
    assert store.align_view(moved, [])["reason"] == "No earlier view to align with"
    with pytest.raises(ValueError, match="Malformed alignment view"):
        store.align_view(moved, [{"image": first["image"]}])
