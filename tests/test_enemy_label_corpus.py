import json

import pytest

from tools.enemy_label_corpus import prepare


def test_preserves_missing_empty_frames_and_never_fabricates_labels(tmp_path):
    monster = {"confidence": .82, "box": {"x": 1, "y": 2, "width": 3, "height": 4}}
    rows = [{"frame": "1.png", "monsters": [monster]},
            {"frame": "2.png", "monsters": []},
            {"frame": "3.png", "monsters": [monster]}]
    (tmp_path / "1.png").write_bytes(b"fixture")
    (tmp_path / "decisions.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    result = prepare(tmp_path)
    assert result["summary"] == {"frames": 3, "missing_images": 2, "candidates": 2}
    frames = result["frames"]
    assert len(frames[0]["sha256"]) == 64
    assert frames[1]["candidates"] == [] and frames[2]["sha256"] is None
    candidate = frames[0]["candidates"][0]
    assert candidate["raw_score"] == .82
    assert candidate["recorded_track_id"] is None
    assert candidate["annotation"]["expected_eligible"] is None
    assert candidate["annotation"]["identity"] is None
    assert prepare(tmp_path) == result


@pytest.mark.parametrize("name", ["../outside.png", "sub/a.png", "sub\\a.png", "a.json"])
def test_rejects_external_frames(tmp_path, name):
    (tmp_path / "decisions.jsonl").write_text(json.dumps({"frame": name}), encoding="utf-8")
    with pytest.raises(ValueError, match="local PNG"):
        prepare(tmp_path)


def test_duplicate_frames_cannot_count_as_independent_evidence(tmp_path):
    row = json.dumps({"frame": "1.png"})
    (tmp_path / "decisions.jsonl").write_text(row + "\n" + row, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        prepare(tmp_path)
