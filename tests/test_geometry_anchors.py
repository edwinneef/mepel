import numpy as np

from maplebot.geometry_anchors import GeometryAnchors, GeometryTracking
from maplebot.structure_detection import Structure


def source():
    return {"ladderRopes": [{"x": x, "y1": 0, "y2": 180, "isLadder": True}
                            for x in (10, 110)],
            "footholds": {"1": {"x1": -200, "x2": 300, "y1": 200, "y2": 200}}}


def features():
    return [Structure("ladder", 320, 220, 370, 3), Structure("ladder", 420, 220, 370, 3),
            Structure("surface", 400, 110, 610, 12)]


def test_joint_matching_places_candidates_but_preserves_collision_uncertainty():
    model = GeometryAnchors(source())
    result = model.locate(features(), (350, 400), (40, 200))
    assert result["candidate_xy"] == [40, 200]
    assert result["support"] == 3
    assert result["xy"] is None and result["uncertainty_xy"] == [3, 12]
    assert result["contact_verified"] is False


def test_parallel_ladders_do_not_make_vertical_position_observable():
    result = GeometryAnchors(source()).locate(features()[:2], (350, 400), (40, 200))
    assert result["state"] == "uncertain" and result["xy"] is None
    assert result["candidate_x"] == 40


def test_repeated_arrangements_and_conflicting_world_sources_refuse():
    data = source()
    data["ladderRopes"] += [{"x": x, "y1": 0, "y2": 180, "isLadder": True}
                            for x in (30, 130)]
    result = GeometryAnchors(data).locate(features(), (350, 400), (40, 200))
    assert result["xy"] is None and "Competing" in result["reason"]
    result = GeometryAnchors(source()).locate(features(), (350, 400), (9000, 9000))
    assert result["state"] == "uncertain"


def test_map_id_never_changes_detector_association():
    data = source()
    data["id"] = 60
    first = GeometryAnchors(data).locate(features(), (350, 400), (40, 200))
    data["id"] = 123456789
    assert GeometryAnchors(data).locate(features(), (350, 400), (40, 200)) == first


def test_camera_propagation_is_bounded_and_identity_or_camera_loss_resets(monkeypatch):
    monkeypatch.setattr("maplebot.geometry_anchors.detect", lambda *_: features())
    tracker = GeometryTracking(source())
    image = np.zeros((768, 1366, 3), np.uint8)
    first = tracker.observe(image, (350, 400), (40, 200), 1., "player", (0, 0))
    assert first["candidate_xy"] == [40, 200]
    following = tracker.observe(image, (350, 400), (50, 200), 1.1, "player", (-10, 0))
    assert following["candidate_xy"] == [50, 200] and following["xy"] is None
    missing = tracker.observe(image, (350, 400), (50, 200), 1.2, "player", None)
    assert missing["state"] == "uncertain" and tracker.last is None
    tracker.observe(image, (350, 400), (40, 200), 2., "player", (0, 0))
    monkeypatch.setattr("maplebot.geometry_anchors.detect", lambda *_: [])
    assert tracker.observe(image, (350, 400), (40, 200), 2.1, "other", (0, 0))["xy"] is None
