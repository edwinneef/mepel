"""Command-driven offline navigation experiments. Never constructs capture or native input.

NavigationRuntime, Navigator, Arbiter and TimingPlanner are production code. The clock,
controller and platform physics are models, not evidence of game contact or key delivery.
Run with ``python -m tools.navigation_harness --output artifacts/navigation-harness.json``.
"""

import argparse
import copy
import heapq
import json
import math
import random
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from maplebot import navigation_runtime
from maplebot.config import Config, TimingConfig
from maplebot.input_timing import TimingPlanner
from maplebot.navigation import RouteMap, map_hash, surface_y
from maplebot.navigation_executor import Feedback, Navigator
from maplebot.navigation_runtime import NavigationRuntime
from maplebot.public_map import span
from maplebot.scheduler import Arbiter


@dataclass(frozen=True)
class Experiment:
    name: str = "round-trip"
    targets: tuple[str, ...] = ("ledge", "floor")
    fps: float = 3
    seed: int = 71
    input_delay: float = 0
    drop_input: bool = False
    feedback_delay: float = 0
    speed: float = 180
    acceleration: float = 1400
    braking: float = 2200
    jump_speed: float = 310
    gravity: float = 620
    fault: str = ""
    fault_at: float = 2
    expected: str = "arrived"
    expected_reason: str = ""

    def __post_init__(self):
        for name in ("fps", "speed", "acceleration", "braking", "jump_speed", "gravity"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("input_delay", "feedback_delay", "fault_at"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative and finite")
        if self.fps > 120 or self.fps < 1:
            raise ValueError("Offline observation rate must be between 1 and 120 fps")
        if self.fault not in {"", "focus", "stop", "stale", "map", "missing", "handoff"}:
            raise ValueError("Unknown offline fault")
        if not self.targets or any(not isinstance(target, str) or not target
                                   for target in self.targets):
            raise ValueError("At least one target is required")
        if self.expected not in {"arrived", "safe_stop"}:
            raise ValueError("Expected result must be arrived or safe_stop")


class World:
    """Small acceleration/gravity model; collisions use geometry, never route.trace."""

    def __init__(self, graph, feet, settings):
        if len(feet) != 2 or not all(math.isfinite(value) for value in feet):
            raise ValueError("Initial feet must be two finite coordinates")
        self.graph, self.settings = graph, settings
        self.x, self.y = feet
        self.vx = self.vy = 0.0
        self.surface = self.contact()
        if self.surface is None:
            raise ValueError("Initial feet must be on a modeled platform")
        self.ignore = None
        self.ignore_until = 0.0

    def contact(self):
        return next((p["id"] for p in self.graph.profile["platforms"]
                     if span(p)[0] <= self.x <= span(p)[1]
                     and abs(surface_y(p, self.x) - self.y) < .1), None)

    def press_jump(self, held, now):
        if self.surface is None:
            return
        if "down" in held:
            self.ignore, self.ignore_until = self.surface, now + .4
            self.vy = 1
        else:
            self.vy = -self.settings.jump_speed
        self.surface = None

    def advance(self, seconds, held, now):
        s = self.settings
        direction = int("right" in held) - int("left" in held)
        wanted = direction * s.speed
        change = (s.acceleration if direction else s.braking) * seconds
        self.vx += max(-change, min(change, wanted - self.vx))
        old_y = self.y
        self.x += self.vx * seconds
        if self.surface is not None:
            platform = self.graph.nodes[self.surface]
            if span(platform)[0] <= self.x <= span(platform)[1]:
                self.y = surface_y(platform, self.x)
                return
            self.surface = None
        self.y += self.vy * seconds + .5 * s.gravity * seconds ** 2
        self.vy += s.gravity * seconds
        if self.vy < 0:
            return
        crossed = [(surface_y(p, self.x), p["id"]) for p in self.graph.profile["platforms"]
                   if span(p)[0] <= self.x <= span(p)[1]
                   and not (p["id"] == self.ignore and now < self.ignore_until)
                   and old_y <= surface_y(p, self.x) <= self.y]
        if crossed:
            self.y, self.surface = min(crossed)
            self.vy = 0


class ModelController:
    """Virtual controller with real timing plans, expiring holds and ticket completion.

    This deliberately has no InputBackend, worker threads, window handle or SendInput path.
    It models the controller contract; native controller coverage remains in test_keyboard.
    """

    def __init__(self, world, settings, config, arbiter):
        self.world, self.settings, self.config, self.arbiter = world, settings, config, arbiter
        self.now = 0.0
        self.planner = TimingPlanner(config, replace(TimingConfig(), seed=settings.seed),
                                     random.Random(settings.seed))
        self.events, self.log, self.held = [], [], {}
        self.next_ticket = self.order = 0
        self.tickets = set()
        self.leases = {}
        self.suspended = False
        self.enabled = False

    def enable(self):
        self.enabled = True

    def _event(self, at, ticket, action, down):
        self.order += 1
        heapq.heappush(self.events, (at, self.order, ticket, action, down))

    def _send(self, action, down, until=math.inf):
        if down and action not in self.held:
            if self.settings.drop_input:
                self.log.append({"at": round(self.now, 6), "action": action, "down": True,
                                 "delivered": False})
                return
            self.held[action] = until
            self.log.append({"at": round(self.now, 6), "action": action, "down": True})
            if action == "jump":
                self.world.press_jump(self.held, self.now)
        elif not down and action in self.held:
            del self.held[action]
            self.log.append({"at": round(self.now, 6), "action": action, "down": False})

    def submit_sequence(self, holds, preserve_movement=False):
        if not self.enabled:
            return "blocked: model input disabled"
        if self.tickets:
            raise RuntimeError("Model sequence overlap; runtime must wait for its ticket")
        if not preserve_movement:
            self.release_movement()
        schedule = self.planner.plan(holds)
        self.next_ticket += 1
        ticket = self.next_ticket
        self.tickets.add(ticket)
        began = self.now + self.settings.input_delay
        for event in schedule.events:
            self._event(began + event.at_seconds, ticket, event.action, event.down)
        self._event(began + max(e.at_seconds for e in schedule.events)
                    + schedule.rest_seconds, ticket, "complete", False)
        return ticket

    def cancel_ticket(self, ticket):
        self.tickets.discard(ticket)
        self.arbiter.finished(ticket)
        self.events = [event for event in self.events if event[2] != ticket]
        heapq.heapify(self.events)
        for action in tuple(self.held):
            self.release(action)

    def refresh_movement(self, action, seconds, navigation=False):
        if not self.enabled or not 0 < seconds <= self.config.max_action_seconds:
            return "blocked: model input disabled or invalid duration"
        other = "left" if action == "right" else "right"
        self.release(other)
        self._send(action, True, self.now + seconds)
        if action in self.held:
            self.held[action] = self.now + seconds
        return f"held: {action}"

    def release(self, action):
        self._send(action, False)

    def release_movement(self):
        for action in ("left", "right"):
            self.release(action)

    def release_vertical_lease(self, lease):
        raise ValueError("Vertical leases require a rope model")

    def start_vertical_lease(self, action):
        raise ValueError("Vertical leases require a rope model")

    def stop(self):
        self.enabled = False
        for ticket in tuple(self.tickets):
            self.cancel_ticket(ticket)
        for action in tuple(self.held):
            self.release(action)
        self.events.clear()
        self.arbiter.reset()

    def advance(self, until):
        while self.now < until - 1e-9:
            event_at = self.events[0][0] if self.events else math.inf
            expiry = min(self.held.values(), default=math.inf)
            end = min(until, self.now + 1 / 240, event_at, expiry)
            self.world.advance(max(0, end - self.now), self.held, end)
            self.now = end
            for action, deadline in tuple(self.held.items()):
                if deadline <= self.now + 1e-9:
                    self.release(action)
            while self.events and self.events[0][0] <= self.now + 1e-9:
                _, _, ticket, action, down = heapq.heappop(self.events)
                if ticket not in self.tickets:
                    continue
                if action == "complete":
                    self.tickets.remove(ticket)
                    self.arbiter.finished(ticket)
                else:
                    self._send(action, down)


def sample_graph():
    """Explicit synthetic geometry, not copied game assets or a fitted game model."""
    profile = {"id": "a" * 32, "revision": 1,
               "boundary": {"x": 0, "y": 0, "width": 600, "height": 500},
               "zones": [], "ropes": [], "platforms": [
                   {"id": name, "name": name, "start": {"x": x, "y": y},
                    "end": {"x": end, "y": y}}
                   for name, x, end, y in (("floor", 40, 300, 400),
                                           ("ledge", 220, 460, 350),
                                           ("island", 480, 560, 250))],
               "links": [{"id": name, "from": a, "to": b, "kind": kind}
                         for name, a, b, kind in (("up", "floor", "ledge", "jump"),
                                                 ("back", "ledge", "floor", "drop"))]}
    traces = {"up": [[230, 400], [250, 300], [270, 350]],
              "back": [[270, 350], [200, 400]]}
    evidence = {"area_id": profile["id"], "revision": 1, "map_hash": map_hash(profile),
                "edges": {link["id"]: {**link, "source": "synthetic-model", "missing_checks": 0,
                                       "max_gap": .3, "trace": traces[link["id"]]}
                          for link in profile["links"]}}
    return RouteMap(profile, evidence)


def run(settings=None, *, graph=None, feet=(230, 400), origin="floor"):
    """One deterministic experiment, including separate route countdowns and handoff.

    A local module clock is replaced only while the synchronous offline adapter runs.
    No Application, capture worker or KeyboardController is created.
    """
    settings = settings or Experiment()
    graph = copy.deepcopy(graph) if graph is not None else sample_graph()
    if settings.fault == "handoff" and "island" not in graph.excluded:
        raise ValueError("Handoff fault requires the sample's excluded island")
    world = World(graph, feet, settings)
    app = SimpleNamespace(config=Config(), mode="navigation_wait", pending_at=3.0,
                          sustain=set(), stop_requested=threading.Event(),
                          areas=SimpleNamespace(directory=Path("unused-offline-area")))
    app.arbiter = Arbiter(.06)
    control = app.controller = ModelController(world, settings, app.config.input, app.arbiter)
    nav = NavigationRuntime(app)
    nav.graph = graph
    def plan(here, target):
        route = graph.plan(here, target, origin_feet=(world.x, world.y))
        ropes = {rope["id"] for rope in graph.profile["ropes"]}
        if any(e.kind == "climb" or e.source in ropes or e.target in ropes for e in route.edges):
            raise ValueError("Rope physics is unsupported; select platform-only routes")
        return route

    nav.route = plan(origin, settings.targets[0])
    nav.agent = Navigator(graph, nav.route, 0)
    app._clear_stop_banner = app._start_sustain = lambda: None
    stopped, snapshots, arrivals, violations = [], [], [], []
    focused = True

    def stop(code, reason):
        stopped.append({"at": round(control.now, 6), "code": code, "reason": reason})
        control.stop()
        app.mode = "capture"

    def block():
        return "Model focus lost" if not focused else nav.feedback_block_reason()

    app._stop, app._input_block_reason = stop, block
    faulted = False
    history = [(0.0, world.x, world.y, world.surface)]
    began = time.perf_counter()
    try:
        clock = SimpleNamespace(perf_counter=lambda: control.now)
        with patch.object(navigation_runtime, "time", clock):
            # Same 60-second route bound plus countdown, independently for each leg.
            for _ in range(math.ceil(64 * settings.fps) * len(settings.targets)):
                control.advance(control.now + 1 / settings.fps)
                history.append((control.now, world.x, world.y, world.surface))
                if not faulted and settings.fault != "handoff" and control.now >= settings.fault_at:
                    faulted = True
                    if settings.fault == "focus":
                        focused = False
                    elif settings.fault == "stop":
                        app.stop_requested.set()
                age = settings.feedback_delay
                if faulted and settings.fault == "stale":
                    age = max(age, .6)
                observed = next((sample for sample in reversed(history)
                                 if sample[0] <= control.now - age + 1e-9), history[0])
                stamp, x, y, surface = observed
                nav.feedback = Feedback(stamp, graph.fingerprint,
                                        (x, y), surface, True, control.now - stamp,
                                        focused=focused)
                if faulted and settings.fault == "missing":
                    nav.feedback = replace(nav.feedback, feet=None, motion_ok=False)
                if faulted and settings.fault == "map":
                    nav.feedback = replace(nav.feedback, fingerprint="changed-map")
                nav.tick(None, control.now)
                snapshots.append({"at": round(control.now, 6), "stage": nav.agent.stage,
                                  "feet": [round(world.x, 3), round(world.y, 3)],
                                  "surface": world.surface, "ticket": nav.ticket,
                                  "feedback_age": round(control.now - stamp, 6),
                                  "reason": nav.agent.reason})
                # An independent oracle must not assume the runtime checked its
                # deadlines: it deliberately waits for a running sequence ticket.
                if app.mode == "navigation":
                    if control.now - nav.agent.edge_started >= 8:
                        violations.append("Edge deadline exceeded while input ticket pending")
                    if control.now - nav.agent.started >= 60:
                        violations.append("Route deadline exceeded")
                    if violations:
                        break
                if app.mode != "capture":
                    continue
                if nav.agent.stage != "arrived":
                    break
                arrivals.append(nav.route.target)
                if len(arrivals) == len(settings.targets):
                    break
                # A second route starts from observed contact, with the real runtime's
                # countdown. A displacement during it must never be labeled an arrival.
                nav.route = plan(world.surface, settings.targets[len(arrivals)])
                nav.agent = Navigator(graph, nav.route, control.now)
                nav.ticket = nav.lease = None
                app.mode, app.pending_at = "navigation_wait", control.now + 3
                if settings.fault == "handoff":
                    # Reproduce the observed *class* of failure: a different, excluded
                    # surface during the next countdown. This is an injected displacement,
                    # not reconstructed physics from the recording.
                    world.x, world.y, world.surface = 500, 250, "island"
                    world.vx = world.vy = 0
                    faulted = True
    finally:
        control.stop()
    outcome = ("arrived" if len(arrivals) == len(settings.targets) else
               "safe_stop" if app.mode == "capture" and stopped else "incomplete")
    return {"settings": asdict(settings), "outcome": outcome,
            "passed": (outcome == settings.expected and not control.held and not control.events
                       and not violations
                       and (not settings.expected_reason or bool(stopped)
                            and settings.expected_reason in stopped[-1]["reason"])),
            "arrivals": arrivals, "stops": stopped, "frames": snapshots, "keys": control.log,
            "violations": violations,
            "held_after": sorted(control.held), "pending_after": len(control.events),
            "tickets_after": len(control.tickets),
            "simulated_seconds": round(control.now, 6),
            "wall_seconds": round(time.perf_counter() - began, 6),
            "input_sent": False, "native_acceptance": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--profile", type=Path, help="Optional saved imported map, read-only")
    parser.add_argument("--origin", default="floor")
    parser.add_argument("--feet", type=float, nargs=2, default=(230, 400))
    parser.add_argument("--targets", nargs="+", default=("ledge", "floor"))
    parser.add_argument("--experiment", type=Path, help="Optional Experiment settings JSON")
    args = parser.parse_args()
    if not 1 <= args.seeds <= 1000:
        parser.error("--seeds must be between 1 and 1000")
    data = (Path(__file__).resolve().parents[1] / "data").resolve()
    if args.output.resolve().is_relative_to(data):
        parser.error("Output must stay outside protected data/")
    if args.output.exists():
        parser.error("Output already exists; choose a new evidence path")
    if args.profile and args.output.resolve().is_relative_to(args.profile.resolve().parent):
        parser.error("Keep output separate from the saved map directory")
    graph = RouteMap.computed(json.loads(args.profile.read_text("utf-8"))) if args.profile else None
    if args.experiment:
        settings = [Experiment(**json.loads(args.experiment.read_text("utf-8")))]
    else:
        settings = [Experiment(seed=seed, targets=tuple(args.targets))
                    for seed in range(args.seeds)]
        if not args.profile:
            settings.extend(Experiment(name=fault, fault=fault, fault_at=4, expected="safe_stop")
                            for fault in ("focus", "stop", "stale", "map", "missing"))
            case = json.loads(Path(__file__).with_name("navigation_harness_case.json")
                              .read_text("utf-8"))
            settings.append(Experiment(**case["experiment"]))
            settings.append(Experiment(name="lost-input", drop_input=True,
                                       expected="safe_stop"))
    results = [run(setting, graph=graph, feet=args.feet, origin=args.origin)
               for setting in settings]
    report = {"scope": "Synthetic platform dynamics and controller; real navigation/runtime/timing",
              "input_sent": False, "native_acceptance": False, "runs": results,
              "passed": sum(row["passed"] for row in results), "total": len(results)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "total", "input_sent")}))
    raise SystemExit(report["passed"] != report["total"])


if __name__ == "__main__":
    main()
