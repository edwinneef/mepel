import json
from urllib.error import HTTPError

import pytest

from maplebot import hit_check
from maplebot.config import Config


def status(session="session", mode="capture"):
    return {
        "session_id": session, "mode": mode,
        "bindings": {"attack": "space", "skill": "ctrl"},
        "frame": {"id": f"{session}:1", "available": True, "captured_at": 10},
        "player": {"box": {"x": 100, "y": 100, "width": 20, "height": 30},
                   "confidence": 1.0},
        "monsters": [{"box": {"x": 250, "y": 100, "width": 20, "height": 30},
                      "confidence": 1.0}],
        "probes": {"attack": {"confirmed": True}, "skill": {"confirmed": True}},
    }


@pytest.mark.parametrize("action,key", [("attack", "space"), ("skill", "ctrl")])
def test_labelled_capture_preserves_detections_without_claiming_keypress_or_hit(
    monkeypatch, tmp_path, action, key
):
    calls = []
    original = status()
    original["live_detections"] = {
        "frame": {"id": "session:2", "available": True, "captured_at": 10.05},
        "player": None, "monsters": [],
    }

    def get(base, path):
        calls.append(path)
        return json.dumps(original).encode() if path == "/api/v1/status" else b"picture"

    monkeypatch.setattr(hit_check, "get", get)
    monkeypatch.setattr(hit_check.time, "time", lambda: 10.1)
    output = tmp_path / key
    result = hit_check.collect("unused", Config(), action, output, 0)
    row = json.loads((output / "observations.jsonl").read_text())
    assert row["key_label"] == key
    assert row["same_platform_targets"][0]["distance_px"] == 150
    assert row["detections"]["monsters"] == original["monsters"]
    assert (output / row["picture"]).read_bytes() == b"picture"
    assert result["hit_confirmed"] is None
    assert "not a recorded keypress" in result["key_label_source"]
    assert calls == ["/api/v1/status", "/api/v1/status", "/api/v1/frame?id=session%3A1&raw=1"]
    assert original["probes"][action]["confirmed"]
    with pytest.raises(FileExistsError):
        hit_check.collect("unused", Config(), action, output, 0)


def test_superseded_picture_is_reported_not_mismatched(monkeypatch, tmp_path):
    def get(base, path):
        if path == "/api/v1/status":
            return json.dumps(status()).encode()
        raise HTTPError(path, 409, "Frame superseded", {}, None)

    monkeypatch.setattr(hit_check, "get", get)
    output = tmp_path / "capture"
    result = hit_check.collect("unused", Config(), "attack", output, 0)
    row = json.loads((output / "observations.jsonl").read_text())
    assert row["picture"] is None
    assert row["picture_unavailable"]
    assert result["pictures"] == 0


@pytest.mark.parametrize("changed", [status(mode="live"), status(session="new")])
def test_activity_or_session_change_stops_and_keeps_partial_evidence(
    monkeypatch, tmp_path, changed
):
    snapshots = iter([status(), changed])
    monkeypatch.setattr(hit_check, "get", lambda *_: json.dumps(next(snapshots)).encode())
    output = tmp_path / "capture"
    with pytest.raises(ValueError):
        hit_check.collect("unused", Config(), "attack", output, 0)
    manifest = json.loads((output / "check.json").read_text())
    assert manifest["stop_reason"] != "Capture window complete"
    assert manifest["hit_confirmed"] is None


def test_wrong_binding_refuses_to_mislabel_capture(monkeypatch, tmp_path):
    snapshot = status()
    snapshot["bindings"]["attack"] = "a"
    monkeypatch.setattr(hit_check, "get", lambda *_: json.dumps(snapshot).encode())
    with pytest.raises(ValueError, match="binding"):
        hit_check.collect("unused", Config(), "attack", tmp_path / "capture", 0)
    assert not (tmp_path / "capture").exists()
