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
    """Platforms with an evidenced round trip, in saved map order. Ropes are never stops."""
    return [p["id"] for p in graph.profile["platforms"] if p["id"] not in graph.excluded]


class Rotation:
    def __init__(self, clear_seconds: float) -> None:
        self.clear_seconds = clear_seconds
        self.visited: dict[str, float] = {}
        self.clear_since: float | None = None
        self.destination: str | None = None
        self.reason = "Rotation off"

    def reset(self, reason: str) -> None:
        self.visited, self.clear_since, self.destination = {}, None, None
        self.reason = reason

    def arrived(self, surface: str, now: float) -> None:
        self.visited[surface], self.clear_since = now, None
        self.reason = "Arrived; fighting on this platform"

    def step(self, now: float, *, searching: bool, surface: str | None,
             platforms: list[str], visible: dict[str, int],
             edges: dict[str, int] | None = None) -> str | None:
        """Return a destination after `clear_seconds` of searching on a known platform."""
        if not searching or surface not in platforms:
            self.clear_since = None
            self.reason = ("Platform unknown or outside the round-trip map; staying"
                           if searching else "Fighting on this platform")
            return None
        self.visited.setdefault(surface, now)
        if self.clear_since is None:
            self.clear_since = now
        others = [key for key in platforms if key != surface]
        if not others:
            self.reason = "No other routable platform; staying"
            return None
        if now - self.clear_since < self.clear_seconds:
            self.reason = f"Platform clear for {now - self.clear_since:.1f}s"
            return None
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
