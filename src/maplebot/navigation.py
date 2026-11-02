"""Pure, revision-bound navigation planning. No capture, filesystem or input authority."""

import copy
import hashlib
import heapq
import itertools
import json
import math
from dataclasses import asdict, dataclass

import numpy as np

from .moves import generate

FLOOR_PX = 8  # platforms this close to the lowest height are the same floor level


def surface_y(platform: dict, x: float) -> float:
    """Height of a platform at x, following its bends when it has them."""
    points = platform.get("points") or [platform["start"], platform["end"]]
    points = sorted(points, key=lambda p: p["x"])
    if points[0]["x"] == points[-1]["x"]:
        return points[0]["y"]
    return float(np.interp(x, [p["x"] for p in points], [p["y"] for p in points]))


def problems(platforms: list[dict], ropes: list[dict], links: list[dict]) -> dict:
    """Surfaces the floor cannot reach, and surfaces with no way back to it.

    The floor ("home") is the lowest platform of the largest group of platforms that
    can all reach each other; among equally low ones, the widest. A one-way pit below
    that group is then stranded rather than the home that excludes everything else.
    Heights can carry sub-pixel noise, so "equally low" allows FLOOR_PX.
    """
    if not platforms:
        return {"home": None, "unreachable": [], "stranded": []}

    def level(item: dict) -> float:
        return (item["start"]["y"] + item["end"]["y"]) / 2

    nodes = [item["id"] for item in (*platforms, *ropes)]
    forward: dict[str, set[str]] = {key: set() for key in nodes}
    backward: dict[str, set[str]] = {key: set() for key in nodes}
    for link in links:
        forward[link["from"]].add(link["to"])
        backward[link["to"]].add(link["from"])

    def reach(start: str, edges: dict[str, set[str]]) -> set[str]:
        seen, todo = {start}, [start]
        while todo:
            for key in edges[todo.pop()] - seen:
                seen.add(key)
                todo.append(key)
        return seen

    floors = {item["id"] for item in platforms}
    groups = {frozenset(reach(item["id"], forward) & reach(item["id"], backward) & floors)
              for item in platforms}
    # Most platforms wins; equally large groups pool, so the original floor rule decides.
    size = max(len(keys) for keys in groups)
    pool = set().union(*(keys for keys in groups if len(keys) == size))
    members = [item for item in platforms if item["id"] in pool]
    lowest = max(level(p) for p in members)
    home = max((p for p in members if lowest - level(p) <= FLOOR_PX),
               key=lambda p: p["end"]["x"] - p["start"]["x"])["id"]
    reached, returns = reach(home, forward), reach(home, backward)
    return {"home": home, "unreachable": [key for key in nodes if key not in reached],
            "stranded": [key for key in nodes if key in reached and key not in returns]}


def map_hash(profile: dict) -> str:
    return hashlib.sha256(json.dumps(profile, sort_keys=True, allow_nan=False).encode()).hexdigest()


def intersects(a: tuple, b: tuple, rect: dict) -> bool:
    """Segment versus a rectangle expanded for player body and tracking uncertainty."""
    low = (rect["x"] - 34, rect["y"] - 12)
    high = (rect["x"] + rect["width"] + 34, rect["y"] + rect["height"] + 76)
    first, last = 0.0, 1.0
    for axis in (0, 1):
        delta = b[axis] - a[axis]
        if abs(delta) < 1e-9:
            if not low[axis] <= a[axis] <= high[axis]:
                return False
        else:
            start, end = sorted(((low[axis] - a[axis]) / delta,
                                 (high[axis] - a[axis]) / delta))
            first, last = max(first, start), min(last, end)
            if first > last:
                return False
    return True


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    kind: str
    launch: tuple[float, float]
    landing: tuple[float, float]
    trace: tuple[tuple[float, float], ...]
    evidence: str


@dataclass(frozen=True)
class Route:
    area_id: str
    revision: int
    fingerprint: str
    origin: str
    target: str
    edges: tuple[Edge, ...]

    def snapshot(self) -> dict:
        return asdict(self)


def required_poses(route: Route, ropes: set[str]) -> set[str]:
    """Pose/facing pairs the player shows on a route; drops may face either way."""
    poses = {"walk/left", "walk/right"}
    for edge in route.edges:
        side = "left" if edge.landing[0] < edge.launch[0] else "right"
        if edge.kind == "jump":
            poses.add(f"air/{side}")
        elif edge.kind == "drop":
            poses.add("air/any")
        elif edge.kind == "climb":
            poses.add("climb/back")
            if edge.landing[1] < edge.launch[1] and edge.source not in ropes:
                # The jump onto a rope or ladder shows the sideways jump, then the climb.
                straight = abs(edge.landing[0] - edge.launch[0]) < 8
                poses.add("air/any" if straight else f"air/{side}")
    return poses


def pose_gaps(required: set[str], verified: set[str]) -> list[str]:
    """Required poses without offline-verified recognition."""
    return sorted(pose for pose in required if pose not in verified and not (
        pose.endswith("/any") and any(v.startswith(pose[:-3]) for v in verified)))


class RouteMap:
    def __init__(self, profile: dict, evidence: dict, *, links: list[dict] | None = None,
                 proven: set[str] | None = None) -> None:
        """Edges from recorded or computed evidence for `links` (default: the saved links).

        `proven` names the edges trusted without supervision; None trusts every usable
        edge, as recorded teaching evidence always was.
        """
        profile = copy.deepcopy(profile)
        self.profile = profile
        self.fingerprint = map_hash(profile)
        links = profile["links"] if links is None else links
        if (evidence.get("area_id") != profile["id"]
                or evidence.get("revision") != profile["revision"]
                or evidence.get("map_hash") != self.fingerprint):
            raise ValueError("Navigation evidence does not match the active map revision")
        self.nodes = {p["id"]: p for p in profile["platforms"] + profile["ropes"]}
        issue = problems(profile["platforms"], profile["ropes"], links)
        self.home = issue["home"]
        self.excluded = set(issue["unreachable"] + issue["stranded"])
        self.edges: dict[str, Edge] = {}
        self.disabled: dict[str, str] = {}
        for link in links:
            row = evidence.get("edges", {}).get(link["id"])
            reason = None
            if link["from"] in self.excluded or link["to"] in self.excluded:
                reason = "Outside the home round-trip component"
            elif not row or row.get("from") != link["from"] or row.get("to") != link["to"]:
                reason = "No matching recorded movement anchors"
            elif row.get("kind") != link["kind"] or not row.get("source"):
                reason = "Movement provenance does not match the link"
            elif row.get("missing_checks") or row.get("max_gap", math.inf) > 1:
                reason = "Movement trace has missing or discontinuous observations"
            if reason:
                self.disabled[link["id"]] = reason
                continue
            trace = tuple(tuple(p) for p in row.get("trace", []))
            if (len(trace) < 2 or any(len(p) != 2 or not all(
                    type(v) in (int, float) and math.isfinite(v) for v in p) for p in trace)):
                self.disabled[link["id"]] = "Invalid movement trace"
                continue
            launch, landing = trace[0], trace[-1]
            if (not self.on_surface(link["from"], launch)
                    or not self.on_surface(link["to"], landing)):
                self.disabled[link["id"]] = "Recorded anchors do not match the learned surfaces"
                continue
            reason = self.path_blocker(trace)
            if reason:
                self.disabled[link["id"]] = reason
                continue
            self.edges[link["id"]] = Edge(link["id"], link["from"], link["to"], link["kind"],
                                           launch, landing, trace, row["source"])
        usable = [{"from": e.source, "to": e.target} for e in self.edges.values()]
        safe = problems(profile["platforms"], profile["ropes"], usable)
        self.excluded.update(safe["unreachable"] + safe["stranded"])
        for key, edge in list(self.edges.items()):
            if edge.source in self.excluded or edge.target in self.excluded:
                self.disabled[key] = "No evidenced round-trip route through this surface"
                del self.edges[key]
        self.proven = set(self.edges) if proven is None else set(self.edges) & set(proven)
        trusted = [{"from": e.source, "to": e.target} for k, e in self.edges.items()
                   if k in self.proven]
        safe = problems(profile["platforms"], profile["ropes"], trusted)
        # Unsupervised movement (rotation) may only use proven edges and their surfaces.
        self.trusted_excluded = self.excluded | set(safe["unreachable"] + safe["stranded"])

    @classmethod
    def computed(cls, profile: dict, proven: set[str] = frozenset(),
                 failed: set[str] = frozenset()) -> "RouteMap":
        """Edges computed from an imported map's geometry; `failed` ones are left out."""
        moves = [m for m in generate(profile) if m.id not in failed]
        evidence = {"area_id": profile["id"], "revision": profile["revision"],
                    "map_hash": map_hash(profile),
                    "edges": {m.id: {"from": m.source, "to": m.target, "kind": m.kind,
                                     "source": "proven" if m.id in proven else "computed",
                                     "missing_checks": 0, "max_gap": 0,
                                     "trace": [list(p) for p in m.trace]} for m in moves}}
        return cls(profile, evidence, links=[m.link for m in moves], proven=set(proven))

    def on_surface(self, surface: str, feet: tuple, *, tolerance: float = 24) -> bool:
        node = self.nodes.get(surface)
        if not node or len(feet) != 2 or not all(math.isfinite(v) for v in feet):
            return False
        a, b = node["start"], node["end"]
        if a["x"] == b["x"]:
            return abs(feet[0] - a["x"]) <= 12 and a["y"] - 1 <= feet[1] <= b["y"] + 1
        x0, x1 = sorted((a["x"], b["x"]))
        return x0 <= feet[0] <= x1 and abs(feet[1] - surface_y(node, feet[0])) <= tolerance

    def path_blocker(self, points: tuple) -> str | None:
        boundary = self.profile["boundary"]
        for x, y in points:
            if not (boundary["x"] + 34 <= x <= boundary["x"] + boundary["width"] - 34
                    and boundary["y"] + 76 <= y <= boundary["y"] + boundary["height"] - 12):
                return "Player footprint leaves the hunting boundary"
        for zone in self.profile["zones"]:
            if any(intersects(a, b, zone["rect"])
                   for a, b in zip(points, points[1:], strict=False)):
                return f"Movement crosses {zone['kind']} zone {zone['id']}"
        return None

    def plan(self, origin: str, target: str, *, max_edges: int = 8,
             trusted_only: bool = False, origin_feet: tuple | None = None) -> Route:
        excluded = self.trusted_excluded if trusted_only else self.excluded
        # A trusted route may leave a one-way origin, but only over proven moves.
        for key, barred in ((origin, self.excluded), (target, excluded)):
            if key not in self.nodes or key in barred:
                raise ValueError("Origin or target is outside the reachable round-trip map"
                                 + (" over proven moves" if trusted_only else ""))
        if not 1 <= max_edges <= 8:
            raise ValueError("Route edge budget must be between one and eight")
        # Fewer transitions can hide a long cross-map approach that exhausts an
        # edge deadline. Rank actual travel plus a modest settling cost instead.
        # This is a preference only: input deadlines and the edge budget stay fixed.
        serial = itertools.count()
        queue = [(0.0, next(serial), origin, (), origin_feet)]
        best = {}
        while queue:
            cost, _, node, path, feet = heapq.heappop(queue)
            if node == target:
                return Route(self.profile["id"], self.profile["revision"], self.fingerprint,
                             origin, target, path)
            if len(path) >= max_edges:
                continue
            for edge in self.edges.values():
                if trusted_only and edge.id not in self.proven:
                    continue
                if edge.source != node:
                    continue
                if feet is not None and self.path_blocker((feet, edge.launch)):
                    continue
                travel = (math.dist(feet, edge.launch) if feet is not None else 0) + sum(
                    math.dist(a, b) for a, b in zip(edge.trace, edge.trace[1:], strict=False))
                candidate = cost + travel + 100
                # Keep different remaining budgets and arrival positions distinct.
                key = (edge.id, len(path) + 1)
                if candidate >= best.get(key, math.inf):
                    continue
                best[key] = candidate
                heapq.heappush(queue, (candidate, next(serial), edge.target,
                                      (*path, edge), edge.landing))
        raise ValueError("No evidenced safe route within the eight-edge budget")

    def verify(self, route: Route) -> None:
        if (route.area_id != self.profile["id"] or route.revision != self.profile["revision"]
                or route.fingerprint != self.fingerprint):
            raise ValueError("Map changed; preview the route again")

    def snapshot(self) -> dict:
        return {"area_id": self.profile["id"], "revision": self.profile["revision"],
                "map_hash": self.fingerprint, "home": self.home,
                "nodes": [{"id": k, "name": v.get("name", k),
                           "kind": "rope" if v in self.profile["ropes"] else "platform",
                           "excluded": k in self.excluded,
                           "unproven": k in self.trusted_excluded and k not in self.excluded}
                          for k, v in self.nodes.items()],
                "usable_edges": len(self.edges), "proven_edges": len(self.proven),
                "edges": [{"id": e.id, "from": e.source, "to": e.target, "kind": e.kind,
                           "proven": e.id in self.proven} for e in self.edges.values()],
                "disabled_edges": self.disabled}
