import numpy as np

from maplebot.first_visit import FirstVisitLocator
from maplebot.structure_detection import Structure


def test_first_visit_needs_no_saved_area_walk_or_map_specific_image(monkeypatch):
    monkeypatch.setattr("maplebot.first_visit.detect", lambda *_: [])
    monkeypatch.setattr("maplebot.first_visit.describe", lambda *_: {
        "canvas": {}, "dot": {"x": 10, "y": 20}})
    monkeypatch.setattr("maplebot.first_visit.align", lambda *_: {
        "transform": {"scale_x": 16, "offset_x": -100, "scale_y": 16, "offset_y": -200}})
    monkeypatch.setattr("maplebot.scene_anchors.SceneAnchor.load", lambda *_:
                        (_ for _ in ()).throw(AssertionError("Per-map bank is forbidden")))
    locator = FirstVisitLocator({"miniMap": {}, "footholds": {}, "ladderRopes": []})
    player = {"box": {"x": 100, "y": 200, "width": 40, "height": 60}, "confidence": 1}
    result = locator.locate(np.zeros((768, 1366, 3), np.uint8), player)
    assert result["coarse_xy"] == [60, 120]
    assert result["xy"] is None and result["precision_verified"] is False
    assert result["input_sent"] is False


def test_missing_marker_never_creates_a_confident_first_fix(monkeypatch):
    monkeypatch.setattr("maplebot.first_visit.detect", lambda *_: [])
    monkeypatch.setattr("maplebot.first_visit.describe", lambda *_: None)
    locator = FirstVisitLocator({})
    result = locator.locate(np.zeros((768, 1366, 3), np.uint8), None)
    assert result["xy"] is None and "No unique" in result["reason"]


def test_scene_x_can_join_stable_mapped_y_without_using_artwork_edges(monkeypatch):
    source = {"miniMap": {}, "ladderRopes": [{"x": x, "y1": 0, "y2": 180,
                                               "isLadder": True} for x in (10, 110)],
              "footholds": {"1": {"id": 1, "x1": -200, "x2": 300, "y1": 200,
                                    "y2": 200, "prev": 0, "next": 0}}}
    monkeypatch.setattr("maplebot.first_visit.detect", lambda *_: [
        Structure("ladder", 320, 220, 370, 3), Structure("ladder", 420, 220, 370, 3)])
    monkeypatch.setattr("maplebot.first_visit.describe", lambda *_: {
        "canvas": {"x": 0, "y": 0, "width": 100, "height": 100},
        "dot": {"x": 10, "y": 20}})
    monkeypatch.setattr("maplebot.first_visit.align", lambda *_: {
        "transform": {"scale_x": 16, "offset_x": -120, "scale_y": 16, "offset_y": -120}})
    player = {"box": {"x": 330, "y": 340, "width": 40, "height": 60}, "confidence": 1}
    locator = FirstVisitLocator(source)
    image = np.zeros((768, 1366, 3), np.uint8)
    for now in (1., 1.2, 1.4):
        result = locator.locate(image, player, now=now, camera=(0, 0), identity="player")
    assert result["candidate_xy"] == [40, 200]
    assert result["xy"] is None and result["precision_verified"] is False
    assert result["geometry"]["contact_verified"] is False
