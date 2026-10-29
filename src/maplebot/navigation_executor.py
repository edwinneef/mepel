"""Pure bounded feedback executor. Commands are proposals, never keyboard authority."""

import math
from dataclasses import dataclass

from .input_timing import MIN_CHORD_LEAD_SECONDS, KeyHold
from .navigation import Route, RouteMap


@dataclass(frozen=True)
class Feedback:
    now: float
    fingerprint: str
    feet: tuple[float, float] | None
    surface: str | None
    motion_ok: bool
    age: float = 0
    focused: bool = True
    marker_only: bool = False


@dataclass(frozen=True)
class Motion:
    holds: tuple[KeyHold, ...] = ()
    vertical: str | None = None
    release: bool = False
    horizontal: str | None = None


# Near a map end the camera clamps, so the player reaches the screen edge and the name tag
# is cut off; inside this band of the hunting boundary a short inward walk restores it.
EDGE_ZONE = 160
EDGE_SECONDS = 4


def distance(point: tuple, trace: tuple) -> float:
    best = math.inf
    for a, b in zip(trace, trace[1:], strict=False):
        dx, dy = b[0] - a[0], b[1] - a[1]
        denominator = dx * dx + dy * dy
        t = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy)
                       / denominator)) if denominator else 0
        best = min(best, math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy))
    return best


class Navigator:
    def __init__(self, graph: RouteMap, route: Route, now: float, *, pulse: float = .12,
                 trusted_only: bool = False) -> None:
        graph.verify(route)
        if not math.isfinite(now) or not 0 < pulse <= .25:
            raise ValueError("Invalid navigation clock or input pulse")
        self.graph, self.route, self.pulse = graph, route, pulse
        self.trusted_only = trusted_only  # unsupervised: replans may use proven edges only
        self.started = self.edge_started = now
        self.last_time = float("-inf")
        self.index = self.completed = self.retries = self.replans = 0
        self.stage, self.reason = "settle_origin", "Waiting for settled origin evidence"
        self.settle_since: float | None = None
        self.departed = False
        self.takeoff_at = now
        self.last_feet: tuple | None = None
        self.settle_surface: str | None = None
        self.rope_start: float | None = None

    @property
    def active(self) -> bool:
        return self.stage not in {"stopped", "arrived"}

    def stop(self, reason: str) -> Motion:
        self.stage, self.reason = "stopped", reason
        return Motion(release=True)

    def pause_for_potion(self) -> Motion:
        self.reason = "Potion priority; movement released; waiting for fresh feedback"
        self.settle_since = None
        return Motion(release=True)

    def pause_for_recognition(self) -> None:
        self.reason = "Recognition paused; waiting for fresh same-player evidence"
        self.settle_since = self.settle_surface = self.last_feet = self.rope_start = None

    def _settled(self, feedback: Feedback, surface: str) -> bool:
        if feedback.marker_only:
            self.settle_since = None
            return False
        steady = (self.last_feet is not None and feedback.feet is not None
                  and abs(feedback.feet[1] - self.last_feet[1]) <= 3
                  and abs(feedback.feet[0] - self.last_feet[0]) <= 8)
        if not steady or self.settle_surface != surface:
            self.settle_since, self.settle_surface = feedback.now, surface
        self.last_feet = feedback.feet
        return self.settle_since is not None and feedback.now - self.settle_since >= .3

    def _walk(self, x: float, target: float) -> Motion:
        direction = "right" if target > x else "left"
        if abs(target - x) > 32:
            return Motion(horizontal=direction)
        return Motion((KeyHold(direction, min(.06, self.pulse)),))

    def step(self, f: Feedback) -> Motion:
        if not self.active:
            return Motion(release=True)
        if not math.isfinite(f.now) or f.now <= self.last_time:
            return self.stop("Non-increasing navigation observation")
        self.last_time = f.now
        if (f.fingerprint != self.route.fingerprint or not f.focused or not f.motion_ok
                or not math.isfinite(f.age) or not 0 <= f.age <= .5 or f.feet is None
                or not all(math.isfinite(v) for v in f.feet)):
            return self.stop("Fresh fused position, map revision or focus lost")
        if f.now - self.started >= 60 or self.completed >= 8:
            return self.stop("Route time or edge budget exhausted")
        blocker = self.graph.path_blocker((f.feet, f.feet))
        if blocker:
            return self.stop(blocker)
        edge = self.route.edges[self.index] if self.index < len(self.route.edges) else None
        origin = edge.source if edge else self.route.target
        if edge and f.now - self.edge_started >= 8:
            return self.stop("Edge deadline exhausted; no blind retry")
        if self.stage == "settle_origin":
            if f.surface is None:  # name-tag dropout: wait, keys released, bounded by the runtime
                self.settle_since = None
                return Motion(release=True)
            if f.surface != origin:
                return self.stop("Origin no longer matches the previewed route")
            if self._settled(f, origin):
                if edge is None:
                    self.stage, self.reason = "arrived", "Destination settled; keys released"
                else:
                    self.stage, self.reason = "approach", "Approaching recorded launch position"
            return Motion(release=True)
        assert edge is not None
        if f.surface not in (None, edge.source, edge.target):
            if f.surface in self.graph.excluded or f.surface not in self.graph.nodes:
                return self.stop("Unexpected or excluded surface")
            self.reason = "Unexpected safe surface; settling before bounded replan"
            if self._settled(f, f.surface):
                if self.replans >= 2:
                    return self.stop("Replan budget exhausted")
                try:
                    self.route = self.graph.plan(f.surface, self.route.target,
                                                 max_edges=max(1, 8 - self.completed),
                                                 trusted_only=self.trusted_only,
                                                 origin_feet=f.feet)
                except ValueError as error:
                    return self.stop(str(error))
                self.replans += 1
                self.index, self.stage, self.edge_started = 0, "settle_origin", f.now
                self.settle_since = None
            return Motion(release=True)
        if self.stage == "approach":
            rope = origin in {p["id"] for p in self.graph.profile["ropes"]}
            # No surface for a frame is a name-tag dropout, bounded by the runtime's grace.
            if not rope and f.surface not in (origin, None):
                return self.stop("Lost launch platform before takeoff")
            if rope:
                if not self.graph.on_surface(origin, f.feet):
                    return self.stop("Lost rope alignment before the next movement")
                if abs(f.feet[1] - edge.launch[1]) > 12:
                    if self.graph.path_blocker((f.feet, edge.launch)):
                        return self.stop("Rope approach crosses a boundary or excluded zone")
                    self.reason = "Approaching recorded rope launch height"
                    return Motion(vertical="up" if edge.launch[1] < f.feet[1] else "down")
            if abs(f.feet[0] - edge.launch[0]) > 12:
                if self.graph.path_blocker((f.feet, edge.launch)):
                    return self.stop("Approach crosses a boundary or excluded zone")
                self.last_feet = f.feet
                return self._walk(f.feet[0], edge.launch[0])
            self.stage, self.takeoff_at = "flight", f.now
            self.reason = "Following observed movement"
            self.departed, self.settle_since = False, None
            self.rope_start = None
            if edge.kind == "climb":
                rope_x = next((p["start"]["x"] for p in self.graph.profile["ropes"]
                               if p["id"] in {edge.source, edge.target}), f.feet[0])
                if abs(f.feet[0] - rope_x) > 12:
                    direction = "right" if rope_x > f.feet[0] else "left"
                    vertical = "up" if edge.landing[1] < f.feet[1] else "down"
                    jump = ((KeyHold("jump", min(.06, self.pulse)),)
                            if vertical == "up" and not rope else ())
                    return Motion(jump, vertical=vertical, horizontal=direction)
                if not rope and edge.landing[1] < f.feet[1]:
                    return Motion((KeyHold("jump", min(.06, self.pulse)),), vertical="up")
                return Motion(vertical="up" if edge.landing[1] < f.feet[1] else "down")
            direction = "right" if edge.landing[0] > f.feet[0] else "left"
            holds = [KeyHold(direction, self.pulse)]
            if edge.kind == "drop":
                holds.append(KeyHold("down", self.pulse))
            if edge.kind in {"jump", "drop"}:
                holds.append(KeyHold("jump", min(.06, self.pulse), MIN_CHORD_LEAD_SECONDS))
            return Motion(tuple(holds))
        if distance(f.feet, edge.trace) > 64:
            return self.stop("Movement departed the recorded corridor")
        self.departed |= (math.dist(f.feet, edge.launch) >= 12 or f.surface != edge.source)
        target_rope = edge.target in {p["id"] for p in self.graph.profile["ropes"]}
        on_target = (f.surface == edge.target if not target_rope
                     else self.graph.on_surface(edge.target, f.feet)
                     and abs(f.feet[1] - edge.launch[1]) >= 16
                     and (f.feet[1] - edge.launch[1]) * (edge.landing[1] - edge.launch[1]) > 0)
        if on_target and self.departed:
            if f.marker_only:
                self.settle_since, self.rope_start = None, None
                return Motion(release=True)
            if target_rope:
                # Observe sustained aligned vertical progress; proximity alone is insufficient.
                if self.settle_since is None:
                    self.settle_since = f.now
                    self.rope_start = f.feet[1]
                settled = (f.now - self.settle_since >= .3 and self.rope_start is not None
                           and abs(f.feet[1] - self.rope_start) >= 8)
            else:
                settled = self._settled(f, edge.target)
            self.reason = "Verifying destination evidence; contact remains inferred"
            if settled:
                self.index += 1
                self.completed += 1
                self.retries = 0
                self.settle_since, self.last_feet = None, None
                self.stage = "settle_origin"
                self.edge_started = f.now
                if self.index == len(self.route.edges):
                    self.stage, self.reason = "arrived", "Destination settled; keys released"
                elif target_rope:
                    self.stage, self.edge_started = "approach", f.now
                    next_edge = self.route.edges[self.index]
                    if (next_edge.kind == "climb"
                            and (next_edge.landing[1] - next_edge.launch[1])
                            * (edge.landing[1] - edge.launch[1]) > 0):
                        return Motion(vertical="up" if edge.landing[1] < edge.launch[1] else "down")
                return Motion(release=True)
            return Motion(release=True) if not target_rope else Motion(
                vertical="up" if edge.landing[1] < edge.launch[1] else "down")
        self.settle_since, self.last_feet, self.rope_start = None, f.feet, None
        if not self.departed and f.now - self.takeoff_at >= 1:
            if f.surface == edge.source and self.retries < 1:
                self.retries += 1
                self.stage = "settle_origin"
                self.reason = "No departure observed; one settled-origin retry"
                return Motion(release=True)
            return self.stop("Departure not observed; retry budget exhausted")
        if edge.kind == "climb":
            rope_x = next((p["start"]["x"] for p in self.graph.profile["ropes"]
                           if p["id"] in {edge.source, edge.target}), f.feet[0])
            if not target_rope and abs(f.feet[1] - edge.landing[1]) <= 16:
                if abs(f.feet[0] - edge.landing[0]) > 12:
                    return self._walk(f.feet[0], edge.landing[0])
            # Still on the launch floor below the rope: the takeoff chord can be dropped
            # while a walk pulse is in flight, and plain "up" cannot reach an overhead rope.
            grab = (f.surface == edge.source and edge.landing[1] < f.feet[1]
                    and edge.source not in {p["id"] for p in self.graph.profile["ropes"]})
            jump = (KeyHold("jump", min(.06, self.pulse)),)
            if abs(f.feet[0] - rope_x) > 12:
                return Motion(jump if grab else (),
                              vertical="up" if edge.landing[1] < f.feet[1] else "down",
                              horizontal="right" if rope_x > f.feet[0] else "left")
            if grab:
                return Motion(jump, vertical="up")
            return Motion(vertical="up" if edge.landing[1] < f.feet[1] else "down")
        if abs(f.feet[0] - edge.landing[0]) > 12:
            direction = edge.landing[0] - edge.launch[0]
            if (direction > 0 and f.feet[0] > edge.landing[0] + 48
                    or direction < 0 and f.feet[0] < edge.landing[0] - 48):
                return self.stop("Landing overshoot; keys released")
            return self._walk(f.feet[0], edge.landing[0])
        return Motion(release=True)

    def snapshot(self) -> dict:
        return {"stage": self.stage, "reason": self.reason, "active": self.active,
                "target": self.route.target, "edge_index": self.index,
                "completed": self.completed, "retries": self.retries, "replans": self.replans,
                "edge": self.route.edges[self.index].id if self.index < len(self.route.edges)
                else None, "budget": {"route_seconds": 60, "edge_seconds": 8, "edges": 8},
                "route": self.route.snapshot()}


class EdgeStep:
    """Walk inward from a map end until the clipped name tag is recognized again.

    The minimap marker is the only position evidence, so the walk is flat (no jump or
    vertical keys), short, and stops on recognition, stalled progress or the deadline.
    """

    def __init__(self, graph: RouteMap, now: float, *, pulse: float = .12) -> None:
        if not math.isfinite(now) or not 0 < pulse <= .25:
            raise ValueError("Invalid navigation clock or input pulse")
        boundary = graph.profile["boundary"]
        self.graph, self.pulse = graph, pulse
        self.low = boundary["x"] + EDGE_ZONE
        self.high = boundary["x"] + boundary["width"] - EDGE_ZONE
        self.started = self.progress_at = now
        self.last_time = float("-inf")
        self.direction: str | None = None
        self.best = 0.0
        self.stage, self.reason = "edge", "Walking inward from the map edge to show the name tag"

    @property
    def active(self) -> bool:
        return self.stage not in {"stopped", "arrived"}

    def stop(self, reason: str) -> Motion:
        self.stage, self.reason = "stopped", reason
        return Motion(release=True)

    def pause_for_potion(self) -> Motion:
        self.reason = "Potion priority; movement released; waiting for fresh feedback"
        return Motion(release=True)

    def side(self, x: float) -> str | None:
        """The inward direction from a map end, or None away from both ends."""
        return "left" if x >= self.high else "right" if x <= self.low else None

    def step(self, f: Feedback) -> Motion:
        if not self.active:
            return Motion(release=True)
        if not math.isfinite(f.now) or f.now <= self.last_time:
            return self.stop("Non-increasing navigation observation")
        self.last_time = f.now
        if (f.fingerprint != self.graph.fingerprint or not f.focused
                or not math.isfinite(f.age) or not 0 <= f.age <= .5 or f.feet is None
                or not all(math.isfinite(v) for v in f.feet)):
            return self.stop("Fresh minimap marker, map revision or focus lost")
        if f.motion_ok and f.surface is not None:
            self.stage, self.reason = "arrived", "Name tag recognized again; keys released"
            return Motion(release=True)
        if f.now - self.started >= EDGE_SECONDS:
            return self.stop("Edge step deadline exhausted; name tag still not recognized")
        x = f.feet[0]
        if self.direction is None:
            self.direction, self.best = self.side(x), x
            if self.direction is None:
                return self.stop("Player marker is not at a map edge")
        if (x - self.best) * (1 if self.direction == "right" else -1) >= 8:
            self.best, self.progress_at = x, f.now
        elif f.now - self.progress_at >= 1.5:
            return self.stop("No inward movement at the map edge")
        if self.low + 48 < x < self.high - 48:
            return self.stop("Left the map edge; name tag still not recognized")
        ahead = (x + (40 if self.direction == "right" else -40), f.feet[1])
        blocker = self.graph.path_blocker((f.feet, ahead))
        if blocker:
            return self.stop(blocker)
        return Motion((KeyHold(self.direction, self.pulse),))

    def snapshot(self) -> dict:
        return {"stage": self.stage, "reason": self.reason, "active": self.active,
                "target": None, "direction": self.direction, "route": None,
                "budget": {"edge_seconds": EDGE_SECONDS, "zone_px": EDGE_ZONE}}
