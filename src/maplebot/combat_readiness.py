"""Read-only combat preparation: observe distances and probes, never send input."""

import argparse
import json
import time
from pathlib import Path
from urllib.request import urlopen

from .config import Config
from .contracts import FRESH_FRAME_SECONDS


def summarize(status: dict, config: Config, now: float) -> dict:
    detections = status.get("live_detections") or status
    frame = detections.get("frame", {})
    age = now - frame.get("captured_at", 0)
    fresh = bool(frame.get("available") and 0 <= age <= FRESH_FRAME_SECONDS)
    player = detections.get("player")
    threshold = status.get("player_threshold", config.perception.confidence)
    recognized = bool(fresh and player and not player.get("tracked")
                      and player["confidence"] >= threshold)
    targets = []
    if recognized:
        origin = player["box"]
        for monster in detections.get("monsters", []):
            box = monster["box"]
            if monster.get("tracked") or monster["confidence"] < threshold:
                continue
            feet_gap = abs(box["y"] + box["height"] - origin["y"] - origin["height"])
            if feet_gap > config.agent.platform_tolerance:
                continue
            dx = box["x"] + box["width"] / 2 - origin["x"] - origin["width"] / 2
            distance = abs(dx)
            low, high = config.agent.attack_min_range, config.agent.attack_range
            targets.append({
                "template": monster.get("template"), "distance_px": distance,
                "direction": "right" if dx >= 0 else "left", "feet_gap_px": feet_gap,
                "configured_band": "too_close" if distance < low else
                "approach" if distance > high else "in_range",
            })
    return {
        "observed_at": now, "session_id": status.get("session_id"),
        "frame_id": frame.get("id"), "fresh_player": recognized,
        "player": player if recognized else None,
        "mode": status.get("mode"), "focused": status.get("focused"),
        "capture_only": status.get("capture_only"),
        "bindings": {key: status.get("bindings", {}).get(key) for key in ("attack", "skill")},
        "unconfirmed_controls": [key for key in status.get("required_probes", [])
                                 if not status.get("probes", {}).get(key, {}).get("confirmed")],
        "active_probe": status.get("active_probe"), "probes": status.get("probes", {}),
        "map": status.get("catalog", {}).get("active_map"),
        "catalog_paused": status.get("catalog", {}).get("catalog_paused"),
        "same_platform_targets": sorted(targets, key=lambda target: target["distance_px"]),
        "range_from_config_file": [config.agent.attack_min_range, config.agent.attack_range],
        "range_note": "File settings, not measured hit limits or proof of engine-loaded tuning",
        "engine_attack_setup": status.get("attack_setup"),
        "combat_evidence": status.get("combat_evidence"),
        "readiness": status.get("readiness"),
        "potion_readings": status.get("autopotter", {}).get("readings", {}),
        "hit_confirmed": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--seconds", type=float, default=0, help="Observe for 0 to 60 seconds")
    parser.add_argument("--output", type=Path, help="New JSONL evidence file; never overwritten")
    args = parser.parse_args()
    if not 0 <= args.seconds <= 60 or not 1 <= args.port <= 65535:
        parser.error("Use 0 to 60 seconds and a port from 1 to 65535")
    config = Config.load(args.config)
    output = args.output.open("x", encoding="utf-8") if args.output else None
    try:
        deadline = time.monotonic() + args.seconds
        while True:
            with urlopen(f"http://127.0.0.1:{args.port}/api/status", timeout=3) as response:
                status = json.load(response)
            line = json.dumps(summarize(status, config, time.time()))
            print(line, flush=True)
            if output:
                output.write(line + "\n")
                output.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
    finally:
        if output:
            output.close()


if __name__ == "__main__":
    main()
