import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from tools.validate_position_landmarks import match, metrics, validate


def test_repeated_or_wrong_landmarks_are_not_accepted():
    patch = np.random.default_rng(7).integers(0, 255, (16, 16, 3), dtype=np.uint8)
    image = np.zeros((70, 150, 3), np.uint8)
    image[20:36, 30:46] = patch
    assert match(image, patch)[:2] == (30, 20)
    image[20:36, 90:106] = patch
    assert match(image, patch) is None
    assert match(np.zeros_like(image), patch) is None


def test_foreground_matching_ignores_changed_background_without_lowering_threshold():
    random = np.random.default_rng(11)
    patch = random.integers(0, 255, (24, 24, 3), dtype=np.uint8)
    mask = np.zeros((24, 24), np.uint8)
    mask[:, 8:16] = 255
    changed = patch.copy()
    changed[mask == 0] = 0
    image = random.integers(0, 255, (100, 140, 3), dtype=np.uint8)
    image[40:64, 60:84] = changed
    assert match(image, patch) is None
    assert match(image, patch, mask)[:2] == (60, 40)


def test_landmark_truth_is_independent_of_minimap_estimate(tmp_path, monkeypatch):
    reference = np.zeros((120, 500, 3), np.uint8)
    random = np.random.default_rng(9)
    reference[30:46, 200:216] = random.integers(0, 255, (16, 16, 3), dtype=np.uint8)
    reference[60:76, 400:416] = random.integers(0, 255, (16, 16, 3), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "reference.png"), reference)
    labels = {"map_id": 60, "reference": "reference.png", "annotation_uncertainty_px": 2,
              "landmarks": [{"name": str(x), "box": [x, y, 16, 16], "screen_x": x + 8,
                             "world_x": x - 92} for x, y in ((200, 30), (400, 60))]}
    annotations = tmp_path / "labels.json"
    annotations.write_text(json.dumps(labels))
    monkeypatch.setattr("tools.validate_position_landmarks.load_source", lambda *_: (
        {"ladderRopes": [{"x": 108}, {"x": 308}], "miniMap": {}}, "a" * 64))
    transform = {"scale_x": 16, "offset_x": 0, "scale_y": 16, "offset_y": 0}
    monkeypatch.setattr("tools.validate_position_landmarks.align", lambda *_: {
        "transform": transform, "uncertainty_px": 16})
    rows = []
    for i, dx in enumerate((0, -5, -10)):
        image = cv2.warpAffine(reference, np.float32([[1, 0, dx], [0, 1, 0]]), (500, 120))
        name = f"frame{i}.png"
        cv2.imwrite(str(tmp_path / name), image)
        rows.append({"frame": name, "capture_clock": 1 + .2 * i,
                     "position": {"canvas": {}, "marker": [10, 5]},
                     "player": {"box": {"x": 240, "y": 70, "width": 20, "height": 20},
                                "confidence": 1}, "camera_confidence": 1,
                     "camera_shift": [0 if i == 0 else -5, 0]})
    (tmp_path / "decisions.jsonl").write_text("\n".join(map(json.dumps, rows)))
    report = validate(tmp_path, annotations, tmp_path / "unused-source")
    assert report["accepted"] == 3
    assert [s["landmark_world_x"] for s in report["samples"]] == [150, 155, 160]
    assert [s["raw_error_px"] for s in report["samples"]] == [10, 5, 0]
    assert report["native_acceptance"] is False and report["input_sent"] is False
    monkeypatch.setattr("tools.validate_position_landmarks.SceneAnchor.load", lambda *_:
                        SimpleNamespace(record={"world_x": 108, "name": "test"}))
    with pytest.raises(ValueError, match="separate recording"):
        validate(tmp_path, annotations, tmp_path / "unused-source", scene_anchor=True)
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    (evaluation / "decisions.jsonl").write_text("\n".join(map(json.dumps, rows)))
    with pytest.raises(ValueError, match="overlap"):
        validate(evaluation, annotations, tmp_path / "unused-source",
                 reference_recording=tmp_path, scene_anchor=True)
    labels["landmarks"][0]["world_x"] = 999
    annotations.write_text(json.dumps(labels))
    with pytest.raises(ValueError, match="absent"):
        validate(tmp_path, annotations, tmp_path / "unused-source")


def test_empty_metrics_cannot_look_like_passed_accuracy():
    assert metrics([]) is None
    assert metrics([10, -10])["p95_px"] == 10
