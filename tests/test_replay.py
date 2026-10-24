import json
import sys
from dataclasses import asdict

import cv2
import numpy as np
import pytest
from test_perception import templates

from maplebot.config import Config
from maplebot.decision import Agent, PolicyInput
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation
from maplebot.replay import run_policy_replay, run_replay, write_policy_diff


def policy_record(config, sequence, now):
    agent = Agent(config.agent, config.perception.confidence)
    agent.start()
    observation = Observation(
        Detection("player", Rect(100, 100, 24, 28), 0.99),
        [Detection("monster", Rect(200, 100, 24, 28), 0.99)],
    )
    policy_input = PolicyInput(observation, now, {"status": "not_sent"})
    policy_before = agent.snapshot()
    decision = agent.step_input(policy_input)
    return {
        "sequence": sequence,
        "frame": f"{sequence:08d}.png",
        "policy_input": policy_input.to_dict(),
        "policy_before": policy_before,
        "decision": {**asdict(decision), "state": str(decision.state)},
    }


def test_policy_replay_is_input_free_and_rejects_invalid_history(tmp_path):
    config = Config()
    record = policy_record(config, 0, 0.0)
    session = tmp_path / "session"
    session.mkdir()
    (session / "decisions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert run_policy_replay(session, config) == []
    (session / "decisions.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="at least one record"):
        run_policy_replay(session, config)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda record: record.pop("policy_input"), "Invalid policy record"),
        (lambda record: record["policy_before"].pop("version"), "Unsupported policy snapshot"),
    ],
)
def test_policy_replay_rejects_legacy_or_incomplete_records(tmp_path, mutate, message):
    config = Config()
    record = policy_record(config, 0, 0.0)
    mutate(record)
    session = tmp_path / "session"
    session.mkdir()
    (session / "decisions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        run_policy_replay(session, config)


def test_policy_replay_rejects_duplicate_sequence_or_capture_time(tmp_path):
    config = Config()
    first = policy_record(config, 0, 0.0)
    second = policy_record(config, 0, 0.0)
    session = tmp_path / "session"
    session.mkdir()
    (session / "decisions.jsonl").write_text(
        "\n".join(json.dumps(record) for record in (first, second)) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="sequence must strictly increase"):
        run_policy_replay(session, config)


def test_policy_diff_writes_one_stable_row_for_changed_decision(tmp_path):
    config = Config()
    record = policy_record(config, 0, 0.0)
    record["decision"]["reason"] = "deliberately changed"
    session = tmp_path / "session"
    session.mkdir()
    (session / "decisions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    result = write_policy_diff(session, tmp_path / "output", config)
    rows = (tmp_path / "output" / "policy-diff.jsonl").read_text("utf-8").splitlines()
    assert result["differences"] == 1
    assert result["input_sent"] is False
    assert json.loads(rows[0]) == {
        "actual": {"reason": "Acquired nearest same-platform target"},
        "expected": {"reason": "deliberately changed"},
        "fields": ["reason"],
        "frame": "00000000.png",
        "sequence": 0,
    }


def test_policy_only_cli_returns_success_for_an_exact_replay(tmp_path, monkeypatch, capsys):
    from maplebot.__main__ import main

    config = Config()
    session = tmp_path / "session"
    session.mkdir()
    (session / "decisions.jsonl").write_text(
        json.dumps(policy_record(config, 0, 0.0)) + "\n", encoding="utf-8"
    )
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        ["maplebot", "replay", str(session), "--policy-only", "--output", str(output)],
    )
    main()
    assert json.loads(capsys.readouterr().out)["differences"] == 0
    assert (output / "policy-diff.jsonl").read_text("utf-8") == ""


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
