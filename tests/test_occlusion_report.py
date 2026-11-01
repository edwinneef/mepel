import json

import cv2
import numpy as np
import pytest

from tools.occlusion_evaluation import digest
from tools.occlusion_report import recovery_intents, render


def test_report_preserves_unknowns_and_rejects_stale_or_unaligned_evidence(tmp_path):
    image = tmp_path / "raw.png"
    cv2.imwrite(str(image), np.zeros((60, 80, 3), np.uint8))
    frame = {"path": "raw.png", "sha256": digest(image), "at": 1,
             "visibility": "hidden", "identity": None, "box": None}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sequences": [{"id": "hidden", "frames": [frame]}]}))
    row = {"path": "raw.png", "at": 1, "player": None,
           "evaluation": {"outcome": "abstained"}}
    report = {"manifest_sha256": digest(manifest),
              "semantic": {"sequences": [{"id": "hidden", "frames": [row]}]}}
    result = tmp_path / "result.json"
    result.write_text(json.dumps(report))
    summary = render(manifest, result, result, tmp_path / "report", tmp_path)
    assert summary["semantic_equal"] and summary["frames"] == 1
    assert "identity=None; independent box=None" in (tmp_path / "report/index.html").read_text()
    assert cv2.imread(str(tmp_path / "report/000.png")).shape == (92, 160, 3)
    with pytest.raises(FileExistsError):
        render(manifest, result, result, tmp_path / "report", tmp_path)
    row["at"] = 2
    result.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="alignment"):
        render(manifest, result, result, tmp_path / "bad", tmp_path)
    assert not (tmp_path / "bad").exists()
    row["at"] = 1
    result.write_text(json.dumps(report))
    image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Hash mismatch"):
        render(manifest, result, result, tmp_path / "stale", tmp_path)
    assert not (tmp_path / "stale").exists()


@pytest.mark.parametrize("outcome,visibility,wrong,unknown", [
    ("correct_fresh_identity", "visible", 0, 0), ("wrong_fresh", "visible", 1, 0),
    ("unsupported_fresh", "unknown", 0, 1), ("unsupported_fresh", "hidden", 1, 0),
])
def test_recovery_label_support(outcome, visibility, wrong, unknown):
    def row(at, fresh, classification):
        return {"at": at, "player": {"template": "nametag:alice"},
                "evaluation": {"fresh": fresh, "outcome": classification,
                               "visibility": visibility}}

    result = recovery_intents({"id": "synthetic", "frames": [
        row(0, True, "correct_fresh_identity"), row(.1, False, "abstained"),
        row(.2, True, outcome), row(.4, True, outcome)]})
    assert [r["state"] for r in result["intents"]] == ["ok", "pause", "wait", "resume"]
    assert result["resume_requests"] == 1
    assert result["wrong_resume_requests"] == wrong
    assert result["unknown_resume_requests"] == unknown
    assert result["native_acceptance"] is False
