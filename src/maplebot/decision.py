"""Deterministic decisions, with no capture or keyboard dependencies."""

import math
from dataclasses import dataclass
from enum import StrEnum

from .config import AgentConfig
from .perception import Detection, Observation


class State(StrEnum):
    IDLE = "IDLE"
    SEARCH = "SEARCH"
    APPROACH = "APPROACH"
    ATTACK = "ATTACK"
    VERIFY = "VERIFY"


@dataclass(frozen=True)
class Action:
    kind: str = "release"
    seconds: float = 0


@dataclass(frozen=True)
class Decision:
    state: State
    action: Action
    reason: str
    target: Detection | None = None


class Agent:
    def __init__(self, config: AgentConfig, confidence: float = 0.9) -> None:
        self.config, self.confidence = config, confidence
        self.state = State.IDLE
        self.target: Detection | None = None
        self.facing: str | None = None
        self.verify_until = 0.0
        self.attempts = 0
        self.acquisitions = 0
        self.missing_frames = 0
        self.last_distance: float | None = None
        self.stalled_steps = 0

    def stop(self, reason: str) -> Decision:
        self.state, self.target, self.facing = State.IDLE, None, None
        self.attempts, self.missing_frames = 0, 0
        self.last_distance, self.stalled_steps = None, 0
        return Decision(self.state, Action(), reason)

    def start(self) -> None:
        self.stop("Starting")
        self.state = State.SEARCH

    def _result(self, reason: str, action: Action | None = None) -> Decision:
        return Decision(self.state, action or Action(), reason, self.target)

    def step(self, observation: Observation, now: float) -> Decision:
        if self.state == State.IDLE:
            return self._result("Stopped; start dry run or arm combat")
        player = observation.player
        if player is None or (player.confidence < self.confidence and not player.tracked):
            return self.stop("Uncertain player; stop and recalibrate templates")
        candidates = [
            monster
            for monster in observation.monsters
            if monster.confidence >= self.confidence
            and abs(monster.box.feet - player.box.feet) <= self.config.platform_tolerance
        ]
        if self.state == State.SEARCH:
            if not candidates:
                return self.stop("No confident same-platform targets; stopped")
            self.target = min(
                candidates, key=lambda item: abs(item.box.center[0] - player.box.center[0])
            )
            self.state, self.attempts, self.missing_frames = State.APPROACH, 0, 0
            self.acquisitions += 1
            self.last_distance, self.stalled_steps = None, 0
            return self._result("Acquired nearest same-platform target")

        if self.target is None:
            return self.stop("Target tracking lost")
        expected = self.target.box.translated(*observation.camera_shift)
        tracked = sorted(candidates, key=lambda item: math.dist(item.box.center, expected.center))
        match = tracked[0] if tracked else None
        distance = math.dist(match.box.center, expected.center) if match else math.inf
        if len(tracked) > 1:
            second = math.dist(tracked[1].box.center, expected.center)
            if abs(second - distance) < 8:
                return self.stop("Ambiguous target association; stopped")
        if match is None or distance > 80:
            if self.state == State.VERIFY:
                self.missing_frames += 1
                if now < self.verify_until or self.missing_frames < 3:
                    return self._result("Target absent; awaiting further visual evidence")
                self.state, self.target = State.SEARCH, None
                return self._result("Target absent for 3 frames after attack; kill unconfirmed")
            return self.stop("Target missing or below confidence; stopped")
        self.target, self.missing_frames = match, 0
        dx = match.box.center[0] - player.box.center[0]
        direction = "right" if dx >= 0 else "left"
        if self.state == State.VERIFY:
            if now < self.verify_until:
                return self._result("Observing target after attack; no outcome assumed")
            if self.attempts >= self.config.max_attack_attempts:
                return self.stop("Attack limit reached without confirmed target disappearance")
            self.state = State.APPROACH
            return self._result("Target remains visible; reacquire range")
        if abs(dx) > self.config.attack_range:
            if self.last_distance is not None and self.last_distance - abs(dx) < 1.5:
                self.stalled_steps += 1
            else:
                self.stalled_steps = 0
            if self.stalled_steps >= 5:
                return self.stop(
                    "No observed approach progress for 5 steps; check controls or terrain"
                )
            self.last_distance = abs(dx)
            self.state, self.facing = State.APPROACH, direction
            return self._result(
                "Short approach step, then observe again",
                Action(direction, self.config.movement_seconds),
            )
        if self.state == State.APPROACH:
            self.last_distance, self.stalled_steps = None, 0
            self.state = State.ATTACK
            # Always face target once at close range, even if previous movement was opposite.
            self.facing = direction
            return self._result(
                "In range; face target before attack",
                Action(direction, min(0.035, self.config.movement_seconds)),
            )
        self.state = State.VERIFY
        self.attempts += 1
        self.verify_until = now + self.config.attack_seconds + self.config.verify_seconds
        return self._result(
            "Attack requested; inspect subsequent screenshots",
            Action("attack", self.config.attack_seconds),
        )
