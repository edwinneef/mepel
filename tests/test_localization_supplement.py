import hashlib
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_live_position import AREA, calibrate, observe
from test_live_position import store as _store
from test_minimap_reader import view
from test_runtime import app as _app

from maplebot import localization_supplement as supplement
from maplebot.live_position import LivePosition
from maplebot.runtime import Application

store, app = _store, _app


@pytest.fixture
def position(store, monkeypatch):
    original = LivePosition(store, AREA)
    calibrate(original)
    original.close()
    profile = store.load(AREA)["profile"]
    profile["platforms"][0]["end"]["x"] = 300
    store.save(profile)
    store.save(store.load(AREA)["profile"])
    monkeypatch.setattr(supplement, "AREA", AREA)
    monkeypatch.setattr(supplement, "BASE_SHA256", hashlib.sha256(
        (store.directory / f"{AREA}.json").read_bytes()).hexdigest())
    monkeypatch.setattr(supplement, "PLATFORM", {
        "id": "draft_middle_ledge", "name": "Provisional ledge",
        "start": {"x": 450, "y": 600}, "end": {"x": 550, "y": 600}})
    position = LivePosition(store, AREA, capture_only=True)
    try:
        yield position
    finally:
        position.close()


def step(position, now, *, allow=True, observation=None, image=None):
    image = view(((60, 20),)) if image is None else image
    return position.update(image, position.read_map(image), observation or observe(500), now,
                           allow_supplement=allow)


def test_optin_fallback_preserves_map_primary_tracker_and_restarts_off(position):
    path = position.store.directory / f"{AREA}.json"
    before = path.read_bytes()
    primary = position.tracker
    assert not step(position, 10)["supplement"]["enabled"]
    position.set_supplement(True)
    result = [step(position, 11 + i * .2) for i in range(3)][-1]
    assert result["provisional"] and result["surface_id"] == "draft_middle_ledge"
    assert result["projection"] and result["input_sent"] is False
    assert position.tracker is primary and len(primary.platforms) == 1
    assert path.read_bytes() == before
    assert result["teaching"]["geometry"]["platforms"] == position.profile["platforms"]
    position.set_supplement(False)
    cleared = Application._position_snapshot(SimpleNamespace(position=position), result)
    assert cleared["kind"] == "unknown" and cleared["projection"] is None
    assert step(position, 12)["kind"] == "unknown"
    recovered = LivePosition(position.store, AREA, capture_only=True)
    try:
        assert not recovered.supplement_status()["enabled"]
    finally:
        recovered.close()


def test_primary_saved_platform_always_wins_even_if_supplement_overlaps(position, monkeypatch):
    monkeypatch.setattr(supplement, "PLATFORM", position.profile["platforms"][0])
    position.set_supplement(True)
    image = view(((10, 20),))
    results = [step(position, 10 + i * .2, image=image, observation=observe(100))
               for i in range(3)]
    assert results[-1]["kind"] == "platform" and not results[-1]["provisional"]
    assert results[-1]["surface_id"] == "floor"


@pytest.mark.parametrize("change", ["mode", "source", "profile"])
def test_mode_or_basis_change_disables_until_explicit_reenable(position, change):
    position.set_supplement(True)
    if change == "source":
        path = position.store.directory / f"{AREA}.json"
        path.write_bytes(path.read_bytes() + b"\n")
    if change == "profile":
        position.profile["revision"] = 5
    result = step(position, 10, allow=change != "mode")
    assert not result["supplement"]["enabled"] and not result["provisional"]
    assert not step(position, 11)["supplement"]["enabled"]


@pytest.mark.parametrize("failure", ["weak", "tracked", "missing", "covered", "vertical"])
def test_supplement_keeps_existing_freshness_map_and_motion_gates(position, failure):
    position.set_supplement(True)
    for i in range(3):
        step(position, 10 + i * .2)
    observation, image = observe(500), None
    if failure == "weak":
        observation = observe(500, confidence=.5)
    elif failure == "tracked":
        observation = replace(observation, player=replace(observation.player, tracked=True))
    elif failure == "missing":
        observation = replace(observation, player=None)
    elif failure == "covered":
        image = view(((60, 20),))
        image[60:150, 0:220] = (30, 30, 30)
    else:
        observation = replace(observation, player=replace(
            observation.player, box=observation.player.box.translated(0, -8)))
    result = step(position, 11, observation=observation, image=image)
    assert result["kind"] == "unknown" and not result["provisional"]
    assert result["projection"] is None


def test_runtime_rejects_input_sessions_and_non_capture_modes_and_accepts_disable(app, position):
    app.position = position
    app.capture_only = False
    with pytest.raises(ValueError, match="idle capture-only"):
        app._command("position_supplement", {"enabled": True})
    app.capture_only = True
    app.mode = "dry_run"
    with pytest.raises(ValueError, match="idle capture-only"):
        app._command("position_supplement", {"enabled": True})
    app.mode = "capture"
    app.calibrating = True
    with pytest.raises(ValueError, match="idle capture-only"):
        app._command("position_supplement", {"enabled": True})
    app.calibrating = False
    assert app._command("position_supplement", {"enabled": True})["enabled"]
    app.area_editing = True
    assert not app._command("position_supplement", {"enabled": False})["enabled"]
    app.area_editing = False
    with pytest.raises(ValueError, match="boolean"):
        app._command("position_supplement", {"enabled": "true"})
    assert app.controller.backend.events == []


def test_teaching_calibration_and_input_capable_tracker_cannot_use_supplement(position):
    position.capture_only = False
    with pytest.raises(ValueError, match="capture-only"):
        position.set_supplement(True)
    position.capture_only = True
    position.set_supplement(True)
    position.begin_calibration()
    assert not position.supplement_status()["enabled"]
    with pytest.raises(ValueError, match="teaching and calibration"):
        position.set_supplement(True)
    position.cancel_calibration()
    position.set_supplement(True)
    position.begin_teaching()
    assert not position.supplement_status()["enabled"]


def test_provisional_reading_is_not_navigation_feedback(app, position):
    from maplebot.navigation import RouteMap

    profile = position.profile
    path = position.store.directory / f"{AREA}.json"
    evidence = {"area_id": AREA, "revision": 4, "map_hash": "", "edges": {}}
    from maplebot.navigation import map_hash
    evidence["map_hash"] = map_hash(profile)
    app.position, app.areas = position, position.store
    app.navigation.graph = RouteMap(profile, evidence)
    image, observation = view(((60, 20),)), observe(500)
    fix = position.read_map(image)
    for provisional in (False, True):
        app.navigation.observe(fix, observation, {
            "surface_id": "draft_middle_ledge", "provisional": provisional}, time.perf_counter())
        assert app.navigation.feedback.surface == (None if provisional else "draft_middle_ledge")
    assert json.loads(path.read_text())["platforms"] == profile["platforms"]
