import hashlib
import json

import cv2
import numpy as np
import pytest

from maplebot.scene_anchors import SceneAnchor


def fixture():
    hsv = np.random.default_rng(8).integers((10, 80, 40), (35, 255, 230),
                                          (24, 24, 3), dtype=np.uint8)
    template = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    record = {"version": 1, "world_x": 100, "local_x": 12, "uncertainty_px": 2,
              "capture_width": 500, "capture_height": 120, "name": "test ladder",
              "foreground_hsv": [[8, 45, 25], [38, 255, 235]]}
    image = np.zeros((120, 500, 3), np.uint8)
    image[30:54, 200:224] = template
    return record, template, image


def test_absolute_anchor_does_not_follow_marker_quantization():
    record, template, image = fixture()
    anchor = SceneAnchor(record, template)
    for coarse in (128, 138, 148):
        result = anchor.locate_x(image, 250, coarse)
        assert result["x"] == 138
        assert result["uncertainty_px"] == 2 and result["vertical_verified"] is False


def test_missing_ambiguous_resized_or_inconsistent_landmarks_refuse():
    record, template, image = fixture()
    anchor = SceneAnchor(record, template)
    assert anchor.locate_x(np.zeros_like(image), 250, 138) is None
    assert anchor.locate_x(image[:100], 250, 138) is None
    assert anchor.locate_x(image, 250, 180) is None
    image[30:54, 230:254] = template
    assert anchor.locate_x(image, 250, 138) is None


def test_anchor_bank_is_pinned_to_source_provider_and_template_bytes(tmp_path, monkeypatch):
    from maplebot import scene_anchors

    monkeypatch.setattr(scene_anchors, "__file__", str(tmp_path / "scene_anchors.py"))
    root = tmp_path / "static" / "landmarks"
    root.mkdir(parents=True)
    record, template, _ = fixture()
    image = root / "template.png"
    cv2.imwrite(str(image), template)
    record.update(source_sha256="a" * 64, provider="meowdb-classic", image=image.name,
                  template_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    (root / "60.json").write_text(json.dumps(record))
    public = {"id": 60, "sha256": "a" * 64, "provider": "meowdb-classic"}
    assert SceneAnchor.load(public) is not None
    assert SceneAnchor.load({**public, "sha256": "b" * 64}) is None
    assert SceneAnchor.load({**public, "provider": "dreamms"}) is None
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="template changed"):
        SceneAnchor.load(public)
