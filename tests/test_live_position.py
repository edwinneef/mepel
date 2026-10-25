import json
import time
from types import SimpleNamespace

import numpy as np
import pytest
from test_minimap_reader import view
from test_runtime import app  # noqa: F401 - pytest fixture

from maplebot.geometry import Rect
from maplebot.live_position import LivePosition
from maplebot.map_filter import MapFilter
from maplebot.perception import Detection, Observation
from maplebot.profiles import AreaStore, validate_profile
from maplebot.runtime import Application

AREA = "b" * 32


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Registration is measured offline; here the camera sits on the reference view.
    monkeypatch.setattr("maplebot.live_position.register_view", lambda reference, image: (0, 0))
    store = AreaStore(tmp_path / "areas")
    store.save({
        "schema_version": 2, "id": AREA, "name": "Floor", "revision": 0,
        "boundary": {"x": 0, "y": 0, "width": 1366, "height": 768},
        "views": [store.capture_view(view())], "zones": [], "ropes": [], "links": [],
        "platforms": [{"id": "floor", "start": {"x": 0, "y": 600},
                       "end": {"x": 1366, "y": 600}}],
    })
    return store


def observe(x, *, confidence=1.0):
    player = Detection("player", Rect(round(x) - 22, 536, 44, 64), confidence, "nametag")
    return Observation(player, [], camera_shift=(0, 0), camera_confidence=0.9)


def step(position, dx, now):
    image = view(((dx, 20),))
    fix = position.read_map(image)
    result = position.update(image, fix, observe(8 * (dx + 2.5)), now)
    if position.pending is not None:
        position.pending.result(timeout=5)
    return result


def calibrate(position):
    position.begin_calibration()
    for index, dx in enumerate(range(10, 170, 8)):
        step(position, dx, index * 0.3)
    return position.finish_calibration()


def test_uncalibrated_area_reports_why_and_sends_no_input(store):
    position = LivePosition(store, AREA)
    try:
        result = step(position, 60, 0.0)
        assert result["kind"] == "unknown" and result["reason"] == "Walk calibration needed"
        assert result["marker"] == [62.5, 22.5] and result["input_sent"] is False
    finally:
        position.close()


def test_walk_calibration_saves_transform_and_residual_then_locates(store):
    position = LivePosition(store, AREA)
    try:
        saved = calibrate(position)
        calibration = saved["calibration"]
        assert saved["revision"] == 2 and calibration["pairs"] >= 10
        assert calibration["transform"]["scale_x"] == pytest.approx(8, abs=0.01)
        assert calibration["residual_px"]["x"]["p95"] < 1
        assert list(store.directory.glob("*.bak"))
        on_disk = json.loads((store.directory / f"{AREA}.json").read_text("utf-8"))
        assert on_disk["minimap_calibration"]["pairs"] == calibration["pairs"]
        results = [step(position, 60, 10 + index * 0.2) for index in range(3)]
        assert [r["kind"] for r in results] == ["unknown", "unknown", "platform"]
        assert results[-1]["surface_id"] == "floor"
        assert results[-1]["feet"] == pytest.approx([500, 600], abs=1)
        assert results[-1]["calibration"]["saved"]["pairs"] == calibration["pairs"]
    finally:
        position.close()


def test_calibration_needs_enough_fresh_pairs(store):
    position = LivePosition(store, AREA)
    try:
        position.begin_calibration()
        image = view(((60, 20),))
        for index in range(12):
            position.update(image, position.read_map(image), observe(500, confidence=0.5),
                            index * 0.3)
        assert position.pending is None and position.samples == []
        with pytest.raises(ValueError, match="at least ten"):
            position.finish_calibration()
    finally:
        position.close()


def test_covered_minimap_is_unknown(store):
    position = LivePosition(store, AREA)
    try:
        calibrate(position)
        image = view(((60, 20),))
        image[60:150, 0:220] = (30, 30, 30)
        result = position.update(image, position.read_map(image), observe(500), 20.0)
        assert result["kind"] == "unknown" and result["marker"] is None
        assert result["reason"] == "Minimap missing, covered or showing another map"
    finally:
        position.close()


def test_changed_reference_view_drops_calibration(store):
    position = LivePosition(store, AREA)
    try:
        calibrate(position)
    finally:
        position.close()
    profile = store.load(AREA)["profile"]
    assert "minimap_calibration" in profile
    profile["views"] = [store.capture_view(view(seed=2))]
    checked, warnings = validate_profile(profile)
    assert "minimap_calibration" not in checked
    assert "Walk calibration removed: its reference view changed" in warnings


def test_position_older_than_500_ms_is_cleared():
    tracking = SimpleNamespace(position=object())
    fresh = {"kind": "platform", "surface_id": "floor", "feet": [1, 2], "marker": [3, 4],
             "reason": "ok", "captured_at": time.time()}
    assert Application._position_snapshot(tracking, fresh)["kind"] == "platform"
    stale = Application._position_snapshot(tracking, {**fresh, "captured_at": time.time() - 0.6})
    assert stale["stale"] is True and stale["kind"] == "unknown"
    assert stale["surface_id"] is None and stale["feet"] is None and stale["marker"] is None
    assert Application._position_snapshot(SimpleNamespace(position=None), fresh) is None


def test_taught_minimap_holds_monster_set_while_title_is_unreadable(monkeypatch, tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "maps.json").write_text(json.dumps([
        {"streetName": "Hidden Street", "name": "The Blue Mushroom Forest",
         "monsters": [1]},
    ]))
    router = MapFilter(tmp_path, [{"id": 1, "name": "Blue Mushroom"}])
    title = {"text": "Hidden Street The Blue Mushroom Forest"}
    monkeypatch.setattr("maplebot.map_filter.read_title", lambda image: title["text"])
    image = np.zeros((100, 350, 3), dtype=np.uint8)
    try:
        router.select(image, True)
        router.pending.result(timeout=3)
        assert router.select(image, True) == {"Blue Mushroom"}
        title["text"] = "Loading..."
        image[:19] = 100
        router.select(image, True)
        router.pending.result(timeout=3)
        assert router.select(image, True) == {"Blue Mushroom"} and router.held
        assert router.select(image, False) is None and not router.held
        assert router.select(image, True) is None
    finally:
        router.close()


def test_runtime_tracks_position_read_only_and_stops_cleanly(app, store):  # noqa: F811
    from maplebot.contracts import COMMANDS
    from maplebot.runtime import POSITION_COMMANDS

    assert POSITION_COMMANDS <= COMMANDS
    with pytest.raises(ValueError, match="Track a saved area"):
        app._command("walk_calibration_begin", {})
    assert app._command("position_start", {"area_id": AREA}) == {
        "tracking": True, "area_id": AREA, "calibrated": False,
    }
    _, result = app._process(view(((60, 20),)), time.perf_counter())
    assert result["position"]["reason"] == "Walk calibration needed"
    assert result["position"]["input_sent"] is False and app.detector.taught_map
    assert app._command("walk_calibration_begin", {})["active"] is True
    app.area_editing = True
    with pytest.raises(ValueError, match="Finish area editing"):
        app._command("walk_calibration_finish", {})
    app.area_editing = False
    assert app._command("position_stop", {}) == {"tracking": False}
    assert app.position is None and not app.detector.taught_map
    assert app.snapshot()["position"] is None


def test_teaching_calibrates_itself_then_records_and_saves_walked_geometry(store):
    position = LivePosition(store, AREA)
    try:
        assert position.begin_teaching()["phase"] == "calibrating"
        for index, dx in enumerate(range(10, 170, 7)):
            result = step(position, dx, index * 0.3)
        assert position.tracker is not None
        assert result["teaching"]["phase"] == "recording"
        for index, dx in enumerate(range(170, 10, -7)):
            result = step(position, dx, 20 + index * 0.3)
        assert result["teaching"]["geometry"]["platforms"]
        proposal = position.finish_teaching()
        assert position._teaching_status(30)["phase"] == "review"
        saved = position.save_teaching()
        profile = saved["profile"]
        assert profile["platforms"] == proposal["platforms"] and profile["revision"] == 3
        assert profile["minimap_calibration"]["pairs"] >= 20
        [floor] = profile["platforms"]
        assert floor["start"]["y"] == pytest.approx(600, abs=1)
        assert position._teaching_status(31)["phase"] is None
    finally:
        position.close()


def test_teaching_refuses_to_save_nothing(store):
    position = LivePosition(store, AREA)
    try:
        calibrate(position)
        position.begin_teaching()
        with pytest.raises(ValueError, match="No platform seen"):
            position.finish_teaching()
        with pytest.raises(ValueError, match="Finish teaching"):
            position.save_teaching()
    finally:
        position.close()
