"""Navigation's runtime adapter; keyboard authority stays with the existing controller."""

import json
import time

from .contracts import FRESH_FRAME_SECONDS
from .decision import Action
from .navigation import RouteMap, map_hash
from .navigation_evidence import build_evidence
from .navigation_executor import Feedback, Navigator
from .scheduler import SUSTAIN


class NavigationRuntime:
    def __init__(self, app) -> None:
        self.app = app
        self.graph = self.route = self.agent = self.feedback = None
        self.previous = None
        self.ticket = self.lease = None
        self.reason = "Track a saved map, then load its navigation routes"

    def cancel(self, reason: str) -> None:
        if self.agent and self.agent.active:
            self.agent.stop(reason)
        if self.lease is not None:
            self.app.controller.release_vertical_lease(self.lease)
        self.lease, self.ticket = None, None
        self.reason = reason

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
        position = app.position
        if position.teacher or position.finished or position.teach_calibrating:
            raise ValueError("Finish and save or discard teaching before navigation")
        profile = app.areas.load(position.profile["id"])["profile"]
        self.graph = RouteMap(profile, build_evidence(profile, app.areas.directory))
        self.route = self.agent = None
        self.reason = "Choose a destination and preview its route; no keys are sent"
        return self.snapshot()

    def preview(self, origin: str, target: str) -> dict:
        self.refresh()
        self.route = self.graph.plan(origin, target)
        self.reason = "Route preview only; no gameplay keys sent"
        return self.snapshot()

    def blocker(self) -> str | None:
        app = self.app
        if app.capture_only:
            return "Capture-only session: navigation input locked"
        if not self.route or not self.graph:
            return "Preview an evidenced route first"
        if (app.position is not None and map_hash(app.position.profile) != self.graph.fingerprint):
            return "Stop tracking and reload the changed map before navigation"
        if app.area_editing or app.calibrating or app.active_probe is not None:
            return "Finish editing, selection or control probing first"
        if app.alarm.snapshot()["active"]:
            return "Acknowledge the active alarm first"
        controls = {"left", "right"}
        for edge in self.route.edges:
            controls.update({"jump"} if edge.kind == "jump" else
                            {"jump", "down"} if edge.kind == "drop" else
                            {"up", "down"} if edge.kind == "climb" else set())
        missing = controls - app.probed
        if missing:
            return "Verify navigation controls: " + ", ".join(sorted(missing))
        f = self.feedback
        # Before the countdown, a reading from the last ~3 fps frame is fresh enough;
        # while moving, the executor keeps its own 0.5 s limit.
        if (not f or time.perf_counter() - f.now > FRESH_FRAME_SECONDS or not f.motion_ok
                or f.surface != self.route.origin):
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
        self.route = self.graph.plan(f.surface, target)
        return self.start(context, opt_in)

    def start(self, context, opt_in: bool) -> dict:
        app = self.app
        blocker = self.blocker()
        if blocker:
            raise ValueError(blocker)
        if opt_in is not True:
            raise ValueError("Explicit supervision opt-in is required for a bounded route")
        app._stop("OPERATOR_STOP", "Preparing navigation; focus the game within 3 seconds")
        with app.stop_lock:
            if context is not None:
                context.validate(app.command_epoch - 1)
            app.stop_requested.clear()
            app.mode, app.pending_at = "navigation_wait", time.perf_counter() + 3
        self.agent = Navigator(self.graph, self.route, time.perf_counter(),
                               pulse=min(.12, app.config.input.max_action_seconds))
        self.reason = "Focus the game; navigation countdown is bounded and cancelable"
        return self.snapshot()

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
        feet = self.app.position.tracker.transform.to_area(*fix.dot) if (
            fresh and self.app.position.tracker) else None
        screen = (player.box.center[0], player.box.feet) if fresh else None
        motion = False
        if fresh and self.previous:
            last_time, last_feet, last_screen = self.previous
            shift = observation.camera_shift
            motion = 0 < now - last_time <= 1 and all(
                abs(feet[i] - last_feet[i] - (screen[i] - last_screen[i] - shift[i])) <= 32
                for i in (0, 1))
        self.previous = (now, feet, screen) if feet and screen else None
        profile = json.loads((self.app.areas.directory / f"{self.graph.profile['id']}.json")
                             .read_text("utf-8"))
        self.feedback = Feedback(now, map_hash(profile), feet,
                                 position.get("surface_id") if position
                                 and not position.get("provisional") else None,
                                 motion, max(0, time.perf_counter() - now),
                                 self.app._input_block_reason() is None
                                 if not self.app.capture_only else False)

    def tick(self, suggestion: str | None, now: float) -> None:
        app = self.app
        if app.mode not in {"navigation", "navigation_wait"}:
            return
        if app.mode == "navigation_wait" and now < app.pending_at:
            return
        if not self.agent or not self.feedback:
            app._stop("PLAYER_UNCERTAIN", "Navigation feedback unavailable")
            return
        if not self.feedback.motion_ok or time.perf_counter() - self.feedback.now > .5:
            app._stop("PLAYER_UNCERTAIN", "Navigation fused feedback is stale or uncertain")
            return
        if app.stop_requested.is_set() or app._input_block_reason():
            app._stop("FOCUS_LOSS", "Navigation focus/capture/input gate lost")
            return
        if app.mode == "navigation_wait":
            app.controller.enable()
            # A new run gets its own stop record, time and clip, as probes and arming do.
            app._clear_stop_banner()
            app.mode = "navigation"
            app._start_sustain()
            self.agent = Navigator(self.graph, self.route, now,
                                   pulse=min(.12, app.config.input.max_action_seconds))
        f = self.feedback
        motion = self.agent.step(f)
        if not self.agent.active:
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

    def snapshot(self) -> dict:
        value = self.agent.snapshot() if self.agent else {
            "stage": "preview" if self.route else "idle", "reason": self.reason,
            "active": False, "route": self.route.snapshot() if self.route else None}
        return {**value, "map": self.graph.snapshot() if self.graph else None,
                **({"stage": "countdown", "reason": self.reason, "active": True}
                   if self.app.mode == "navigation_wait" else {}),
                "ready": self.blocker() is None, "blocker": self.blocker()}
