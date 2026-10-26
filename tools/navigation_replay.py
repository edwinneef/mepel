"""Offline saved-anchor decision smoke. No capture, controller or native input."""

import argparse
import json
import math
from pathlib import Path

from maplebot.navigation import Route, RouteMap
from maplebot.navigation_evidence import build_evidence
from maplebot.navigation_executor import Feedback, Navigator


def simulate(graph: RouteMap, route: Route) -> dict:
    agent = Navigator(graph, route, 0)
    now = 0.0
    proposals = 0

    def feed(point, surface):
        nonlocal now, proposals
        motion = agent.step(Feedback(now, graph.fingerprint, point, surface, True))
        proposals += bool(motion.holds or motion.vertical)
        now += .1

    previous = route.edges[0].launch
    for edge in route.edges:
        for _ in range(6):
            feed(previous, edge.source)
        # Synthetic same-surface connector tests approach decisions, not travel speed.
        count = max(1, math.ceil(math.dist(previous, edge.launch) / 16))
        for i in range(1, count + 1):
            feed(tuple(previous[a] + (edge.launch[a] - previous[a]) * i / count
                       for a in (0, 1)), edge.source)
        for point in edge.trace[1:]:
            feed(point, edge.target if point == edge.landing else None)
        for _ in range(6):
            feed(edge.landing, edge.target)
        previous = edge.landing
    return {"stage": agent.stage, "reason": agent.reason, "proposals": proposals}


def replay(profile: dict, directory: Path) -> dict:
    graph = RouteMap(profile, build_evidence(profile, directory))
    results, compositions = [], []
    for edge in graph.edges.values():
        route = Route(profile["id"], profile["revision"], graph.fingerprint,
                      edge.source, edge.target, (edge,))
        results.append({"edge": edge.id, "source": edge.evidence,
                        "samples": len(edge.trace), **simulate(graph, route)})
    for node in graph.nodes:
        if node in graph.excluded:
            continue
        route = graph.plan(graph.home, node)
        if len(route.edges) == 2 and all(e.kind == "climb" for e in route.edges):
            compositions.append({"target": node, "edges": [e.id for e in route.edges],
                                 **simulate(graph, route)})
    return {"input_sent": False, "native_acceptance": False,
            "scope": "Saved XY traces; synthetic clock/surfaces/connectors; no contact proof",
            "map": graph.snapshot(), "edges": results, "compositions": compositions}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(json.loads(args.profile.read_text("utf-8")), args.profile.parent)
    args.output.write_text(json.dumps(result, indent=2), "utf-8")
    print(json.dumps({"edges": len(result["edges"]), "input_sent": False,
                      "stages": {stage: sum(e["stage"] == stage for e in result["edges"])
                                 for stage in {e["stage"] for e in result["edges"]}}}))
    raise SystemExit(any(e["stage"] != "arrived"
                         for e in result["edges"] + result["compositions"]))
