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
