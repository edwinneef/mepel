"""Plan test journeys as separately bounded routes, ending each leg on a platform."""

from collections import deque

from maplebot.navigation import RouteMap

if __package__:
    from .navigation_replay import simulate
else:
    from navigation_replay import simulate


def legs(graph: RouteMap, origin: str, target: str, feet: tuple | None = None) -> list:
    """Find a sequence of ordinary <=8-edge routes; never raise the executor budget.

    Search is finite over platform/arrival pairs. Each continuation checks the
    connector from the previous landing, so it cannot walk across a portal zone.
    """
    platforms = [p["id"] for p in graph.profile["platforms"] if p["id"] not in graph.excluded]
    if origin not in platforms or target not in platforms:
        raise ValueError("Journey endpoints must be reachable platforms")
    queue, seen = deque([(origin, feet, [])]), {(origin, feet)}
    while queue:
        here, position, routes = queue.popleft()
        for destination in [target, *(p for p in platforms if p not in (here, target))]:
            if destination == here:
                return routes
            try:
                route = graph.plan(here, destination, origin_feet=position)
            except ValueError:
                continue
            # Preflight the bounded executor at the required observation cadence.
            # A geometrically connected route can still exhaust an edge deadline
            # during a long approach. Split those journeys at a different platform.
            if simulate(graph, route, fps=3, origin_feet=position)["stage"] != "arrived":
                continue
            if destination == target:
                return [*routes, route]
            landing = route.edges[-1].landing
            key = (destination, landing)
            if key not in seen:
                seen.add(key)
                queue.append((destination, landing, [*routes, route]))
    raise ValueError(f"No safe bounded journey from {origin} to {target}")


def expand(profile: dict, snapshot: dict, origin: str, targets: list[str]) -> dict:
    """Pin the saved geometry and honor edges disabled by the current engine."""
    graph = RouteMap.computed(profile)
    if graph.fingerprint != snapshot["map_hash"]:
        raise ValueError("Saved map differs from the engine; reload before checking routes")
    active = {e["id"] for e in snapshot["edges"]}
    graph = RouteMap.computed(profile, failed=set(graph.edges) - active)
    here, feet, expanded, journeys = origin, None, [], []
    for target in targets:
        routes = legs(graph, here, target, feet)
        destinations = [r.target for r in routes]
        journeys.append({"origin": here, "target": target, "legs": destinations,
                         "edge_counts": [len(r.edges) for r in routes]})
        expanded.extend(destinations)
        if routes:
            feet = routes[-1].edges[-1].landing
        here = target
    return {"map_hash": graph.fingerprint, "targets": expanded, "journeys": journeys}
