"""Pure, revision-bound navigation planning. No capture, filesystem or input authority."""

import copy
import hashlib
import json
import math
from collections import deque
from dataclasses import asdict, dataclass

from .map_teacher import problems, surface_y
from .moves import generate


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
             trusted_only: bool = False) -> Route:
        excluded = self.trusted_excluded if trusted_only else self.excluded
        for key in (origin, target):
            if key not in self.nodes or key in excluded:
                raise ValueError("Origin or target is outside the reachable round-trip map"
                                 + (" over proven moves" if trusted_only else ""))
        if not 1 <= max_edges <= 8:
            raise ValueError("Route edge budget must be between one and eight")
        queue, seen = deque([(origin, ())]), {origin}
        while queue:
            node, path = queue.popleft()
            if node == target:
                return Route(self.profile["id"], self.profile["revision"], self.fingerprint,
                             origin, target, path)
            if len(path) >= max_edges:
                continue
            for edge in self.edges.values():
                if trusted_only and edge.id not in self.proven:
                    continue
                if edge.source == node and edge.target not in seen:
                    seen.add(edge.target)
                    queue.append((edge.target, (*path, edge)))
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
