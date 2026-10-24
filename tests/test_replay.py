import json

import cv2
import numpy as np
from test_perception import templates

from maplebot.config import Config
from maplebot.replay import run_replay


def test_replay_produces_decisions_metrics_and_annotations_without_win32(tmp_path):
    player, monster = templates(tmp_path / "templates")
    frames = tmp_path / "frames"
    frames.mkdir()
    image = np.full((160, 260, 3), 30, dtype=np.uint8)
    image[90:118, 20:44] = player
    image[90:118, 180:204] = monster
    labels = {}
    for index in range(3):
        name = f"{index:04d}.png"
        cv2.imwrite(str(frames / name), image)
        labels[name] = {"player": [[20, 90, 24, 28]], "monster": [[180, 90, 24, 28]]}
    label_path = tmp_path / "labels.json"
    label_path.write_text(json.dumps(labels))
    output = tmp_path / "output"
    result = run_replay(frames, tmp_path / "templates", output, Config(), label_path, True)
    assert result["input_sent"] is False
    assert result["frames"] == 3
    assert result["target_acquisitions"] == 1
    assert result["accuracy"]["player"]["recall"] == 1
    assert result["accuracy"]["monster"]["precision"] == 1
    assert result["processing_fps"] > 0
    decisions = [json.loads(line) for line in next(output.glob("*.jsonl")).read_text().splitlines()]
    assert all(not item["input_sent"] for item in decisions)
    assert decisions[1]["decision"]["action"]["kind"] == "right"
    assert len(list(output.glob("*.annotated.png"))) == 3


def test_unlabeled_replay_does_not_invent_accuracy(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    cv2.imwrite(str(frames / "blank.png"), np.zeros((100, 100, 3), dtype=np.uint8))
    result = run_replay(frames, tmp_path / "empty", tmp_path / "out", Config())
    assert result["accuracy"] is None
    assert result["target_acquisitions"] == 0


def test_replay_includes_potion_suggestions_without_any_input(tmp_path):
    from test_autopotter import hud, monitor

    potter = monitor(tmp_path)
    frames = tmp_path / "frames"
    frames.mkdir()
    for index in range(3):
        cv2.imwrite(str(frames / f"{index:04d}.png"), hud(20))
    output = tmp_path / "out"
    metrics = run_replay(
        frames,
        tmp_path / "templates",
        output,
        Config(),
        annotated=True,
        autopotter=potter.path,
    )
    assert metrics["potion_suggestions"] == {"hp": 1, "mp": 0}
    assert metrics["input_sent"] is False
    logs = [json.loads(line) for line in next(output.glob("*.jsonl")).read_text().splitlines()]
    assert logs[1]["autopotter"]["suggestion"] == "hp"
    assert all(not item["autopotter"]["input_sent"] for item in logs)
