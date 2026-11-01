"""One bounded same-platform walk. Pure feedback proposals, never input authority."""

import math

from .input_timing import KeyHold
from .navigation_executor import BRAKE_PX, Motion, Navigator


class ShortWalk(Navigator):
    def __init__(self, graph, route, now, origin, delta, *, pulse=.08):
        super().__init__(graph, route, now, pulse=min(.08, pulse))
        if (route.origin != route.target or route.edges or len(origin) != 2
                or not all(type(v) in (int, float) and math.isfinite(v) for v in (*origin, delta))
                or not 48 <= abs(delta) <= 96):
            raise ValueError("Short walk requires one platform and a 48-96 pixel distance")
        node = graph.nodes[route.origin]
        points = node.get("points", [node["start"], node["end"]])
        if node in graph.profile["ropes"] or any(abs(p["y"] - points[0]["y"]) > 1
                                                for p in points):
            raise ValueError("Short walk requires a flat platform")
        self.origin = tuple(origin)
        self.delta, self.target_x = delta, origin[0] + delta
        self.direction = "left" if delta < 0 else "right"
        self.moving_since = self.progress_at = None
        self.best_distance = abs(delta)
        left, right = sorted((node["start"]["x"], node["end"]["x"]))
        corridor = (min(origin[0] - 16, self.target_x - 32) - BRAKE_PX,
                    max(origin[0] + 16, self.target_x + 32) + BRAKE_PX)
        if (not graph.on_surface(route.origin, origin)
                or not left <= corridor[0] < corridor[1] <= right):
            raise ValueError("Short walk needs stopping room inside the same platform")
        if reason := graph.path_blocker(tuple((x, origin[1]) for x in corridor)):
            raise ValueError(reason)

    def budget_blocker(self, now):
        if now - self.started >= 5 or (self.moving_since is not None
                                       and now - self.moving_since >= 3):
            return "Short walk time budget exhausted; no retry"
        return None

    def step(self, f):
        if not self.active:
            return Motion(release=True)
        if (not math.isfinite(f.now) or f.now <= self.last_time or f.feet is None
                or not all(math.isfinite(v) for v in f.feet)
                or not math.isfinite(f.age) or not 0 <= f.age <= .5 or not f.focused
                or not f.motion_ok or f.marker_only or f.fingerprint != self.route.fingerprint
                or f.surface != self.route.origin or not self.graph.on_surface(f.surface, f.feet)):
            return self.stop("Short walk lost fresh same-platform position or focus")
        self.last_time = f.now
        if reason := self.budget_blocker(f.now):
            return self.stop(reason)
        if reason := self.graph.path_blocker((f.feet, f.feet)):
            return self.stop(reason)
        if self.stage == "settle_origin":
            if abs(f.feet[0] - self.origin[0]) > 16 or abs(f.feet[1] - self.origin[1]) > 3:
                return self.stop("Short walk starting position changed")
            if not self._settled(f, self.route.origin):
                return Motion(release=True)
            self.stage, self.reason = "walk", "Walking toward the nearby point"
            self.moving_since = self.progress_at = f.now
        remaining = self.target_x - f.feet[0]
        if abs(remaining) <= 32:
            if self.stage != "settle_target":
                self.stage, self.reason = "settle_target", "Stopping and observing arrival"
                self.settle_since = self.last_feet = self.settle_surface = None
            if self._settled(f, f.surface) and f.now - self.settle_since >= 1:
                self.stage, self.reason = "arrived", "Short walk arrived; keys released"
            return Motion(release=True)
        if self.stage == "settle_target":
            return self.stop("Short walk left the arrival band; no correction or retry")
        if (remaining * self.delta < 0
                or (f.feet[0] - self.origin[0]) * self.delta < -16 * abs(self.delta)):
            return self.stop("Short walk overshoot or wrong-way movement")
        if abs(remaining) < self.best_distance - 4:
            self.best_distance, self.progress_at = abs(remaining), f.now
        if f.now - self.progress_at >= 1:
            return self.stop("Short walk made no progress; no retry")
        return Motion(holds=(KeyHold(self.direction, self.pulse),))

    def snapshot(self):
        return {**super().snapshot(), "kind": "short_walk", "target_x": self.target_x,
                "origin_feet": list(self.origin), "delta": self.delta,
                "budget": {"total_seconds": 5, "movement_window_seconds": 3,
                           "arrival_seconds": 1, "max_distance_px": 96}}
