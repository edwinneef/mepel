"""Fit offline jump dynamics from saved observations; never capture or send input."""

import argparse
import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np

from tools.navigation_harness import Experiment


def valid_dispatch(event):
    start, end, issued = event.get("clock"), event.get("finished_clock"), event.get("issued_at")
    return (all(type(value) in (int, float) and math.isfinite(value) for value in (start, end))
            and 0 <= start <= end and (issued is None or type(issued) in (int, float)
                                      and math.isfinite(issued))
            and type(event.get("down")) is bool and isinstance(event.get("key"), str)
            and bool(event["key"]))


def history_snapshot(row, coverage):
    timing = row.get("input_timing") or {}
    if "history" not in timing:
        coverage["legacy_snapshots"] += 1
        return
    history = timing["history"]
    limit, last, dropped = (timing.get(name) for name in
                            ("history_limit", "history_last_sequence", "history_dropped"))
    if (not isinstance(history, list) or type(limit) is not int or limit <= 0
            or type(last) is not int or last < 0 or type(dropped) is not int or dropped < 0
            or len(history) != min(last, limit) or dropped != last - len(history)):
        coverage["invalid_snapshots"] += 1
        return
    if coverage["previous_last"] is not None and last < coverage["previous_last"]:
        coverage["ambiguous_lifetime"] = True
    coverage["previous_last"] = last
    coverage["last"] = max(coverage["last"], last)
    coverage["evictions_seen"] = max(coverage["evictions_seen"], dropped)
    coverage["history_snapshots"] += 1
    for sequence, event in enumerate(history, dropped + 1):
        if (not isinstance(event, dict) or type(event.get("sequence")) is not int
                or event["sequence"] != sequence or not valid_dispatch(event)):
            coverage["invalid_snapshots"] += 1
            continue
        signature = tuple(event.get(k) for k in
                          ("clock", "finished_clock", "key", "down", "issued_at"))
        if sequence in coverage["seen"] and coverage["seen"][sequence] != signature:
            coverage["ambiguous_lifetime"] = True
        coverage["seen"][sequence] = signature


def history_report(coverage, source):
    missing, next_sequence = [], 1
    previous_clock = float("-inf")
    # Work scales with recorded events, not potentially huge sequence counters.
    for sequence in sorted(coverage["seen"]):
        clock = coverage["seen"][sequence][0]
        if clock < previous_clock:
            coverage["ambiguous_lifetime"] = True
        previous_clock = clock
        if sequence > next_sequence:
            missing.append([next_sequence, sequence - 1])
        next_sequence = sequence + 1
    if next_sequence <= coverage["last"]:
        missing.append([next_sequence, coverage["last"]])
    unknown = (coverage["legacy_snapshots"] or coverage["invalid_snapshots"]
               or coverage["ambiguous_lifetime"] or not coverage["history_snapshots"])
    ambiguous = coverage["ambiguous_lifetime"]
    return {"source": source, "status": "unknown" if unknown else "gaps" if missing else "complete",
            "missing_ranges": None if ambiguous else missing,
            "missing_events": None if ambiguous else sum(b - a + 1 for a, b in missing),
            "observed_events": len(coverage["seen"]), "last_sequence": coverage["last"],
            "evictions_seen": coverage["evictions_seen"], "ambiguous_lifetime": ambiguous,
            "legacy_snapshots": coverage["legacy_snapshots"],
            "invalid_snapshots": coverage["invalid_snapshots"]}


def event_clocks(row, basis, collected):
    """Read successful dispatch observations; never reconstruct legacy clocks."""
    timing = row.get("input_timing") or {}
    values = timing.get("history", timing.get("events", []))
    if not isinstance(values, list):
        collected["invalid_event_snapshots"] += 1
        return
    for event in values:
        if not isinstance(event, dict):
            collected["invalid_event_snapshots"] += 1
            continue
        if "clock" not in event:
            collected["legacy_event_snapshots"] += 1
            continue
        if not valid_dispatch(event):
            collected["invalid_event_snapshots"] += 1
            continue
        value = {"basis": basis, "key": event["key"], "down": event["down"],
                 "clock": event["clock"], "finished_clock": event["finished_clock"],
                 "issued_at": event.get("issued_at")}
        key = (*basis, event["key"], event["clock"])
        if key in collected["events"] and collected["events"][key] != value:
            collected["conflicts"].add(key)
        else:
            collected["events"][key] = value


def align_events(samples, collected, max_gap=.3):
    """Associate event intervals with neighboring observations, not inferred effects."""
    grouped = {}
    for sample in samples:
        grouped.setdefault(tuple(sample["basis"]), []).append(sample)
    clocks = {basis: [s["t"] for s in group] for basis, group in grouped.items()}
    aligned = []
    for key, event in sorted(collected["events"].items(), key=lambda item: item[1]["clock"]):
        if key in collected["conflicts"]:
            continue
        basis = tuple(event["basis"])
        group, times = grouped.get(basis, []), clocks.get(basis, [])
        left = bisect_right(times, event["clock"]) - 1
        right = bisect_left(times, event["finished_clock"])
        before = group[left] if left >= 0 else None
        after = group[right] if right < len(group) else None
        supported = (before is not None and after is not None and before["feet"] is not None
                     and after["feet"] is not None and event["clock"] - before["t"] <= max_gap
                     and after["t"] - event["finished_clock"] <= max_gap)
        aligned.append({**event, "status": "aligned" if supported else "observation_gap",
                        "before_clock": before["t"] if before else None,
                        "after_clock": after["t"] if after else None,
                        "observed_delta": [after["feet"][i] - before["feet"][i] for i in (0, 1)]
                        if supported else None})
    return {"events": aligned, "unique_events": len(aligned),
            "aligned_events": sum(e["status"] == "aligned" for e in aligned),
            "conflicting_events": len(collected["conflicts"]),
            "legacy_event_snapshots": collected["legacy_event_snapshots"],
            "invalid_event_snapshots": collected["invalid_event_snapshots"],
            "clock_source": "perf_counter; same domain as capture_clock",
            "scope": "Neighboring observations only; no causal motion or input-effect claim"}


def observations(root, *, events=None):
    """Merge overlapping clips by capture clock, keeping inconsistent copies out."""
    found, sources, conflicts = {}, [], set()
    for path in sorted(root.glob("*/decisions.jsonl")):
        raw = path.read_bytes()
        sources.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        coverage = {"seen": {}, "last": 0, "previous_last": None, "evictions_seen": 0,
                    "ambiguous_lifetime": False, "legacy_snapshots": 0,
                    "invalid_snapshots": 0, "history_snapshots": 0}
        for line in raw.decode("utf-8").splitlines():
            row = json.loads(line)
            if events is not None:
                history_snapshot(row, coverage)
            position, player = row.get("position") or {}, row.get("player") or {}
            clock, feet = row.get("capture_clock"), position.get("feet")
            if (not position.get("area_id") or type(clock) not in (int, float)
                    or not math.isfinite(clock)):
                continue
            key = (position["area_id"], clock)
            valid = (row.get("focused") and feet and len(feet) == 2
                     and all(isinstance(v, (int, float)) and math.isfinite(v) for v in feet)
                     and player.get("confidence", 0) >= .85 and not player.get("tracked")
                     and not position.get("provisional") and position.get("calibrated")
                     and math.isfinite(clock))
            sample = {"area": key[0], "t": clock, "feet": feet if valid else None,
                      "basis": [key[0], ":".join(player.get("template", "").split(":")[:2]),
                                ((position.get("calibration") or {}).get("saved") or {})
                                .get("captured_at")],
                      "surface": position.get("surface_id") if valid else None,
                      "frame": row.get("frame"), "source": str(path.parent),
                      "jump": any(e.get("action") == "jump" and e.get("down")
                                  for e in (row.get("input_timing") or {})
                                  .get("schedule", {}).get("events", []))
                      if (row.get("input_timing") or {}).get("schedule") else False}
            if events is not None:
                event_clocks(row, sample["basis"], events)
            if key in found and (found[key]["feet"], found[key]["surface"]) != (
                    sample["feet"], sample["surface"]):
                conflicts.add(key)
            else:
                found[key] = sample
        if events is not None:
            events["coverage"].append(history_report(coverage, str(path)))
    for key in conflicts:
        found[key]["feet"] = None
    return sorted(found.values(), key=lambda s: (s["area"], s["t"])), sources, len(conflicts)


def flights(samples, max_gap=.3):
    ground, air, previous = None, [], None
    for sample in samples:
        if (not sample["feet"] or previous is not None and (
                sample["basis"] != previous["basis"]
                or sample["t"] - previous["t"] > max_gap)):
            ground, air = None, []
        if sample["feet"]:
            if sample["surface"]:
                if air and ground:
                    yield ground, air, sample
                ground, air = sample, []
            elif ground:
                air.append(sample)
        previous = sample


def fit(ground, air, landing):
    """Fit training frames and evaluate interleaved held-out observations."""
    if len(air) < 6 or not any(s["jump"] for s in [ground, *air]):
        return {"accepted": False, "reason": "insufficient airborne frames or jump command"}
    t = np.array([s["t"] - air[0]["t"] for s in air])
    y = np.array([s["feet"][1] for s in air])
    if t[-1] < .4:
        return {"accepted": False, "reason": "flight too short"}
    train = np.arange(len(t)) % 2 == 0
    design = np.column_stack((t * t / 2, t, np.ones(len(t))))
    gravity, velocity, intercept = np.linalg.lstsq(design[train], y[train], rcond=None)[0]
    peak = -velocity / gravity if gravity > 0 else -1
    energy = velocity ** 2 - 2 * gravity * (intercept - ground["feet"][1])
    if not (100 <= gravity <= 5000 and .05 < peak < t[-1] - .05 and energy > 0):
        return {"accepted": False, "reason": "no supported rising-and-falling ballistic arc"}
    speed = float(np.sqrt(energy))
    launch = (-speed - velocity) / gravity
    if not ground["t"] - air[0]["t"] - .15 <= launch <= 0:
        return {"accepted": False, "reason": "takeoff inconsistent with preceding contact"}
    predicted = design @ np.array([gravity, velocity, intercept])
    error = float(np.sqrt(np.mean((predicted[~train] - y[~train]) ** 2)))
    # Fair comparison: refit the default gravity's nuisance velocity and offset
    # on the same training frames; evaluate on exactly the same held-out frames.
    default = Experiment().gravity
    linear = design[:, 1:]
    baseline = np.linalg.lstsq(linear[train], y[train] - default * t[train] ** 2 / 2,
                               rcond=None)[0]
    baseline_error = float(np.sqrt(np.mean((default * t[~train] ** 2 / 2
                                          + linear[~train] @ baseline - y[~train]) ** 2)))
    return {"accepted": error <= 10, "reason": "accepted" if error <= 10 else "holdout error >10px",
            "gravity": round(float(gravity), 4), "jump_speed": round(speed, 4),
            "holdout_rmse_px": round(error, 4), "default_gravity_holdout_rmse_px":
            round(baseline_error, 4), "frames": len(air), "train_frames": int(sum(train)),
            "holdout_frames": int(sum(~train)), "area": ground["area"],
            "basis": ground["basis"],
            "start": ground["t"], "end": landing["t"], "source": air[0]["source"],
            "frame_names": [s["frame"] for s in air]}


def calibrate(root):
    events = {"events": {}, "conflicts": set(), "legacy_event_snapshots": 0, "coverage": [],
              "invalid_event_snapshots": 0}
    samples, sources, conflicts = observations(root, events=events)
    alignment = align_events(samples, events)
    reports = events["coverage"]
    alignment["history_coverage"] = {
        "status": ("unknown" if not reports or any(r["status"] == "unknown" for r in reports)
                   else "gaps" if any(r["status"] == "gaps" for r in reports) else "complete"),
        "clips": reports,
        "scope": "Per clip, sequence 1 through last counter; no cross-clip lifetime merging",
        "limitations": "Prefix may predate recording; resets/conflicts mean unknown lifetime."
    }
    windows = list(flights(samples))
    candidates = [fit(*flight) for flight in windows]
    accepted = [c for c in candidates if c["accepted"]]
    parameters = {}
    # Do not promote a single arc or inconsistent population into a model preset.
    if len(accepted) >= 2 and len({tuple(c["basis"]) for c in accepted}) == 1:
        for key in ("gravity", "jump_speed"):
            values = [c[key] for c in accepted]
            if max(values) / min(values) <= 1.5:
                parameters[key] = round(float(np.median(values)), 4)
    rises = []
    for ground, air, _ in windows:
        if len(air) < 4 or not any(s["jump"] for s in [ground, *air]):
            continue
        heights = [s["feet"][1] for s in air]
        peak = int(np.argmin(heights))
        rise = ground["feet"][1] - min(heights)
        if 0 < peak < len(air) - 1 and rise > 20 and heights[-1] > min(heights):
            rises.append({"area": ground["area"], "start": ground["t"],
                          "basis": ground["basis"],
                          "source": air[0]["source"], "rise_px": round(rise, 4)})
    constraints = {}
    # Only a height constraint: this cannot identify gravity and takeoff speed separately.
    if len(rises) >= 2 and len({tuple(r["basis"]) for r in rises}) == 1:
        values = [r["rise_px"] for r in rises]
        constraints["jump_rise_px"] = {"min": min(values), "max": max(values),
                                       "median": float(np.median(values)),
                                       "margin_px": 16, "flights": rises}
    return {"schema_version": 1, "scope": "Recorded world-position ballistic fits; offline only",
            "input_sent": False, "native_acceptance": False, "sources": sources,
            "unique_observations": len(samples), "conflicting_duplicates": conflicts,
            "candidates": candidates, "accepted_flights": len(accepted), "parameters": parameters,
            "constraints": constraints,
            "input_alignment": alignment,
            "unidentified": [key for key in ("speed", "acceleration", "braking", "jump_speed",
                                             "gravity") if key not in parameters],
            "limitations": ["Positions are quantized minimap estimates, not contact proof",
                            "Saved jump schedules do not establish absolute input timing",
                            "Interleaved holdout is within each flight, not a new independent clip",
                            "Event alignment alone does not identify horizontal dynamics",
                            "Unidentified fields retain defaults; global settings unchanged"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings", type=Path, default=Path("data/recordings"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    if args.output.resolve().is_relative_to(protected) or args.output.resolve().is_relative_to(
            args.recordings.resolve()):
        parser.error("Output must stay outside saved data and recordings")
    report = calibrate(args.recordings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ("accepted_flights", "parameters", "unidentified", "constraints")}))


if __name__ == "__main__":
    main()
