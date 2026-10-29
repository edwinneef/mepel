"""Navigation's runtime adapter; keyboard authority stays with the existing controller."""

import json
import time
from dataclasses import replace

from .contracts import FRESH_FRAME_SECONDS
from .decision import Action
from .move_proofs import MoveProofs
from .navigation import RouteMap, map_hash
from .navigation_executor import EdgeStep, Feedback, Navigator, distance
from .scheduler import SUSTAIN

# While airborne the camera moves faster than its shift estimate and the minimap marker
# moves in ~15 px steps, so marker and name tag can briefly disagree mid-jump.
FLIGHT_GRACE_SECONDS = 0.8
# Screen width searched beside a map end during an edge step; covers the walk-in band.
EDGE_STRIP = 480
# Stops that blame the move itself; focus, feedback or budget stops do not.
MOVE_FAILURES = ("Movement departed the recorded corridor", "Landing overshoot",
                 "Departure not observed", "Edge deadline exhausted",
                 "Lost launch platform", "Lost rope alignment", "Unexpected or excluded surface")


class NavigationRuntime:
    def __init__(self, app) -> None:
        self.app = app
        self.graph = self.route = self.agent = self.feedback = None
        self.previous = None
        self.ticket = self.lease = None
        self.resume_combat = False
        self.agreed_at = float("-inf")
        self.confirmed: tuple[str, float] | None = None  # last agreed platform and its time
        self.reason = "Track a saved map, then load its navigation routes"
        self.proofs = MoveProofs(app.areas.directory)
        self.failed: set[str] = set()  # computed moves that failed this session
        self.failed_map: str | None = None
        self.counted = 0
        self.pending_proofs: list[tuple[str, str, str]] = []
        self.last_feedback_failure = None
        self.last_input_refusal = None

    def cancel(self, reason: str) -> None:
        if self.agent and self.agent.active:
            self.agent.stop(reason)
        if self.lease is not None:
            self.app.controller.release_vertical_lease(self.lease)
        self.lease, self.ticket = None, None
        self.resume_combat = False
        self.reason = reason
        # safe_stop has already released controller input. Disk flushes must not
        # consume the next observation's freshness budget during a route.
        while self.pending_proofs:
            try:
                self.proofs.record(*self.pending_proofs[0])
            except OSError as error:
                self.app.note(f"Navigation proof save deferred: {error}")
                break
            self.pending_proofs.pop(0)

    def _release(self) -> None:
        if self.ticket is not None:
            self.app.controller.cancel_ticket(self.ticket)
            self.ticket = None
        if self.lease is not None:
            self.app.controller.release_vertical_lease(self.lease)
        self.lease = None
        for action in ("left", "right", "jump", "up", "down"):
            self.app.controller.release(action)

    def refresh(self) -> dict:
        app = self.app
        if not app.position or app.area_editing:
            raise ValueError("Track a saved map outside the area editor first")
        profile = app.areas.load(app.position.profile["id"])["profile"]
        if not profile.get("public_map"):
            raise ValueError("Import this map first: maplebot import-map <area>")
        fingerprint = map_hash(profile)
        if self.failed_map != fingerprint:
            self.failed, self.failed_map = set(), fingerprint
        self.graph = RouteMap.computed(profile, self.proofs.load(profile["id"], fingerprint),
                                       self.failed)
        self.route = self.agent = None
        self.reason = "Choose a destination and preview its route; no keys are sent"
        return self.snapshot()

    def preview(self, origin: str, target: str) -> dict:
        self.refresh()
        self.route = self.graph.plan(origin, target)
        self.reason = "Route preview only; no gameplay keys sent"
        return self.snapshot()

    def blocker(self) -> str | None:
        if not self.route or not self.graph:
            return "Preview an evidenced route first" if not self.app.capture_only else (
                "Capture-only session: navigation input locked")
        return self._gate(self._route_controls())

    def _route_controls(self) -> set[str]:
        controls = {"left", "right"}
        for edge in self.route.edges:
            controls.update({"jump"} if edge.kind == "jump" else
                            {"jump", "down"} if edge.kind == "drop" else
                            {"up", "down"} if edge.kind == "climb" else set())
            if (edge.kind == "climb" and edge.landing[1] < edge.launch[1]
                    and edge.source not in {r["id"] for r in self.graph.profile["ropes"]}):
                controls.add("jump")
        return controls

    def _gate(self, controls: set[str], *, edge: bool = False) -> str | None:
        app = self.app
        if app.capture_only:
            return "Capture-only session: navigation input locked"
        if (app.position is not None and map_hash(app.position.profile) != self.graph.fingerprint):
            return "Stop tracking and reload the changed map before navigation"
        if app.area_editing or app.calibrating or app.active_probe is not None:
            return "Finish editing, selection or control probing first"
        if app.alarm.snapshot()["active"]:
            return "Acknowledge the active alarm first"
        missing = controls - app.probed
        if missing:
            return "Verify navigation controls: " + ", ".join(sorted(missing))
        f = self.feedback
        if edge:
            if not f or f.feet is None or time.perf_counter() - f.now > FRESH_FRAME_SECONDS:
                return "Waiting for a fresh minimap marker"
            if EdgeStep(self.graph, f.now).side(f.feet[0]) is None:
                return "Player marker is not at a map edge"
            if f.motion_ok and f.surface is not None:
                return "Player is already recognized; no edge step needed"
            if f.fingerprint != self.graph.fingerprint:
                return "Map changed; preview again"
        else:
            # Before the countdown, a reading from the last ~3 fps frame is fresh enough;
            # while moving, the executor keeps its own 0.5 s limit.
            # The name tag drops out at some spots, so a platform agreed within the grace
            # counts while the current frame shows no other surface.
            recent = f is not None and ((f.motion_ok and f.surface == self.route.origin) or (
                self.confirmed is not None and self.confirmed[0] == self.route.origin
                and f.now - self.confirmed[1] <= FLIGHT_GRACE_SECONDS))
            if (not f or time.perf_counter() - f.now > FRESH_FRAME_SECONDS or not recent
                    or f.surface not in (None, self.route.origin)):
                return "Waiting for fresh fused position on the previewed origin"
            if self.route.fingerprint != f.fingerprint:
                return "Map changed; preview again"
        if app.config.input.max_action_seconds < .08:
            return "Configured action cap is too short for a navigation chord"
        movement = {getattr(app.config.input, key) for key in
                    ("left", "right", "jump", "up", "down")}
        if any(getattr(app.config.input, f"{r}_potion") in movement for r in ("hp", "mp")
               if f"{r}_potion" in app.probed and app.potter.settings[f"{r}_threshold"] > 0):
            return "Movement and enabled potion bindings overlap"
        return None

    def go(self, context, target: str, opt_in: bool) -> dict:
        """Plan from the platform the player stands on and start it, in one step."""
        if self.app.position is not None:
            self.refresh()
        if not self.graph:
            raise ValueError("Track a saved map first")
        f = self.feedback
        if not f or not f.surface:
            raise ValueError(
                "Your platform is unknown; keep the full minimap open and stand on a platform"
            )
        if f.surface == target:
            raise ValueError("You are already on that platform")
        self.route = self.graph.plan(f.surface, target, origin_feet=f.feet)
        return self.start(context, opt_in)

    def edge(self, context, opt_in: bool) -> dict:
        """Walk inward from a map end where the camera clips the name tag, then stop."""
        if self.app.position is not None:
            self.refresh()
        if not self.graph:
            raise ValueError("Track a saved map first")
        blocker = self._gate({"left", "right"}, edge=True)
        if blocker:
            raise ValueError(blocker)
        return self.start(context, opt_in, edge=True)

    def start(self, context, opt_in: bool, *, edge: bool = False) -> dict:
        app = self.app
        blocker = None if edge else self.blocker()
        if blocker:
            raise ValueError(blocker)
        if opt_in is not True:
            raise ValueError("Explicit supervision opt-in is required for a bounded route")
        app._stop("OPERATOR_STOP", "Preparing navigation; focus the game within 3 seconds")
        self.last_feedback_failure = self.last_input_refusal = None
        with app.stop_lock:
            if context is not None:
                context.validate(app.command_epoch - 1)
            app.stop_requested.clear()
            app.mode, app.pending_at = "navigation_wait", time.perf_counter() + 3
        pulse = min(.12, app.config.input.max_action_seconds)
        self.agent = (EdgeStep(self.graph, time.perf_counter(), pulse=pulse) if edge else
                      Navigator(self.graph, self.route, time.perf_counter(), pulse=pulse))
        self.reason = "Focus the game; navigation countdown is bounded and cancelable"
        return self.snapshot()

    def handoff(self, target: str, now: float) -> str | None:
        """Armed combat found its platform clear: route on without a new countdown.

        Returns why the move was refused; the caller stops safely instead of retrying.
        """
        f = self.feedback
        if not self.graph or not f or not f.surface:
            return "Rotation: current platform unknown"
        try:
            self.route = self.graph.plan(f.surface, target, trusted_only=True, origin_feet=f.feet)
        except ValueError as error:
            return f"Rotation: {error}"
        blocker = self.blocker()
        if blocker:
            return f"Rotation: {blocker}"
        self._release()
        self.agent = Navigator(self.graph, self.route, now,
                               pulse=min(.12, self.app.config.input.max_action_seconds),
                               trusted_only=True)
        self.counted = 0
        self.resume_combat, self.app.mode = True, "navigation"
        self.reason = f"Platform clear; moving to {self.graph.nodes[target].get('name', target)}"
        return None

    def observe(self, fix, observation, position: dict | None, now: float) -> None:
        if not self.graph or not self.app.position:
            return
        if self.app.position.profile["id"] != self.graph.profile["id"]:
            self.feedback = None
            return
        player = observation.player
        fresh = bool(fix and fix.dot is not None and player and not player.tracked
                     and player.confidence >= .9 and observation.camera_shift is not None
                     and observation.camera_confidence >= .35)
        # The marker places the player even when the name tag drops out for a frame; only
        # fresh agreement counts as trusted motion, and trusted() bounds marker-only stretches.
        feet = self.app.position.tracker.transform.to_area(*fix.dot) if (
            fix and fix.dot is not None and self.app.position.tracker) else None
        screen = (player.box.center[0], player.box.feet) if fresh else None
        motion = False
        if fresh and self.previous:
            last_time, last_feet, last_screen = self.previous
            shift = observation.camera_shift
            motion = 0 < now - last_time <= 1 and all(
                abs(feet[i] - last_feet[i] - (screen[i] - last_screen[i] - shift[i])) <= 32
                for i in (0, 1))
        self.previous = (now, feet, screen) if fresh and feet and screen else None
        if motion:
            self.agreed_at = now
        surface = (position.get("surface_id")
                   if position and not position.get("provisional") else None)
        if motion and surface:
            self.confirmed = (surface, now)
        profile = json.loads((self.app.areas.directory / f"{self.graph.profile['id']}.json")
                             .read_text("utf-8"))
        self.feedback = Feedback(now, map_hash(profile), feet,
                                 position.get("surface_id") if position
                                 and not position.get("provisional") else None,
                                 motion, max(0, time.perf_counter() - now),
                                 self.app._input_block_reason() is None
                                 if not self.app.capture_only else False)

    def search_strip(self, width: int) -> tuple[int, int] | None:
        """Screen columns that can hold the player during an edge step, else None.

        The camera clamps at a map end, so a marker at the right end means the player is
        at the right of the screen. Searching only there keeps frames inside the 0.5 s
        freshness limit while the name tag is missing.
        """
        f, agent = self.feedback, self.agent
        if not isinstance(agent, EdgeStep) or not agent.active or not f or f.feet is None:
            return None
        side = agent.direction or agent.side(f.feet[0])
        if side is None:
            return None
        return (max(0, width - EDGE_STRIP), width) if side == "left" else (0, min(width,
                                                                              EDGE_STRIP))

    def trusted(self) -> bool:
        """Fresh agreeing feedback, or a brief marker-only stretch while moving.

        Walking to a launch point or flying may ride the minimap marker for
        FLIGHT_GRACE_SECONDS. Drops and climbs may instead use the marker inside their
        recorded corridor for the existing eight-second edge budget. Marker-only feedback
        never confirms settling; corridor, boundary and freshness checks remain active.
        """
        return self.feedback_status()["trusted"]

    def feedback_status(self) -> dict:
        """Evaluate one feedback/time pair, retaining the existing movement predicates."""
        f, now = self.feedback, time.perf_counter()
        trusted = self._trusted_feedback(f, now)
        return {"trusted": trusted, "observed_at": f.now if f else None,
                "age_ms": round((now - f.now) * 1000, 3) if f else None,
                "motion_ok": bool(f and f.motion_ok), "marker_present": bool(f and f.feet),
                "agreement_age_ms": round((f.now - self.agreed_at) * 1000, 3)
                if f and self.agreed_at != float("-inf") else None,
                "surface": f.surface if f else None, "focused": f.focused if f else None,
                "stage": self.agent.stage if self.agent else None,
                "reason": (None if trusted else "unavailable" if not f else
                           "stale" if now - f.now > .5 else "motion_or_marker_uncertain")}

    def feedback_block_reason(self) -> str | None:
        value = self.feedback_status()
        if value["trusted"]:
            return None
        self.last_feedback_failure = value
        return ("Navigation fused position is stale or uncertain: "
                + json.dumps(value, sort_keys=True))

    def _trusted_feedback(self, f, now: float) -> bool:
        if not f or now - f.now > .5:
            return False
        agent = self.agent
        if isinstance(agent, EdgeStep):
            # Marker-only by design; EdgeStep bounds its own time, direction and progress.
            return f.feet is not None and agent.active
        if (f.feet is not None and agent is not None and agent.stage == "flight"
                and agent.index < len(agent.route.edges)):
            edge = agent.route.edges[agent.index]
            if (edge.kind in {"drop", "climb"}
                    and 0 <= f.now - agent.edge_started < 8
                    and distance(f.feet, edge.trace) <= 64
                    and not agent.graph.path_blocker((f.feet, f.feet))):
                return True
        return f.motion_ok or (
            f.feet is not None and self.agent is not None
            and self.agent.stage in {"settle_origin", "approach", "flight"}
            and f.now - self.agreed_at <= FLIGHT_GRACE_SECONDS)

    def tick(self, suggestion: str | None, now: float) -> None:
        app = self.app
        if app.mode not in {"navigation", "navigation_wait"}:
            return
        if app.mode == "navigation_wait" and now < app.pending_at:
            return
        if not self.agent or not self.feedback:
            app._stop("PLAYER_UNCERTAIN", "Navigation feedback unavailable")
            return
        f = self.feedback
        if reason := self.feedback_block_reason():
            app._stop("PLAYER_UNCERTAIN", reason)
            return
        airborne = not f.motion_ok
        if app.stop_requested.is_set() or app._input_block_reason():
            app._stop("FOCUS_LOSS", "Navigation focus/capture/input gate lost")
            return
        if app.mode == "navigation_wait":
            app.controller.enable()
            # A new run gets its own stop record, time and clip, as probes and arming do.
            app._clear_stop_banner()
            app.mode = "navigation"
            app._start_sustain()
            pulse = min(.12, app.config.input.max_action_seconds)
            self.agent = (EdgeStep(self.graph, now, pulse=pulse)
                          if isinstance(self.agent, EdgeStep)
                          else Navigator(self.graph, self.route, now, pulse=pulse))
            self.counted = 0
        if isinstance(self.agent, EdgeStep):
            motion = self.agent.step(f)
        else:
            motion = self.agent.step(replace(f, motion_ok=True, marker_only=True)
                                     if airborne else f)
            self._learn()
        if not self.agent.active:
            if self.agent.stage == "arrived" and self.resume_combat:
                self._release()
                self.resume_combat = False
                app.resume_combat(self.route.target, now)
                return
            app._stop("POLICY_STOP", self.agent.reason)
            return
        if self.ticket is not None and self.ticket not in app.arbiter.in_flight:
            self.ticket = None
        proposal = Action(motion.holds[0].action, motion.holds[0].seconds) if motion.holds else (
            Action(motion.vertical, .1) if motion.vertical else Action())
        choice = app.arbiter.choose(sustain=suggestion if suggestion in app.sustain else None,
                                    combat=None, navigation=proposal)
        if choice.lane in SUSTAIN:
            self.agent.pause_for_potion()
            self._release()
            queued_at = time.perf_counter()
            submitted = app.controller.submit(choice.action, priority=choice.priority)
            if isinstance(submitted, int):
                app.arbiter.submitted(submitted, choice.lane)
                app.live_potion_ticket = submitted
                app.potion_evidence.queued(
                    submitted, choice.lane, queued_at,
                    (app.view_generation, app.source_generation),
                )
            else:
                app._stop("INPUT_BACKEND_FAILURE", str(submitted))
            return
        if choice.action is None or self.ticket is not None:
            self._release() if choice.action is None else None
            return
        if motion.release:
            self._release()
        elif motion.vertical:
            if self.lease is None:
                self.lease = app.controller.start_vertical_lease(motion.vertical)
            elif not app.controller.renew_vertical_lease(self.lease):
                app._stop("POLICY_STOP", "Navigation vertical lease expired")
        elif motion.holds:
            self._release()
            submitted = app.controller.submit_sequence(motion.holds)
            if isinstance(submitted, int):
                self.ticket = submitted
                app.arbiter.submitted(submitted, "navigation")
            else:
                app._stop("INPUT_BACKEND_FAILURE", str(submitted))
        self.reason = self.agent.reason

    def _learn(self) -> None:
        """Prove each computed move the navigator just settled; switch off one that failed."""
        agent, graph = self.agent, self.graph
        if graph is None or not graph.profile.get("public_map"):
            return
        if agent.completed > self.counted:
            self.counted = agent.completed
            edge = agent.route.edges[agent.index - 1]
            if edge.id not in graph.proven:
                self.pending_proofs.append((graph.profile["id"], graph.fingerprint, edge.id))
                graph.proven.add(edge.id)
        elif (agent.stage == "stopped" and agent.reason.startswith(MOVE_FAILURES)
              and agent.index < len(agent.route.edges)):
            self.failed.add(agent.route.edges[agent.index].id)

    def snapshot(self) -> dict:
        value = self.agent.snapshot() if self.agent else {
            "stage": "preview" if self.route else "idle", "reason": self.reason,
            "active": False, "route": self.route.snapshot() if self.route else None}
        return {**value, "map": self.graph.snapshot() if self.graph else None,
                "feedback": self.feedback_status(),
                "last_feedback_failure": self.last_feedback_failure,
                "last_input_refusal": self.last_input_refusal,
                **({"stage": "countdown", "reason": self.reason, "active": True}
                   if self.app.mode == "navigation_wait" else {}),
                "ready": self.blocker() is None, "blocker": self.blocker(),
                "edge_blocker": self._gate({"left", "right"}, edge=True) if self.graph
                else "Track a saved map first"}
