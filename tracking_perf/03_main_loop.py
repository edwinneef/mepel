# src/maplebot/runtime.py, class Application -- revised method excerpts only.
# Merge these methods into the existing class; do NOT overwrite runtime.py.
# Original line-range labels are retained as merge locations, not current lines.
# All policy, freshness, focus, stop and ownership guards are retained.
# New timing fields reveal work previously hidden inside the frame loop.
# _pace itself was not supplied: verify its configured FPS cap in the real project.
# previous_pace_ms/previous_loop_ms describe the prior completed iteration, while
# latency_ms/fps retain their original meaning (measured before publication).
# Copying encoder inputs remains intentional until its ownership contract is audited.


    # ---- _process (runtime.py:2202-2677) ----
    def _process(
        self, image: Image, now: float, policy_now: float | None = None,
        *, captured_at: float | None = None,
    ) -> tuple[Image, dict]:
        policy_now = now if policy_now is None else policy_now
        self.processing_frame = {
            "sequence": self.sequence, "capture_clock": now, "stage": "map",
            "source_generation": self.source_generation, "view_generation": self.view_generation,
        }
        # Camera motion needs only the frame; start it beside the minimap read.
        self.detector.begin_frame(image)
        map_began = time.perf_counter()
        captured_at = time.time() if captured_at is None else captured_at
        fix = self.position.read_map(image) if self.position is not None else None
        map_ms = (time.perf_counter() - map_began) * 1000
        self.detector.taught_map = bool(fix and fix.canvas)
        self.detector.enemy_source = (self.session_id, self.source_generation)
        self.detector.strip = (self.navigation.search_strip(image.shape[1])
                               if self.mode in {"navigation", "navigation_wait"} else None)
        # Navigation/probes prioritize position freshness; idle view keeps enemy outlines.
        movement_probe = (self.mode.startswith("probe") and self.active_probe is not None
                          and self.active_probe.action in {"left", "right", "up", "down", "jump"})
        self.monster_search = not (
            movement_probe or self.mode in {"navigation", "navigation_wait"})
        perception_began = time.perf_counter()
        self.processing_frame = {**self.processing_frame, "stage": "perception"}
        observation = self.detector.detect(image, now, monsters=self.monster_search)
        self._auto_track(image, now)
        if (getattr(self, "auto_area_pending", False) and not self.area_editing
                and self.mode in {"capture", "dry_run"}
                and now >= getattr(self, "auto_area_retry_at", 0)):
            self.auto_area_retry_at = now + 1
            from .automatic_area import create_area

            try:
                area_id = create_area(self.areas, image, self.detector.map_filter)
                if area_id is not None:
                    self._position_command("position_start", {"area_id": area_id})
                    self.auto_area_pending = False
            except (ValueError, OSError) as error:
                self.note(f"Automatic area waiting: {error}")
        pose_began = time.perf_counter()
        self.pose_collection.observe(
            image, self.detector, observation, now, captured_at,
            (self.session_id, self.source_generation),
            eligible=bool(self.monster_search and self.calibration and
                          self.calibration.capture_verified and not self.calibrating),
        )
        perception_ms = (time.perf_counter() - perception_began) * 1000
        perception_stages = {**getattr(self.detector, "stage_ms", {}),
                             "pose": round((time.perf_counter() - pose_began) * 1000, 1)}
        evidence = summarize({
            "frame": {"id": f"{self.session_id}:{self.sequence}", "available": True,
                      "captured_at": captured_at},
            "player": asdict(observation.player) if observation.player else None,
            "monsters": [asdict(item) for item in observation.monsters],
        }, self.config, time.time())
        scan_feedback = getattr(self.detector, "enemy_scan_feedback", None)
        if scan_feedback is not None:
            scan_feedback(evidence["frame_id"], fresh=evidence["fresh_player"],
                          eligible=bool(evidence["same_platform_targets"]))
        self.combat_evidence.observe({
            "frame_id": evidence["frame_id"], "captured_at": captured_at,
            "same_platform_targets": evidence["same_platform_targets"],
            "note": "Observation at collection, not proof of the keypress frame or a hit",
        })
        position = None
        position_began = time.perf_counter()
        self.processing_frame = {**self.processing_frame, "stage": "position"}
        if self.position is not None and fix is not None:
            try:
                position = self.position.update(image, fix, observation, now,
                                                captured_at=captured_at,
                                                input_timing=self.controller.timing_snapshot(),
                                                movement_keys=(self.config.input.left,
                                                               self.config.input.right),
                                                observation_context=(self.source_generation,
                                                                     self.view_generation),
                                                allow_supplement=self.capture_only
                                                and self.mode == "capture" and not self.area_editing
                                                and not self.calibrating
                                                and self.active_probe is None,
                                                passive_calibration=self.mode in {
                                                    "capture", "dry_run"}
                                                and not self.area_editing
                                                and not self.calibrating
                                                and self.active_probe is None)
                learned = position["calibration"]["learned"]
                if learned:
                    residual = learned["calibration"]["residual_px"]
                    self.note(
                        f"Walk calibration learned passively: {learned['calibration']['pairs']} "
                        f"pairs, residual p95 x {residual['x']['p95']:.1f} / "
                        f"y {residual['y']['p95']:.1f} px")
            except (ValueError, cv2.error) as error:
                position = {"kind": "unknown", "reason": f"Position unavailable: {error}",
                            "captured_at": captured_at, "input_sent": False}
        self.navigation.observe(fix, observation, position, now)
        position_ms = (time.perf_counter() - position_began) * 1000
        self.processing_frame = {**self.processing_frame, "stage": "policy"}
        if (
            self.calibration
            and not self.calibration.capture_verified
            and not self.calibrating
            and self.mode in {"capture", "dry_run"}
            and self.hwnd
            and time.perf_counter() - now <= 0.5
        ):
            window = self.windows.get(self.hwnd)
            crop = self.calibration.crop
            if (
                self.config.capture.window_title.casefold() in window.title.casefold()
                and self.calibration.valid_for(window)
                and image.shape[:2] == (crop.height, crop.width)
                and self.windows.unobscured(
                    window.hwnd, crop.translated(window.client.x, window.client.y)
                )
            ):
                player = observation.player
                player_recognized = bool(
                    player and not player.tracked
                    and player.confidence >= self.config.perception.confidence
                )
                hud_recognized = any(
                    reading.percent is not None and reading.confidence >= 0.9
                    for reading in (
                        self._resource_reading(resource, image) for resource in ("hp", "mp")
                    )
                )
                if player_recognized or hud_recognized:
                    self.calibration.capture_verified = True
                    self._restore_probes(clear_results=False)
                    self.note("Game view verified by confident player or HUD recognition")
        for outcome in self.controller.poll_outcomes():
            self.potion_evidence.outcome(outcome)
            self.combat_evidence.record("input_outcome", outcome.result, **asdict(outcome))
            self.arbiter.finished(outcome.ticket)
            self.last_action = outcome.result
            self.policy_outcome = {"status": "completed", **asdict(outcome)}
            self._handle_probe_outcome(outcome)
            if outcome.ticket == self.live_potion_ticket:
                self.live_potion_ticket = None
                if outcome.result.endswith("completed"):
                    self.potter.input_sent = True
                    self.note(f"Live potion key completed: {outcome.action}; effect unconfirmed")
                else:
                    self._stop("INPUT_BACKEND_FAILURE", "Live potion key did not complete")
        if self.mode in {"potion_wait", "potion_live"}:
            if self.capture_only:
                self._stop("CAPTURE_ONLY_GUARD", "Capture-only session: keyboard output locked")
            elif self.windows.pressed(KEYS[self.config.input.emergency_key]):
                self._stop("EMERGENCY_STOP", "Emergency hotkey canceled live potions")
            elif self.mode == "potion_live" or now >= self.pending_at:
                blocker = self._input_block_reason()
                if blocker or self.calibrating or self.stop_requested.is_set():
                    self._stop("FOCUS_LOSS", blocker or "Live potions stopped for calibration")
                elif time.perf_counter() - now > 0.5:
                    self._stop("PLAYER_UNCERTAIN", "Stale HUD frame; live potions stopped")
                elif self.mode == "potion_wait":
                    self._clear_stop_banner()
                    self.potter.start(live=True)
                    self.mode = "potion_live"
                    self.stop_reason = "Live potions enabled; combat remains stopped"
        if self.capture_only and self.mode in {
            "live", "pending_arm", "probe_wait", "navigation", "navigation_wait",
        }:
            self._stop("CAPTURE_ONLY_GUARD", "Capture-only session: keyboard output locked")
        if self.stop_requested.is_set() and self.mode != "capture":
            self._stop("CALIBRATION", "Operator stop or calibration requested")
        if self.controller.reason == "Emergency stop hotkey" and (
            self.mode != "capture" or self.potter.enabled
        ):
            self._stop("EMERGENCY_STOP", "Emergency stop hotkey")
        slow = time.perf_counter() - now > 0.5
        # Waiting for the operator or a potion effect sends nothing, so a slow frame is harmless.
        if slow and self.mode in {"live", "navigation", "navigation_wait"}:
            self._stop("PLAYER_UNCERTAIN", "Observation processing exceeded 500 ms; no input sent")
        if self.mode in {"pending_arm", "probe_wait"}:
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                self._stop("EMERGENCY_STOP", "Emergency hotkey canceled pending input")
            elif slow and now >= self.pending_at + PENDING_SLOW_GRACE_SECONDS:
                if self.active_probe is not None:
                    self._finish_probe(
                        self.active_probe, "cancelled", "Recognition stayed slower than 500 ms"
                    )
                self._stop(
                    "PLAYER_UNCERTAIN",
                    "Recognition stayed slower than 500 ms per frame; pending input canceled",
                )
            elif slow:
                pass  # Never press on a stale frame; wait for the next timely one.
            elif now >= self.pending_at:
                if not self._player_ready(observation.player):
                    raise RuntimeError("Player detection uncertain; input probe/arming canceled")
                pending = self.mode
                # Status takes stop_lock before controller.lock. Keep that order
                # while enabling input and clearing the previous stop banner.
                with self.stop_lock, self.controller.lock:
                    if self.stop_requested.is_set():
                        self._stop("OPERATOR_STOP", "Operator stopped pending input")
                        return self._process(image, now, captured_at=captured_at)
                    try:
                        self.controller.enable()
                    except RuntimeError:
                        if pending != "probe_wait":
                            raise
                        reason = self._input_block_reason() or (
                            "Input safety changed or the emergency key was held; probe canceled"
                        )
                        if self.active_probe is not None:
                            self._finish_probe(self.active_probe, "cancelled", reason)
                        self._stop("PROBE_COMPLETE", reason)
                        return self._process(image, now, captured_at=captured_at)
                    self._clear_stop_banner()
                if pending == "probe_wait":
                    active = self.active_probe
                    if active is None or active.phase != "countdown":
                        self._stop("PROBE_COMPLETE", "Probe was canceled before key submission")
                        return self._process(image, now, captured_at=captured_at)
                    action = active.action
                    duration = min(0.12, self.config.input.max_action_seconds)
                    submitted = self.controller.submit(Action(action, duration), disable_after=True)
                    self.last_action = f"probe {submitted} queued"
                    if isinstance(submitted, int):
                        self.combat_evidence.record("queued", action, ticket=submitted)
                        self.active_probe = replace(active, phase="queued", ticket=submitted)
                        self.mode = "probe_queued"
                    else:
                        self._finish_probe(active, "failed", "Control probe could not be queued")
                        self._stop("INPUT_BACKEND_FAILURE", "Control probe could not be queued")
                        self.mode = "capture"
                else:
                    self.mode = "live"
                    self.agent.start()
                    self.reacquisition.reset()
                    self._start_sustain()
                    if self.config.recording.auto:
                        self.recorder.start("combat")
        if self.mode == "live" and (
            not self.controller.enabled or self.controller.stopped.is_set()
        ):
            self._stop("INPUT_BACKEND_FAILURE", self.controller.reason)
        potion_evidence_safe = bool(
            self.calibration
            and self.calibration.capture_verified
            and not self.calibrating
            and not self.stop_requested.is_set()
            and time.perf_counter() - now <= 0.5
            and self.window
            and self.region
            and self.windows.unobscured(self.window.hwnd, self.region)
        )
        potter = self.potter.observe(
            image, now, safe=potion_evidence_safe,
        )
        mp = potter["readings"].get("mp", {})
        self.mp_percent = mp.get("percent") if mp.get("confidence", 0) >= 0.9 else None
        if self.mode == "navigation" and self.sustain:
            readings = potter["readings"]
            if (readings.get("hp", {}).get("percent") == 0 or any(
                    readings.get(r, {}).get("percent") is None
                    or readings[r]["confidence"] < .9 for r in self.sustain)):
                self._stop("PLAYER_UNCERTAIN", "Navigation sustain HUD unreadable or HP empty")
        if self.farming and self.mode in {"live", "navigation"}:
            if reason := self.farming.check(now, potter["readings"], potion_evidence_safe):
                self._stop("POLICY_STOP", reason)
        if self.farming and self.mode == "navigation":
            self.farming.progress(now, active=True)
        self.navigation.tick(potter["suggestion"], now)
        if self.mode == "live" and self.sustain:
            readings = potter["readings"]
            if readings.get("hp", {}).get("percent") == 0:
                self._stop("PLAYER_UNCERTAIN", "HP empty; combat stopped")
            elif any(
                readings.get(r, {}).get("percent") is None or readings[r]["confidence"] < 0.9
                for r in self.sustain
            ):
                if self.potion_hud_missing_since is None:
                    self.potion_hud_missing_since = now
                if now - self.potion_hud_missing_since >= 5.0:
                    self._stop("PLAYER_UNCERTAIN", "HUD unreadable for 5 seconds; combat stopped")
            else:
                self.potion_hud_missing_since = None
        if self.mode in {"live", "dry_run"}:
            policy_began = time.perf_counter()
            uncertain = (
                observation.player is None
                or observation.player.confidence < self.config.perception.confidence
            )
            if uncertain and not self.player_uncertain and self.recorder.active:
                self.recorder.trigger("Player detection uncertain", time.perf_counter())
            self.player_uncertain = uncertain
            if self.policy_outcome.get("status") == "pending":
                movement = self.controller.running_movement(self.policy_outcome.get("ticket"))
                if movement is not None:
                    self.policy_outcome = {**self.policy_outcome, "status": "held",
                                           "action": movement, "result": f"{movement} held"}
            policy_input = PolicyInput(
                observation, policy_now, self.policy_outcome, self.mp_percent,
                self._combat_platforms(position), immediate_actions=True,
            )
            policy_before = self.agent.snapshot()
            paused = self._reacquire(observation.player, now)
            if paused is not None:
                decision = Decision(self.agent.state, Action(), paused, self.agent.target)
            else:
                decision = self.agent.step_input(policy_input)
                moving = None if decision.state == "IDLE" else self._rotate(
                    decision, observation, now)
                if decision.state == "IDLE":
                    self._stop("PLAYER_UNCERTAIN" if uncertain else "POLICY_STOP", decision.reason)
                    self.policy_outcome = {"status": "not_sent"}
                elif moving:
                    decision = replace(decision, reason=moving)
                    self.last_action = moving
                    self.policy_outcome = {"status": "not_sent"}
                elif self.mode == "live":
                    if decision.state == "SEARCH" or self.agent.missing_frames:
                        for ticket, lane in tuple(self.arbiter.in_flight.items()):
                            if lane == "combat":
                                self.controller.cancel_ticket(ticket)
                    renew_movement = False
                    if (decision.state == "APPROACH" and decision.action.kind in {"left", "right"}
                            and decision.target is not None and observation.player is not None):
                        gap = abs(decision.target.box.center[0] - observation.player.box.center[0])
                        # Use short steps near attack range; bridge frame gaps only well outside it.
                        margin = max(self.config.agent.attack_range,
                                     observation.player.box.width * 2)
                        renew_movement = gap - self.config.agent.attack_range > margin
                        if renew_movement:
                            decision = replace(decision, action=Action(
                                decision.action.kind, self.config.input.max_action_seconds,
                            ))
                    submitted = self._arbitrate(
                        decision.action, potter["suggestion"], renew_movement=renew_movement,
                    )
                    held = submitted == f"held: {decision.action.kind}"
                    if self.farming:
                        active = (decision.action.kind != "release"
                                  and (isinstance(submitted, int) or held))
                        if reason := self.farming.progress(now, active=active):
                            self._stop("POLICY_STOP", reason)
                    if (self.mode == "live" and decision.action.kind != "release"
                            and not isinstance(submitted, int) and not held):
                        self.agent.defer_action(policy_before)
                        decision = Decision(self.agent.state, decision.action,
                                            f"{decision.action.kind.capitalize()} {submitted}",
                                            decision.target)
                    self.last_action = (
                        f"{decision.action.kind} queued ({submitted})"
                        if isinstance(submitted, int)
                        else submitted
                    )
                    if decision.action.kind != "release":
                        self.combat_evidence.record("decision", self.last_action,
                                                    action=decision.action.kind,
                                                    ticket=submitted if isinstance(submitted, int)
                                                    else None,
                                                    acquisition=self.agent.acquisitions)
                    self.policy_outcome = (
                        {"status": "held", "action": decision.action.kind,
                         "result": f"{decision.action.kind} held"} if held else
                        {"status": "pending", "ticket": submitted}
                        if isinstance(submitted, int)
                        else {"status": "not_sent", "result": submitted}
                    )
                else:
                    self.last_action = f"dry run: intended {decision.action.kind}"
                    self.policy_outcome = {"status": "not_sent"}
            if self.status.get("reason") != decision.reason or decision.action.kind != "release":
                self.note(f"{decision.state}: {decision.reason} · {self.last_action}")
            policy_ms = (time.perf_counter() - policy_began) * 1000
        else:
            reason = self.navigation.reason if self.mode == "navigation" else self.stop_reason
            if self.mode in {"pending_arm", "probe_wait", "potion_wait"}:
                reason = f"Focus the game window; input in {max(0, self.pending_at - now):.1f}s"
            decision = Decision(self.agent.state, Action(), reason)
            policy_input = PolicyInput(
                observation, policy_now, self.policy_outcome, self.mp_percent
            )
            policy_before = self.agent.snapshot()
            policy_ms = 0.0
        annotation_began = time.perf_counter()
        annotated = annotate(image, observation, decision.target, decision.state, decision.reason)
        if self.mode == "potion_live":
            unreadable = any(
                self.potter.settings[f"{r}_threshold"] > 0
                and (
                    potter["readings"].get(r, {}).get("percent") is None
                    or potter["readings"][r]["confidence"] < 0.9
                )
                for r in ("hp", "mp")
            )
            if potter["readings"].get("hp", {}).get("percent") == 0:
                self._stop("PLAYER_UNCERTAIN", "HP empty; live potions stopped")
            elif unreadable:
                self.live_potion_ticket = None
                self.controller.stop("Waiting for HUD after transition", notify=False)
                if self.potion_hud_missing_since is None:
                    self.potion_hud_missing_since = now
                if now - self.potion_hud_missing_since >= 5.0:
                    self._stop(
                        "PLAYER_UNCERTAIN", "HUD unreadable for 5 seconds; live potions stopped"
                    )
                else:
                    potter.update(reason="Waiting for HUD after transition; potion input paused")
            else:
                self.potion_hud_missing_since = None
            if not unreadable and potter["suggestion"] and self.live_potion_ticket is None:
                with self.controller.lock:
                    if not self.stop_requested.is_set() and self.mode == "potion_live":
                        try:
                            self.controller.enable()
                            queued_at = time.perf_counter()
                            submitted = self.controller.submit(
                                Action(
                                    f"{potter['suggestion']}_potion",
                                    min(0.06, self.config.input.max_action_seconds),
                                ),
                                disable_after=True,
                            )
                            if not isinstance(submitted, int):
                                raise RuntimeError(str(submitted))
                            self.live_potion_ticket = submitted
                            self.potion_evidence.queued(
                                submitted, potter["suggestion"], queued_at,
                                (self.view_generation, self.source_generation),
                            )
                            self.combat_evidence.record("queued", f"{potter['suggestion']}_potion",
                                                        ticket=submitted)
                        except (RuntimeError, OSError) as error:
                            self._stop("INPUT_BACKEND_FAILURE", f"Live potion stopped: {error}")
            potter.update(self.potter.snapshot())
            if self.mode != "potion_live":
                potter.update(reason=self.stop_reason, suggestion=None)
        self.potter.annotate(annotated, potter)
        self._advance_potion_probe(image, now)
        if potter["suggestion"]:
            self.note(potter["reason"])
        annotation_ms = (time.perf_counter() - annotation_began) * 1000
        return annotated, {
            "state": str(decision.state),
            "reason": decision.reason,
            "player": asdict(observation.player) if observation.player else None,
            "monsters": [asdict(item) for item in observation.monsters],
            "target": asdict(decision.target) if decision.target else None,
            "direction": decision.action.kind
            if decision.action.kind in {"left", "right"}
            else None,
            "last_action": self.last_action,
            "input_timing": self.controller.timing_snapshot(),
            "features": True,
            "capture_only": self.capture_only,
            "autopotter": potter,
            "potion_evidence_safe": potion_evidence_safe,
            "catalog": self.detector.catalog_info,
            "enemy_tracks": [asdict(item) for item in getattr(observation, "enemy_tracks", [])],
            "player_tracking": getattr(observation, "player_tracking", None),
            "position": position,
            "failures": observation.failures,
            "camera_shift": observation.camera_shift,
            "camera_confidence": observation.camera_confidence,
            "policy_input": policy_input.to_dict(),
            "policy_before": policy_before,
            "navigation_step": self.navigation.last_step,
            "decision": asdict(decision),
            "action_outcome": policy_input.last_outcome,
            "stage_timing": {
                "map_ms": round(map_ms, 3),
                "perception_ms": round(perception_ms, 3),
                "perception_stages_ms": perception_stages,
                "player_search_ms": {
                    key: round(value, 3)
                    for key, value in getattr(self.detector, "player_stage_ms", {}).items()
                },
                "position_ms": round(position_ms, 3),
                "policy_ms": round(policy_ms, 3),
                "annotation_ms": round(annotation_ms, 3),
            },
        }

    # ---- _run (runtime.py:2679-2790) ----
    def _run(self) -> None:
        capture: Capture | None = None
        move_failures = 0
        previous = time.perf_counter()
        previous_capture = None
        previous_pace_ms = previous_loop_ms = None
        previous_publish_ms = previous_detection_publish_ms = None
        try:
            capture = Capture(self.windows)
            while not self.closed.is_set():
                began = time.perf_counter()
                self._drain_commands()
                commands_ms = (time.perf_counter() - began) * 1000
                capture_ok = False
                try:
                    capture_began = time.perf_counter()
                    view_generation = self.view_generation
                    captured_at = time.time()
                    if self.hwnd:
                        image, window, region = capture.window(self.hwnd, self.calibration)
                    elif self.manual:
                        image, window, region = capture.grab(self.manual), None, self.manual
                    else:
                        self.closed.wait(0.05)
                        continue
                    capture_finished = time.perf_counter()
                    self.image, self.window, self.region = image, window, region
                    capture_ok = True
                    move_failures = 0
                    if self.session_capture_started is None:
                        self.session_capture_started = capture_began
                    policy_now = capture_began - self.session_capture_started
                    annotated, result = self._process(image, capture_began, policy_now,
                                                      captured_at=captured_at)
                    end = time.perf_counter()
                    status = {
                        **result,
                        "mode": self.mode,
                        "captured_at": captured_at,
                        "capture_clock": capture_began,
                        "source_generation": self.source_generation,
                        "width": image.shape[1],
                        "height": image.shape[0],
                        "sequence": self.sequence,
                        "view_generation": view_generation,
                        "focused": bool(window and window.focused),
                        "window": asdict(window) if window else None,
                        "region": asdict(region),
                        "calibration": asdict(self.calibration) if self.calibration else None,
                        "fps": round(1 / max(0.0001, end - previous), 1),
                        "latency_ms": round(1000 * (end - began), 2),
                        "recording": self.recorder.active,
                    }
                    status["stage_timing"] = {
                        "capture_interval_ms": round(1000 * (capture_began - previous_capture), 3)
                        if previous_capture is not None else None,
                        "capture_ms": round(1000 * (capture_finished - capture_began), 3),
                        "commands_ms": round(commands_ms, 3),
                        "process_ms": round(1000 * (end - capture_finished), 3),
                        "previous_pace_ms": previous_pace_ms,
                        "previous_loop_ms": previous_loop_ms,
                        "previous_publish_ms": previous_publish_ms,
                        "previous_detection_publish_ms": previous_detection_publish_ms,
                        **result["stage_timing"],
                    }
                    previous_capture = capture_began
                    previous = end
                    detection_publish_began = time.perf_counter()
                    self._publish_detections(status, image)
                    previous_detection_publish_ms = round(
                        (time.perf_counter() - detection_publish_began) * 1000, 3)
                    publish_began = time.perf_counter()
                    self.processing_frame = {**(self.processing_frame or {}), "stage": "publish"}
                    packet = FramePacket(
                        self.sequence,
                        f"{self.sequence:08d}",
                        image.copy(),
                        annotated.copy(),
                        status.copy(),
                        policy_now,
                    )
                    self.encoder.publish(packet)
                    previous_publish_ms = round(
                        (time.perf_counter() - publish_began) * 1000, 3
                    )
                    # Preserve the existing field; the previous_* fields above are
                    # complete before either consumer receives this frame.
                    status["stage_timing"]["publish_ms"] = previous_publish_ms
                    self.sequence += 1
                except CaptureMovedError:
                    move_failures = min(move_failures + 1, _CAPTURE_MOVE_ATTEMPTS)
                    self._capture_moved(move_failures)
                    self.closed.wait(_CAPTURE_MOVE_RETRY_SECONDS)
                except Exception as error:
                    move_failures = 0
                    self._stop("CAPTURE_WORKER_FAILURE", str(error))
                    if self.calibration and not capture_ok:
                        self.calibration.capture_verified = False
                        self.calibration.controls_verified = False
                        self.probed.clear()
                    self.image = None
                    self._invalidate_view()
                    reason = str(error)
                    if self.status.get("reason") != reason:
                        self.note(reason)
                    with self.lock:
                        self.status = {
                            "state": "IDLE",
                            "mode": "capture",
                            "reason": reason,
                            "focused": False,
                            "last_action": "none",
                            "features": True,
                            "catalog": self.detector.catalog_info,
                        }
                        self.latest, self.raw = None, None
                pace_began = time.perf_counter()
                self._pace(began)
                loop_finished = time.perf_counter()
                previous_pace_ms = round((loop_finished - pace_began) * 1000, 3)
                previous_loop_ms = round((loop_finished - began) * 1000, 3)
        except Exception as error:
            with self.lock:
                self.status = {"state": "IDLE", "reason": str(error)}
        finally:
            if self.closed.is_set():
                self.controller.stop("Capture worker exited", notify=False)
            else:
                self.safe_stop("CAPTURE_WORKER_EXIT", "Capture worker exited")
            if capture:
                capture.close()

    # ---- _idle_view (runtime.py:2792-2802) ----
    def _idle_view(self) -> bool:
        """Capture mode with nothing running while the attached game is unfocused or covered."""
        if (self.mode != "capture" or not self.hwnd or self.region is None
                or self.calibrating or self.area_editing or self.active_probe is not None
                or self.potter.enabled or self.recorder.active):
            return False
        try:
            window = self.windows.get(self.hwnd)
            return not window.focused or not self.windows.unobscured(window.hwnd, self.region)
        except (OSError, RuntimeError):
            return False

    # ---- _drain_commands (runtime.py:2821-2832) ----
    def _drain_commands(self) -> None:
        while True:
            try:
                name, payload, future = self.commands.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(self._command(name, payload))
            except Exception as error:
                future.set_exception(error)
