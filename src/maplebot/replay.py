"""Offline replay and measured benchmarks. This module never creates an input backend."""

import json
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from .autopotter import PotionMonitor
from .config import Config
from .decision import Agent
from .geometry import Rect
from .perception import TemplateDetector, annotate


def run_replay(
    directory: Path,
    templates: Path,
    output: Path,
    config: Config,
    labels: Path | None = None,
    annotated: bool = False,
    autopotter: Path | None = None,
) -> dict:
    frames = sorted(path for path in directory.glob("*.png") if ".annotated." not in path.name)
    if not frames:
        raise ValueError("Replay directory has no raw PNG screenshots")
    if output.resolve() == directory.resolve():
        raise ValueError("Replay output must be a separate directory from source frames")
    output.mkdir(parents=True, exist_ok=True)
    detector = TemplateDetector(templates, config.perception)
    agent = Agent(config.agent, config.perception.confidence)
    agent.start()
    potter = PotionMonitor(autopotter) if autopotter is not None else None
    if potter:
        potter.start()
    potion_suggestions = {"hp": 0, "mp": 0}
    truth = json.loads(labels.read_text("utf-8")) if labels else {}
    timestamps = {}
    log_path = directory / "decisions.jsonl"
    if log_path.exists():
        for line in log_path.read_text("utf-8").splitlines():
            record = json.loads(line)
            if "captured_at" in record:
                timestamps[record["frame"]] = float(record["captured_at"])
    latency, decision_latency = [], []
    counts = {kind: {"tp": 0, "fp": 0, "fn": 0} for kind in ("player", "monster")}
    labeled_frames = 0
    opportunities = 0
    output_log = output / f"replay-{time.time_ns()}.jsonl"
    first_time = timestamps.get(frames[0].name, 0.0)
    with output_log.open("w", encoding="utf-8") as handle:
        for index, path in enumerate(frames):
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"Unreadable screenshot: {path}")
            now = timestamps.get(path.name, first_time + index / config.capture.fps) - first_time
            began = time.perf_counter()
            observation = detector.detect(image, now)
            potter_status = potter.observe(image, now) if potter else None
            if potter_status and potter_status["suggestion"]:
                potion_suggestions[potter_status["suggestion"]] += 1
            decision_start = time.perf_counter()
            if agent.state == "SEARCH":
                opportunities += 1
            decision = agent.step(observation, now)
            decision_latency.append((time.perf_counter() - decision_start) * 1000)
            latency.append((time.perf_counter() - began) * 1000)
            handle.write(
                json.dumps(
                    {
                        "frame": path.name,
                        "time": now,
                        "decision": asdict(decision),
                        "observation": asdict(observation),
                        "autopotter": potter_status,
                        "input_sent": False,
                    }
                )
                + "\n"
            )
            if annotated:
                image = annotate(
                    image, observation, decision.target, decision.state, decision.reason
                )
                if potter and potter_status:
                    potter.annotate(image, potter_status)
                if not cv2.imwrite(str(output / f"{path.stem}.annotated.png"), image):
                    raise OSError("Could not save annotated replay frame")
            if path.name in truth:
                labeled_frames += 1
                expected = truth[path.name]
                for kind, predictions in (
                    ("player", [observation.player] if observation.player else []),
                    (
                        "monster",
                        [
                            item
                            for item in observation.monsters
                            if item.confidence >= config.perception.confidence
                        ],
                    ),
                ):
                    unmatched = [Rect(*box) for box in expected.get(kind, [])]
                    for detection in sorted(
                        predictions, key=lambda item: item.confidence, reverse=True
                    ):
                        matches = [detection.box.iou(box) for box in unmatched]
                        if matches and max(matches) >= 0.5:
                            counts[kind]["tp"] += 1
                            unmatched.pop(int(np.argmax(matches)))
                        else:
                            counts[kind]["fp"] += 1
                    counts[kind]["fn"] += len(unmatched)
    metrics = {
        "source": str(directory.resolve()),
        "frames": len(frames),
        "input_sent": False,
        "processing_fps": round(1000 * len(latency) / sum(latency), 2),
        "processing_mean_ms": round(float(np.mean(latency)), 3),
        "processing_p95_ms": round(float(np.percentile(latency, 95)), 3),
        "decision_mean_ms": round(float(np.mean(decision_latency)), 4),
        "target_acquisitions": agent.acquisitions,
        "search_opportunities": opportunities,
        "target_acquisition_rate": agent.acquisitions / opportunities if opportunities else None,
        "labeled_frames": labeled_frames,
        "accuracy": None,
        "potion_suggestions": potion_suggestions if potter else None,
        "notes": (
            "FPS excludes disk I/O, annotation and real-time waits. "
            "No kill/success metric inferred."
        ),
    }
    if labeled_frames:
        for values in counts.values():
            values["precision"] = (
                values["tp"] / (values["tp"] + values["fp"])
                if values["tp"] + values["fp"]
                else None
            )
            values["recall"] = (
                values["tp"] / (values["tp"] + values["fn"])
                if values["tp"] + values["fn"]
                else None
            )
        metrics["accuracy"] = counts
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics
