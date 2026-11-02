"""Navigation's runtime adapter; keyboard authority stays with the existing controller."""

import json
import math
import time
from dataclasses import replace

from .contracts import FRESH_FRAME_SECONDS
from .decision import Action
from .move_proofs import MoveProofs
from .moves import Move, generate
from .navigation import RouteMap, map_hash, pose_gaps, required_poses
from .navigation_executor import EdgeStep, Feedback, Navigator, distance
from .navigation_replay import recorded_step
from .reacquisition import RECOVERY_SECONDS
from .scheduler import SUSTAIN
from .short_walk import ShortWalk

# While airborne the camera moves faster than its shift estimate and the minimap marker
# moves in ~15 px steps, so marker and name tag can briefly disagree mid-jump.
FLIGHT_GRACE_SECONDS = 0.8
# Screen width searched beside a map end during an edge step; covers the walk-in band.
EDGE_STRIP = 480
RECOGNITION_RECOVERY_SECONDS = RECOVERY_SECONDS
# Written beside data/areas by tools/recognition_eval.py --coverage.
POSE_COVERAGE = "recognition-coverage.json"
# Stops that blame the move itself; focus, feedback or budget stops do not.
# A supervised learn_moves batch keeps farming after this many safe misses; one more stops.
MISS_LIMIT = 3
# After a missed move, keys stay released while the player lands; no safe landing in time
# is an ordinary navigation failure.
MISS_SETTLE_SECONDS = 2.0
MOVE_FAILURES = ("Movement departed the recorded corridor", "Landing overshoot",
                 "Departure not observed", "Edge deadline exhausted",
                 "Lost launch platform", "Lost rope alignment", "Unexpected or excluded surface")


class NavigationRuntime:
    def __init__(self, app) -> None:
        self.app = app
        self.graph = self.route = self.agent = self.feedback = None
        self.previous = None
        self.last_step = None
        self.ticket = self.lease = None
        self.resume_combat = False
        self.agreed_at = float("-inf")
        self.confirmed: tuple[str, float] | None = None  # last agreed platform and its time
        self.reason = "Track a saved map, then load its navigation routes"
        self.proofs = MoveProofs(app.areas.directory)
        self.failed: set[str] = set()  # computed moves that failed this session
        self.failed_map: str | None = None
        # Generated moves per map: generating them takes seconds on a tall map, and
        # refresh runs on the worker thread right before nav_go checks frame freshness.
        self.moves: tuple[tuple, list] | None = None
        self.counted = 0
        self.pending_proofs: list[tuple[str, str, str, dict]] = []
        self.pending_failures: list[tuple[str, str, str, dict]] = []
        self.exploring: str | None = None  # the unproven move a learn_moves rotation tries
        self.miss: dict | None = None  # a missed move waiting for a safe landing
        self.misses: list[dict] = []  # safe misses in the current farming batch
        self.last_feedback_failure = None
        self.last_input_refusal = None
        self.identity = None
        self.recovery = None
        self.recovery_log = []
        self.recovery_resume_sequence = 0

    def cancel(self, reason: str) -> None:
        if self.recovery:
            self.recovery_log.append({"result": "stopped", "reason": reason})
        self.recovery = None
        self.miss = self.exploring = None
        if self.agent and self.agent.active:
            self.agent.stop(reason)
        if self.lease is not None:
            self.app.controller.release_vertical_lease(self.lease)
        self.lease, self.ticket = None, None
        self.resume_combat = False
        self.reason = reason
        # safe_stop has already released controller input. Disk flushes must not
        # consume the next observation's freshness budget during a route.
        for pending, save in ((self.pending_proofs, self.proofs.record),
                              (self.pending_failures, self.proofs.record_failure)):
            while pending:
                try:
                    save(*pending[0])
                except OSError as error:
                    self.app.note(f"Navigation proof save deferred: {error}")
                    break
                pending.pop(0)

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
        key = (profile["id"], profile["revision"], fingerprint)
        if self.moves is None or self.moves[0] != key:
            self.moves = (key, generate(profile))
        # A move that missed stays off until the generator proposes different geometry.
        current = {m.id: m for m in self.moves[1]}
        missed = {key for key, shape in self.proofs.failures(profile["id"], fingerprint).items()
                  if key in current and shape["kind"] == current[key].kind
                  and shape["trace"] == [list(point) for point in current[key].trace]}
        self.graph = RouteMap.computed(profile, self.proofs.load(profile["id"], fingerprint),
                                       self.failed | missed, self.moves[1],
                                       self.proofs.geometry(profile["id"], fingerprint))
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
        return self._gate(self._route_controls()) or self._pose_blocker()

    def _pose_blocker(self) -> str | None:
        """Refuse routes whose poses lack offline-verified player recognition."""
        try:
            coverage = json.loads((self.app.areas.directory.parent / POSE_COVERAGE)
                                  .read_text("utf-8"))
            verified = {str(pose) for pose in coverage["verified"]}
        except (OSError, ValueError, KeyError, TypeError):
            return "Verify player recognition offline first: python -m tools.recognition_eval"
        ropes = {rope["id"] for rope in self.graph.profile["ropes"]}
        gaps = pose_gaps(required_poses(self.route, ropes), verified)
        return "Player recognition unverified for pose: " + ", ".join(gaps) if gaps else None

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
        if getattr(app.position, "automatic", None):
            return "Automatic alignment precision is not verified; navigation input locked"
        if (app.position is not None and map_hash(app.position.profile) != self.graph.fingerprint):
            return "Stop tracking and reload the changed map before navigation"
        if app.area_editing or app.calibrating or app.active_probe is not None:
            return "Finish editing, selection or control probing first"
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

    def walk(self, context, delta, opt_in: bool) -> dict:
        """Use the existing saved calibration for one nearby same-platform target."""
        position = self.app.position
        if not position or not getattr(position, "calibration", None):
            raise ValueError("Short walk requires the existing saved position calibration")
        self.refresh()
        f = self.feedback
        if not f or not f.surface or f.feet is None:
            raise ValueError("Short walk needs a fresh known starting platform")
        self.route = self.graph.plan(f.surface, f.surface, origin_feet=f.feet)
        walk = ShortWalk(self.graph, self.route, time.perf_counter(), f.feet, delta,
                         pulse=min(.08, self.app.config.input.max_action_seconds))
        return self.start(context, opt_in, walk=walk)

    def start(self, context, opt_in: bool, *, edge: bool = False, walk=None) -> dict:
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
        self.agent = walk or (EdgeStep(self.graph, time.perf_counter(), pulse=pulse) if edge else
                      Navigator(self.graph, self.route, time.perf_counter(), pulse=pulse))
        self.reason = "Focus the game; navigation countdown is bounded and cancelable"
        return self.snapshot()

    def handoff(self, target: str, now: float, *, explore: bool = False) -> str | None:
        """Armed combat found its platform clear: route on without a new countdown.

        With `explore`, the route is one unproven move to a neighbour; replans still use
        proven moves only. Returns why the move was refused; the caller stops safely
        instead of retrying.
        """
        f = self.feedback
        if not self.graph or not f or not f.surface:
            return "Rotation: current platform unknown"
        try:
            self.route = (self.graph.plan(f.surface, target, max_edges=1, origin_feet=f.feet)
                          if explore else
                          self.graph.plan(f.surface, target, trusted_only=True,
                                          origin_feet=f.feet))
        except ValueError as error:
            return f"Rotation: {error}"
        blocker = self.blocker()
        if blocker:
            return f"Rotation: {blocker}"
        self._release()
        self.exploring, self.miss = (self.route.edges[0].id if explore else None), None
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
                     and player.confidence >= self.app.config.perception.confidence
                     and observation.camera_shift is not None
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
        window = self.app.windows.get(self.app.hwnd) if self.app.hwnd else None
        feedback = Feedback(now, map_hash(profile), feet,
                            position.get("surface_id") if position
                            and not position.get("provisional") else None,
                            motion, max(0, time.perf_counter() - now),
                            bool(window and window.focused and not self.app.capture_only))
        identified = bool(player and not player.tracked and math.isfinite(player.confidence)
                          and player.confidence >= self.app.config.perception.confidence)
        # A sprite continuing the named track carries that name, as in combat recovery.
        identity = ((getattr(player, "identity", None) or player.template.removesuffix(":tag-only"))
                    if identified else None)
        if (identity and self.identity and self.identity.startswith("nametag:")
                and not identity.startswith("nametag:")):
            identified, identity = False, None  # Not carried by the named track: may be another.
        navigating = (self.app.mode == "navigation" and isinstance(self.agent, Navigator)
                      and self.agent.active)
        # A drop or climb rides the marker in its corridor; the name tag blurs at fall speed.
        if (navigating and not identified and self.recovery is None
                and not self._marker_flight(feedback)):
            self._begin_recovery(feedback)
        self.feedback = feedback
        if self.recovery:
            self._recover(identity)
        elif identified and identity:
            if (navigating and self.identity and self.identity.startswith("nametag:")
                    and identity.startswith("nametag:") and identity != self.identity):
                self.app._stop("PLAYER_UNCERTAIN", "Player identity changed during navigation")
            elif not self.identity or identity.startswith("nametag:") or not navigating:
                self.identity = identity

    def _begin_recovery(self, feedback: Feedback) -> None:
        app = self.app
        if isinstance(self.agent, ShortWalk):
            app._stop("PLAYER_UNCERTAIN", "Short walk player recognition lost; no retry")
            return
        if not self.identity:
            app._stop("PLAYER_UNCERTAIN", "No confirmed player identity for recovery")
            return
        if self.lease is not None:
            with app.controller.lock:
                lease = app.controller.leases.get(self.lease)
                expired = (lease is None or time.perf_counter() >= lease.deadline
                           or time.perf_counter() >= lease.total_deadline)
            if expired:
                app._stop("POLICY_STOP", "Navigation vertical lease expired")
                return
        if (not feedback.feet or not feedback.focused or feedback.age > .5
                or feedback.fingerprint != self.agent.route.fingerprint):
            app._stop("PLAYER_UNCERTAIN", "Recovery requires fresh map/marker and focus")
            return
        if not app.controller.suspend(lease=self.lease):
            app._stop("INPUT_BACKEND_FAILURE", "Cannot suspend navigation input")
            return
        self.ticket = self.lease = None
        self.recovery = {"started": time.perf_counter(), "identity": self.identity,
                         "matches": 0, "first_match": None,
                         "target": self.agent.route.target,
                         "source": app.source_generation, "view": app.view_generation}
        self.agent.pause_for_recognition()  # Route and edge clocks keep running.
        self.reason = "Recognition paused; keys released; reacquiring the same player"
        self.recovery_log.append({"result": "paused", "identity": self.identity})
        self.recovery_log = self.recovery_log[-16:]

    def recovery_block_reason(self) -> str | None:
        r, f = self.recovery, self.feedback
        if not r:
            return None
        if not self.app.controller.suspended:
            return "Recognition recovery requires suspended input"
        if time.perf_counter() - r["started"] >= RECOGNITION_RECOVERY_SECONDS:
            return "Player recognition recovery timed out"
        if (not self.agent or not self.agent.active or self.agent.route.target != r["target"]
                or self.app.source_generation != r["source"]
                or self.app.view_generation != r["view"]):
            return "Navigation context changed during recognition recovery"
        if (not f or time.perf_counter() - f.now > .5 or not f.feet or not f.focused
                or f.fingerprint != self.agent.route.fingerprint
                or self.graph.path_blocker((f.feet, f.feet))):
            return "Fresh map/marker or focus lost during recognition recovery"
        return None

    def _recover(self, identity: str | None) -> None:
        r = self.recovery
        if reason := self.recovery_block_reason():
            self.app._stop("PLAYER_UNCERTAIN", reason)
            return
        if identity != r["identity"] or not self.feedback.motion_ok:
            if identity and identity.startswith("nametag:") and identity != r["identity"]:
                self.app._stop("PLAYER_UNCERTAIN", "Different player found during recovery")
                return
            r["matches"], r["first_match"] = 0, None
            return
        r["matches"] += 1
        if r["first_match"] is None:
            r["first_match"] = self.feedback.now
        if r["matches"] < 2 or self.feedback.now - r["first_match"] < .15:
            return
        self.recovery = None
        if not self.app.controller.resume():
            if self.app.mode == "navigation" and self.agent and self.agent.active:
                self.recovery = r  # Old canceled input may still be finishing its release.
            return
        self.recovery_log.append({"result": "resumed", "identity": identity,
                                  "seconds": round(time.perf_counter() - r["started"], 3)})
        self.recovery_resume_sequence = self.app.sequence
        self.reason = "Player reacquired from fresh agreeing frames; same route resumed"

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
        if self.recovery:
            return self.recovery_block_reason()
        value = self.feedback_status()
        if value["trusted"]:
            return None
        self.last_feedback_failure = value
        return ("Navigation fused position is stale or uncertain: "
                + json.dumps(value, sort_keys=True))

    def _marker_flight(self, f) -> bool:
        """A drop or climb in flight, marker inside its corridor within the edge budget."""
        agent = self.agent
        if (not f or f.feet is None or not isinstance(agent, Navigator)
                or agent.stage != "flight" or agent.index >= len(agent.route.edges)):
            return False
        edge = agent.route.edges[agent.index]
        return (edge.kind in {"drop", "climb"}
                and 0 <= f.now - agent.edge_started < 8
                and distance(f.feet, edge.trace) <= 64
                and not agent.graph.path_blocker((f.feet, f.feet)))

    def _trusted_feedback(self, f, now: float) -> bool:
        if getattr(getattr(self.app, "position", None), "automatic", None):
            return False
        if not f or now - f.now > .5:
            return False
        agent = self.agent
        if isinstance(agent, ShortWalk):
            return f.motion_ok and f.feet is not None and f.surface == agent.route.origin
        if isinstance(agent, EdgeStep):
            # Marker-only by design; EdgeStep bounds its own time, direction and progress.
            return f.feet is not None and agent.active
        if self._marker_flight(f):
            return True
        return f.motion_ok or (
            f.feet is not None and self.agent is not None
            and self.agent.stage in {"settle_origin", "approach", "flight"}
            and f.now - self.agreed_at <= FLIGHT_GRACE_SECONDS)

    def tick(self, suggestion: str | None, now: float) -> None:
        self.last_step = None
        app = self.app
        if app.mode not in {"navigation", "navigation_wait"}:
            return
        if app.mode == "navigation_wait" and now < app.pending_at:
            return
        if isinstance(self.agent, ShortWalk) and app.mode == "navigation":
            if reason := self.agent.budget_blocker(now):
                app._stop("NAVIGATION_FAILURE", reason)
                return
        if not self.agent or not self.feedback:
            app._stop("PLAYER_UNCERTAIN", "Navigation feedback unavailable")
            return
        f = self.feedback
        if reason := self.feedback_block_reason():
            app._stop("PLAYER_UNCERTAIN", reason)
            return
        if self.recovery:
            # The watchdog still evaluates physical gates, but the suspended controller
            # cannot dispatch keys. Route and lease budgets are never reset by recovery.
            if app.stop_requested.is_set() or app._input_block_reason():
                app._stop("FOCUS_LOSS", "Navigation safety gate lost during recovery")
            return
        airborne = not f.motion_ok
        if app.stop_requested.is_set() or app._input_block_reason():
            app._stop("FOCUS_LOSS", "Navigation focus/capture/input gate lost")
            return
        if self.miss is not None:
            self._settle_miss(f, now)
            return
        if app.mode == "navigation_wait":
            app.controller.enable()
            # A new run gets its own stop record, time and clip, as probes and arming do.
            app._clear_stop_banner()
            app.mode = "navigation"
            app._start_sustain()
            pulse = min(.12, app.config.input.max_action_seconds)
            if isinstance(self.agent, ShortWalk):
                self.agent = ShortWalk(self.graph, self.route, now, self.agent.origin,
                                       self.agent.delta, pulse=min(.08, pulse))
            else:
                self.agent = (EdgeStep(self.graph, now, pulse=pulse)
                              if isinstance(self.agent, EdgeStep)
                              else Navigator(self.graph, self.route, now, pulse=pulse))
            self.counted = 0
        if self.ticket is not None and self.ticket not in app.arbiter.in_flight:
            self.ticket = None
        if self.ticket is not None and not isinstance(self.agent, EdgeStep):
            # A key pulse is still running. Stepping now could choose a takeoff that the
            # busy lane would drop while the navigator believes it was sent.
            # Waiting must not hide expired budgets; use the normal failure/Stop path.
            if reason := self.agent.budget_blocker(now):
                self.agent.stop(reason)
            else:
                return
        if isinstance(self.agent, EdgeStep):
            motion = self.agent.step(f)
        else:
            effective = replace(f, motion_ok=True, marker_only=True) if airborne else f
            if type(self.agent) is Navigator:
                motion, self.last_step = recorded_step(self.agent, effective)
            else:
                motion = self.agent.step(effective)
            self._learn()
        if not self.agent.active:
            if self.agent.stage == "arrived" and self.resume_combat:
                self._release()
                self.resume_combat = False
                app.resume_combat(self.route.target, now)
                return
            if self.agent.stage == "stopped" and self._begin_miss(now):
                return
            # A failed route alarms like any other failure; arriving stops quietly.
            app._stop("NAVIGATION_FAILURE" if self.agent.stage == "stopped" else "POLICY_STOP",
                      self.agent.reason)
            return
        if motion.horizontal:
            proposal = Action(motion.horizontal, app.config.input.max_action_seconds)
        elif motion.vertical:
            proposal = Action(motion.vertical, .1)
        else:
            proposal = (Action(motion.holds[0].action, motion.holds[0].seconds)
                        if motion.holds else Action())
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
        if choice.action is None:
            self._release()
            return
        if motion.release:
            self._release()
        elif motion.vertical or motion.horizontal:
            if not motion.horizontal:
                app.controller.release_movement()
            if motion.vertical:
                if self.lease is not None:
                    lease = app.controller.leases.get(self.lease)
                    if lease is not None and lease.action != motion.vertical:
                        app.controller.release_vertical_lease(self.lease)
                        self.lease = None
                if self.lease is None:
                    self.lease = app.controller.start_vertical_lease(motion.vertical)
                elif not app.controller.renew_vertical_lease(self.lease):
                    app._stop("POLICY_STOP", "Navigation vertical lease expired")
                    return
            elif self.lease is not None:
                app.controller.release_vertical_lease(self.lease)
                self.lease = None
            if motion.horizontal:
                result = app.controller.refresh_movement(
                    motion.horizontal, app.config.input.max_action_seconds, navigation=True)
                if not result.startswith(("held:", "deferred:")):
                    app._stop("INPUT_BACKEND_FAILURE", result)
                    return
            if motion.holds and self.ticket is None:
                submitted = app.controller.submit_sequence(motion.holds, preserve_movement=True)
                if isinstance(submitted, int):
                    self.ticket = submitted
                    app.arbiter.submitted(submitted, "navigation")
                else:
                    app._stop("INPUT_BACKEND_FAILURE", str(submitted))
        elif motion.holds and self.ticket is None:
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
                self.pending_proofs.append((graph.profile["id"], graph.fingerprint, edge.id, {
                    "from": edge.source, "to": edge.target, "kind": edge.kind,
                    "trace": [list(point) for point in edge.trace]}))
                graph.proven.add(edge.id)
        elif (agent.stage == "stopped" and agent.reason.startswith(MOVE_FAILURES)
              and agent.index < len(agent.route.edges)):
            self.failed.add(agent.route.edges[agent.index].id)

    def _begin_miss(self, now: float) -> bool:
        """A learn_moves batch's unproven move failed: release keys and await the landing.

        Only the batch's own explore move qualifies, at most MISS_LIMIT times; every
        feedback, focus and input gate still runs each frame while it lands.
        """
        app, agent = self.app, self.agent
        if (self.exploring is None or not self.resume_combat or not app.learning_moves
                or app.farming is None or len(self.misses) >= MISS_LIMIT
                or not isinstance(agent, Navigator) or agent.completed):
            return False
        self._release()
        self.miss = {"edge": self.exploring, "reason": agent.reason, "since": now,
                     "surface": None, "feet": None, "settled_at": None}
        self.reason = f"Move missed ({agent.reason}); waiting for a safe landing"
        app.note(self.reason)
        return True

    def _settle_miss(self, f: Feedback, now: float) -> None:
        """Resume combat once the player stands still on a known platform; else stop."""
        app, miss = self.app, self.miss
        platforms = {p["id"] for p in self.graph.profile["platforms"]}
        surface = (f.surface if f.motion_ok and f.feet is not None and f.surface in platforms
                   and f.surface not in self.graph.excluded else None)
        steady = (surface is not None and miss["surface"] == surface
                  and miss["feet"] is not None and abs(f.feet[0] - miss["feet"][0]) <= 8
                  and abs(f.feet[1] - miss["feet"][1]) <= 3)
        if not steady:
            miss["settled_at"] = f.now if surface else None
        miss["surface"], miss["feet"] = surface, f.feet
        if surface is not None and f.now - miss["settled_at"] >= .3:
            edge = self.graph.edges.get(miss["edge"])
            self.failed.add(miss["edge"])
            if edge is not None:
                self.pending_failures.append((
                    self.graph.profile["id"], self.graph.fingerprint, edge.id,
                    {"from": edge.source, "to": edge.target, "kind": edge.kind,
                     "trace": [list(point) for point in edge.trace]}))
            self.misses.append({"edge": miss["edge"], "reason": miss["reason"],
                                "landed": surface, "at": time.time()})
            app.combat_evidence.record(
                "decision", f"move miss {miss['edge']}; landed on {surface}",
                action="navigation")
            app.note(f"Missed {miss['edge']}; landed safely on {surface}, "
                     f"{len(self.misses)}/{MISS_LIMIT} misses")
            self.miss = self.exploring = None
            self.resume_combat = False
            graph = self.graph  # the missed move leaves the graph, without disk reads
            self.graph = RouteMap.computed(graph.profile, graph.proven, moves=[
                Move(e.id, e.source, e.target, e.kind, e.trace)
                for e in graph.edges.values() if e.id != miss["edge"]])
            app.resume_combat(surface, now)
        elif now - miss["since"] >= MISS_SETTLE_SECONDS:
            app._stop("NAVIGATION_FAILURE", f"{miss['reason']}; no safe landing within "
                                            f"{MISS_SETTLE_SECONDS:g} s")

    def snapshot(self) -> dict:
        value = self.agent.snapshot() if self.agent else {
            "stage": "preview" if self.route else "idle", "reason": self.reason,
            "active": False, "route": self.route.snapshot() if self.route else None}
        recovery = {"active": self.recovery is not None,
                    "input_suspended": self.app.controller.suspended,
                    "marker_fresh": bool(self.feedback and self.feedback.feet
                                         and 0 <= time.perf_counter() - self.feedback.now <= .5),
                    "map_hash": self.feedback.fingerprint if self.feedback else None,
                    "pending_publication": bool(self.recovery_resume_sequence and (
                        not self.app.published_frame or self.app.published_frame["sequence"]
                        < self.recovery_resume_sequence)),
                    "remaining_seconds": max(0, RECOGNITION_RECOVERY_SECONDS
                                             - (time.perf_counter() - self.recovery["started"]))
                    if self.recovery else 0, "events": self.recovery_log[-16:]}
        return {**value, "map": self.graph.snapshot() if self.graph else None,
                "code": getattr(self, "code_revision", None),
                "recovery": recovery,
                **({"stage": "reacquire_player", "reason": self.reason} if self.recovery else {}),
                "feedback": self.feedback_status(),
                "learning": {"exploring": self.exploring, "miss_pending": self.miss is not None,
                             "misses": self.misses, "limit": MISS_LIMIT},
                "last_feedback_failure": self.last_feedback_failure,
                "last_input_refusal": self.last_input_refusal,
                **({"stage": "countdown", "reason": self.reason, "active": True}
                   if self.app.mode == "navigation_wait" else {}),
                "ready": self.blocker() is None, "blocker": self.blocker(),
                "edge_blocker": self._gate({"left", "right"}, edge=True) if self.graph
                else "Track a saved map first"}
