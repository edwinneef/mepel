"""Saved farming circuits. Drafts never grant input authority."""

import copy
import json
import os
import re
import threading
from pathlib import Path

from .moves import generate
from .navigation import RouteMap, map_hash

MAX_BYTES = 64_000


def preview_graph(profile: dict, proofs) -> RouteMap:
    """Build an input-free preview, independent of the map currently being tracked."""
    if not profile.get("public_map"):
        raise ValueError("Import this map before building farming circuits")
    fingerprint = map_hash(profile)
    moves = generate(profile)
    current = {move.id: move for move in moves}
    proven = proofs.load(profile["id"], fingerprint)
    missed = {key for key, shape in proofs.failures(profile["id"], fingerprint).items()
              if key in current and key not in proven and shape["kind"] == current[key].kind
              and shape["trace"] == [list(point) for point in current[key].trace]}
    return RouteMap.computed(profile, proven, missed, moves,
                             proofs.geometry(profile["id"], fingerprint))


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Use 1-80 letters, numbers, underscores or hyphens for route IDs")
    return value


def draft(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Route must be an object")
    if len(json.dumps(value, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("Route is too large")
    if value.get("version") != 1 or type(value.get("revision")) is not int:
        raise ValueError("Unsupported route version or revision")
    if value["revision"] < 0:
        raise ValueError("Invalid revision")
    allowed = {"version", "revision", "id", "name", "area_id", "map_hash", "stops", "loop",
               "disabled_edges"}
    if set(value) - allowed:
        raise ValueError("Unsupported route fields or movement actions")
    for key in ("id", "area_id"):
        identifier(value.get(key))
    if not isinstance(value.get("name"), str) or not 1 <= len(value["name"].strip()) <= 100:
        raise ValueError("Give this route a name (1-100 characters)")
    if not isinstance(value.get("map_hash"), str) or len(value["map_hash"]) != 64:
        raise ValueError("Route needs a map geometry fingerprint")
    stops = value.get("stops")
    if not isinstance(stops, list) or not 2 <= len(stops) <= 100:
        raise ValueError("Choose between 2 and 100 farming stops")
    for stop in stops:
        identifier(stop)
    if any(a == b for a, b in zip(stops, stops[1:], strict=False)):
        raise ValueError("Consecutive farming stops must differ")
    if type(value.get("loop")) is not bool:
        raise ValueError("Loop must be true or false")
    if value["loop"] and stops[0] == stops[-1]:
        raise ValueError("Loop closes automatically; remove the repeated final stop")
    disabled = value.get("disabled_edges", [])
    if not isinstance(disabled, list) or len(disabled) > 500:
        raise ValueError("Invalid movement connection exclusions")
    for edge in disabled:
        identifier(edge)
    return copy.deepcopy(value)


def compile_route(value: object, graph: RouteMap) -> dict:
    route = draft(value)
    connections = [{"id": e.id, "kind": e.kind, "from": e.source, "to": e.target,
                    "launch": e.launch, "landing": e.landing} for e in graph.edges.values()]
    graph = restrict_graph(route, graph)
    errors, legs = [], []
    if route["area_id"] != graph.profile["id"] or route["map_hash"] != graph.fingerprint:
        errors.append("Map geometry changed; bind this draft to the current map before validating")
    platforms = {p["id"] for p in graph.profile["platforms"]}
    for stop in route["stops"]:
        if stop not in platforms:
            errors.append(f"Missing platform: {stop}")
    pairs = list(zip(route["stops"], route["stops"][1:], strict=False))
    if route["loop"]:
        pairs.append((route["stops"][-1], route["stops"][0]))
    for origin, target in pairs:
        try:
            planned = graph.plan(origin, target, trusted_only=True)
            legs.append({"origin": origin, "target": target,
                         "edges": [{"id": e.id, "kind": e.kind, "from": e.source,
                                    "to": e.target, "launch": e.launch, "landing": e.landing}
                                   for e in planned.edges]})
        except ValueError as error:
            errors.append(f"{origin} to {target}: {error}")
    return {"route": route, "valid": not errors, "errors": errors, "legs": legs,
            "connections": connections}


def restrict_graph(route: dict, graph: RouteMap) -> RouteMap:
    """Remove user-excluded candidates without adding edges or relaxing planner gates."""
    result = copy.copy(graph)
    disabled = set(route.get("disabled_edges", []))
    result.edges = {key: edge for key, edge in graph.edges.items() if key not in disabled}
    return result


class FarmingRouteStore:
    def __init__(self, directory: Path):
        self.directory = directory / "farming-routes"
        self.lock = threading.RLock()

    def load(self, route_id: str) -> dict:
        path = self.directory / f"{identifier(route_id)}.json"
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Route file is too large")
            route = draft(json.loads(path.read_text("utf-8")))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Route missing or unreadable; preserved unchanged") from error
        if route["id"] != route_id:
            raise ValueError("Route file ID does not match its name")
        return route

    def list(self, area_id: str) -> dict:
        identifier(area_id)
        routes, errors = [], []
        with self.lock:
            for path in sorted(self.directory.glob("*.json")):
                try:
                    route = self.load(path.stem)
                    if route["area_id"] == area_id:
                        routes.append(route)
                except ValueError as error:
                    errors.append(f"{path.name}: {error}")
        return {"routes": routes, "errors": errors}

    def save(self, value: object) -> dict:
        route = draft(value)
        with self.lock:
            path = self.directory / f"{route['id']}.json"
            previous = self.load(route["id"]) if path.exists() else None
            if route["revision"] != (previous["revision"] if previous else 0):
                raise ValueError("Route changed elsewhere; reload before saving")
            route["revision"] += 1
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            try:
                with temporary.open("w", encoding="utf-8") as stream:
                    json.dump(route, stream, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return route

