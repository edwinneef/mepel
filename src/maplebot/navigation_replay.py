"""Per-step Navigator evidence. Offline comparison never constructs an input backend."""

import copy
import json
import math
from dataclasses import asdict
from pathlib import Path

from .navigation import Edge, Route, RouteMap, map_hash
from .navigation_executor import Feedback, Navigator


def _json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return "inf" if value > 0 else "-inf"
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json(v) for v in value]
    return value


def snapshot(agent):
    graph = agent.graph
    return _json({
        "profile": copy.deepcopy(graph.profile),
        "edges": [asdict(e) for e in graph.edges.values()],
        "excluded": sorted(graph.excluded),
        "trusted_excluded": sorted(graph.trusted_excluded),
        "proven": sorted(graph.proven),
        "route": asdict(agent.route),
        "state": {k: v for k, v in vars(agent).items() if k not in {"graph", "route"}},
    })


def _edge(row):
    return Edge(**{**row, "launch": tuple(row["launch"]),
                   "landing": tuple(row["landing"]),
                   "trace": tuple(tuple(p) for p in row["trace"])})


def restore(saved):
    graph = object.__new__(RouteMap)
    graph.profile = copy.deepcopy(saved["profile"])
    graph.fingerprint = map_hash(graph.profile)
    graph.nodes = {p["id"]: p for p in graph.profile["platforms"] + graph.profile["ropes"]}
    graph.edges = {e["id"]: _edge(e) for e in saved["edges"]}
    for key in ("excluded", "trusted_excluded", "proven"):
        setattr(graph, key, set(saved[key]))
    row = saved["route"]
    route = Route(**{**row, "edges": tuple(_edge(e) for e in row["edges"])})
    agent = Navigator(graph, route, 0)
    if set(saved["state"]) != set(vars(agent)) - {"graph", "route"}:
        raise ValueError("Unsupported Navigator state fields")
    for key, value in saved["state"].items():
        if isinstance(value, str) and value in ("inf", "-inf"):
            value = float(value)
        if key == "last_feet" and value is not None:
            value = tuple(value)
        setattr(agent, key, value)
    return agent


def recorded_step(agent, feedback):
    before = snapshot(agent)
    motion = agent.step(feedback)
    return motion, {"version": 1, "before": before, "feedback": asdict(feedback),
                    "motion": _json(asdict(motion)), "after": snapshot(agent)}


def replay(directory: Path):
    compared, differences = 0, []
    previous_sequence, previous_now = -1, -math.inf
    for line in (directory / "decisions.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        record = row.get("navigation_step")
        if record is None:
            continue
        if record["version"] != 1:
            raise ValueError("Unsupported navigation record version")
        now = record["feedback"]["now"]
        if row["sequence"] <= previous_sequence or not math.isfinite(now) or now <= previous_now:
            raise ValueError("Navigation records must have increasing sequence and time")
        previous_sequence, previous_now = row["sequence"], now
        agent = restore(record["before"])
        motion = agent.step(Feedback(**record["feedback"]))
        fields = []
        if _json(asdict(motion)) != record["motion"]:
            fields.append("motion")
        if snapshot(agent) != record["after"]:
            fields.append("state")
        if fields:
            differences.append({"sequence": row["sequence"], "fields": fields})
        compared += 1
    if not compared:
        raise ValueError("No Navigator step records; legacy clips cannot prove navigation parity")
    return {"steps": compared, "differences": differences, "input_sent": False,
            "scope": "Per-step Navigator parity; excludes runtime gates and physical effects"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.clip)
    if args.output.resolve().is_relative_to(args.clip.resolve()):
        parser.error("Output must be outside the source clip")
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result))
    raise SystemExit(bool(result["differences"]))
