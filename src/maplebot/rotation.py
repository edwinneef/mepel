"""Choose the next taught platform once combat finds its own platform clear. No I/O."""

from .navigation import RouteMap
from .perception import Detection


def visible_by_surface(graph: RouteMap, player_area: tuple[float, float],
                       player: Detection, monsters: list[Detection],
                       confidence: float) -> dict[str, int]:
    """Count fresh confident monsters per routable platform, placed relative to the player.

    A preference only: minimap feet are coarse, so a miscounted monster changes the
    chosen destination, never whether any input is allowed.
    """
    counts: dict[str, int] = {}
    for monster in monsters:
        if monster.tracked or monster.confidence < confidence:
            continue
        point = (player_area[0] + monster.box.center[0] - player.box.center[0],
                 player_area[1] + monster.box.feet - player.box.feet)
        for key in routable(graph):
            if graph.on_surface(key, point):
                counts[key] = counts.get(key, 0) + 1
                break
    return counts


def routable(graph: RouteMap) -> list[str]:
    """Platforms with a proven round trip, in saved map order. Ropes are never stops.

    Rotation moves without supervision, so it never relies on an unproven computed move.
    """
    return [p["id"] for p in graph.profile["platforms"] if p["id"] not in graph.trusted_excluded]


# Standing feet sit about 115 px above the chat box. On Tree Dungeon (2026-11-02) a 323 px
# drop fell behind it before the camera followed, so recognition lost the player mid-fall.
LEARN_MAX_FALL_PX = 100


def unproven_neighbours(graph: RouteMap, surface: str, *,
                        max_fall: float = LEARN_MAX_FALL_PX) -> dict[str, tuple[str, ...]]:
    """Platforms reachable by unproven computed moves: target -> the moves to try.

    A path is one move, or a move onto a rope and one off it; at least one is unproven.

    From inside the round-trip map only platforms outside it count. From a platform with
    no proven way back, moves into the map count too: proving one connects this platform
    (Tree Dungeon, 2026-11-02: stranded on fh320 beside an unproven drop to fh315).
    Only a supervised farming batch that opted in may try these.
    Moves falling more than `max_fall` below their launch are skipped: the player would
    leave the visible play area before the camera catches up.
    """
    known, platforms = set(routable(graph)), {p["id"] for p in graph.profile["platforms"]}
    ropes = {r["id"] for r in graph.profile["ropes"]}
    if surface not in known:
        known = set()

    def usable(edge) -> bool:
        return (edge.target not in graph.excluded and bool(edge.trace)
                and max(y for _, y in edge.trace) - edge.trace[0][1] <= max_fall)

    def wanted(target: str) -> bool:
        return target != surface and target in platforms and target not in known

    edges = sorted(graph.edges.values(), key=lambda e: e.id)
    found: dict[str, tuple[str, ...]] = {}
    for edge in edges:
        if edge.source == surface and edge.id not in graph.proven and wanted(edge.target) \
                and usable(edge):
            found.setdefault(edge.target, (edge.id,))
    for grab in edges:  # onto a rope, then off it: the only way up much of a tall map
        if grab.source != surface or grab.target not in ropes or not usable(grab):
            continue
        for leave in edges:
            if (leave.source == grab.target and wanted(leave.target) and usable(leave)
                    and {grab.id, leave.id} - graph.proven):
                found.setdefault(leave.target, (grab.id, leave.id))
    return found


class Rotation:
    def __init__(self, clear_seconds: float) -> None:
        self.clear_seconds = clear_seconds
        self.visited: dict[str, float] = {}
        self.clear_since: float | None = None
        self.destination: str | None = None
        # Clear for the full wait with nowhere to go: no proven route and nothing to try.
        self.stranded = False
        self.reason = "Rotation off"

    def reset(self, reason: str) -> None:
        self.visited, self.clear_since, self.destination = {}, None, None
        self.stranded = False
        self.reason = reason

    def arrived(self, surface: str, now: float) -> None:
        self.visited[surface], self.clear_since = now, None
        self.reason = "Arrived; fighting on this platform"

    def step(self, now: float, *, searching: bool, surface: str | None,
             platforms: list[str], visible: dict[str, int],
             edges: dict[str, int] | None = None,
             explore: dict[str, tuple[str, ...]] | None = None) -> str | None:
        """Return a destination after `clear_seconds` of searching on a known platform.

        `explore` lists neighbours reachable by one unproven move; one is tried before
        proven destinations, so a supervised batch grows the round-trip map.
        """
        self.stranded = False
        if not searching or surface not in platforms:
            self.clear_since = None
            self.reason = ("Platform unknown or outside the round-trip map; staying"
                           if searching else "Fighting on this platform")
            return None
        self.visited.setdefault(surface, now)
        if self.clear_since is None:
            self.clear_since = now
        explore = explore or {}
        others = [key for key in platforms if key != surface]
        if not others and not explore:
            self.stranded = now - self.clear_since >= self.clear_seconds
            self.reason = "No other routable platform; staying"
            return None
        if now - self.clear_since < self.clear_seconds:
            self.reason = f"Platform clear for {now - self.clear_since:.1f}s"
            return None
        if explore:
            self.destination = max(sorted(explore), key=lambda key: (
                visible.get(key, 0), -self.visited.get(key, float("-inf"))))
            self.visited[surface], self.clear_since = now, None
            self.reason = f"Platform clear; trying a new move to {self.destination}"
            return self.destination
        # Most visible monsters, then the platform left longest ago (never first), then the
        # shortest route.
        edges = edges or {}
        self.destination = max(others, key=lambda key: (
            visible.get(key, 0), -self.visited.get(key, float("-inf")), -edges.get(key, 0)))
        self.visited[surface], self.clear_since = now, None
        self.reason = f"Platform clear; moving to {self.destination}"
        return self.destination

    def snapshot(self) -> dict:
        return {"destination": self.destination, "clear_since": self.clear_since,
                "reason": self.reason}
