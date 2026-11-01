"""Summarize a saved failed check and optionally replay its policy, without input."""

import argparse
import json
import time
from pathlib import Path


def stop_records(value):
    if isinstance(value, dict):
        stop = value.get("stop")
        if isinstance(stop, dict) and stop.get("code"):
            yield stop
        for key, child in value.items():
            if key != "stop":
                yield from stop_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from stop_records(child)


def classify(reason: str) -> tuple[str, str]:
    reason = reason.lower()
    if any(word in reason for word in (" hp", " mp", "hud", "potions", "health")):
        return "health", "Inspect saved HUD readings and the no-consumables health limits."
    # FOCUS_LOSS is also used for stale feedback; the recorded detail takes priority.
    if "stale" in reason or "freshness" in reason or "500 ms" in reason:
        return "navigation", "Inspect frame gaps and stage timings; keep freshness gates unchanged."
    if "focus" in reason or "actual game window" in reason:
        return "focus", "Foreground ownership at refusal is needed; do not blame the operator."
    if "recognition" in reason or "player" in reason:
        return "perception", "Replay the recorded player observations before another live check."
    return "combat", "Inspect the recorded policy decisions and input outcomes."


def clip_summary(clip: Path, since: float | None = None, until: float | None = None) -> dict:
    log = clip / "decisions.jsonl"
    if not log.is_file():
        return {"path": str(clip), "available": False}
    records = [json.loads(line) for line in log.read_text("utf-8").splitlines() if line]
    transitions, gaps, timings = [], [], []
    active_seconds = 0.0
    previous = None
    for record in records:
        stamp = float(record["captured_at"])
        if previous is None or any(record.get(k) != previous.get(k) for k in ("mode", "focused")):
            transitions.append({k: record.get(k) for k in
                                ("sequence", "captured_at", "mode", "focused", "frame")})
        if previous is not None:
            previous_stamp = float(previous["captured_at"])
            if previous.get("mode") in {"live", "navigation"}:
                active_seconds += max(0, min(stamp, until if until is not None else stamp)
                                      - max(previous_stamp, since if since is not None
                                            else previous_stamp))
            gaps.append({"sequence": record.get("sequence"), "frame": record.get("frame"),
                         "gap_ms": round(1000 * (stamp - float(previous["captured_at"])), 3)})
        if isinstance(record.get("latency_ms"), (int, float)):
            timings.append({k: record.get(k) for k in
                            ("sequence", "frame", "mode", "latency_ms", "stage_timing")})
        previous = record
    return {"path": str(clip), "available": True, "frames": len(records),
            "transitions": transitions, "observed_active_seconds": round(active_seconds, 3),
            "active_time_scope": "Recorded live/navigation intervals within available run bounds; "
                                 "without a start bound this includes clip pre-roll",
            "run_bounds": {"since": since, "until": until},
            "largest_frame_gaps": sorted(gaps, key=lambda r: r["gap_ms"], reverse=True)[:5],
            "slowest_frames": sorted(timings, key=lambda r: r["latency_ms"], reverse=True)[:5],
            "foreground_owner_recorded": any((r.get("window") or {}).get("foreground")
                                             for r in records)}


def summarize(path: Path) -> dict:
    result = json.loads(path.read_text("utf-8"))
    unique = {}
    for stop in stop_records(result):
        unique[stop.get("id") or (stop["code"], stop.get("message"))] = stop
    stops = list(unique.values())
    alarms = [s for s in stops if s.get("severity") == "ALARM"]
    relevant = alarms or stops
    reason = result.get("error") or result.get("failure") or (
        relevant[-1].get("message") if relevant else "No failure detail recorded")
    if not isinstance(reason, str):
        reason = json.dumps(reason)
    category, next_step = classify(reason)
    clips = list(dict.fromkeys(s["clip_path"] for s in relevant if s.get("clip_path")))
    since = (result.get("before") or {}).get("captured_at")
    if since is None:
        since = next((r["captured_at"] for r in result.get("samples", [])
                      if r.get("captured_at") is not None), None)
    until = relevant[-1].get("time") if relevant else None
    summaries = [clip_summary(Path(clip), since, until) for clip in clips[-3:]]
    after = result.get("after") or {}
    return {"source": str(path.resolve()), "input_sent": False, "native_acceptance": False,
            "category": category, "reason": reason, "next_diagnostic": next_step,
            "reported_run_seconds": result.get("seconds"), "stops": relevant[-3:],
            "input_refusal": after.get("input_refusal"),
            "input_state": after.get("input_state"),
            "code_revision": (result.get("before") or {}).get("code_revision"),
            "health_readings": [sample.get("autopotter", {}).get("readings")
                                for sample in result.get("samples", [])
                                if sample.get("autopotter")][-3:],
            "clips": summaries,
            "limits": "Saved evidence only. Policy replay cannot reproduce OS focus, key delivery "
                      "or live capture scheduling. Timing outliers do not establish their cause."}


def run(path: Path, output: Path, *, replay_policy=False, config: Path = Path("config.toml")):
    began = time.perf_counter()
    report = summarize(path)
    # Analysis must never add files to a source recording or replace an earlier report.
    for clip in report["clips"]:
        if output.resolve().is_relative_to(Path(clip["path"]).resolve()):
            raise ValueError("Report output must be outside source recordings")
    output.mkdir(parents=True, exist_ok=False)
    report["policy_replays"] = []
    if replay_policy:
        from maplebot.config import Config
        from maplebot.replay import write_policy_diff

        loaded = Config.load(config)
        for index, clip in enumerate(report["clips"]):
            try:
                replay = write_policy_diff(Path(clip["path"]), output / f"policy-{index}", loaded)
                replay["comparison_only"] = True
            except (ValueError, OSError, KeyError, TypeError) as error:
                replay = {"error": str(error)}
            report["policy_replays"].append({"clip": clip["path"], **replay})
        if not report["clips"]:
            report["policy_replays"].append({"error": "No recorded clip path in check result"})
    report["analysis_seconds"] = round(time.perf_counter() - began, 3)
    (output / "summary.json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-policy", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    args = parser.parse_args()
    report = run(args.result, args.output, replay_policy=args.replay_policy, config=args.config)
    print(json.dumps({"report": str(args.output / "summary.json"),
                      "category": report["category"], "reason": report["reason"],
                      "analysis_seconds": report["analysis_seconds"], "input_sent": False,
                      "policy_replays": report["policy_replays"]}))
    return int(any(r.get("error") for r in report["policy_replays"]))


if __name__ == "__main__":
    raise SystemExit(main())
