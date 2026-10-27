"""Deterministic decisions, with no capture or keyboard dependencies."""

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .config import AgentConfig
from .geometry import Rect
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


@dataclass(frozen=True)
class PolicyInput:
    """Everything the pure policy may use for one captured frame."""

    observation: Observation
    now: float
    last_outcome: dict[str, Any]
    mp_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PolicyInput":
        try:
            raw_observation = value["observation"]
            raw_player = raw_observation["player"]
            player = Detection(
                raw_player["kind"],
                Rect(**raw_player["box"]),
                raw_player["confidence"],
                raw_player.get("template", ""),
                raw_player.get("tracked", False),
            ) if raw_player else None
            monsters = [
                Detection(
                    item["kind"],
                    Rect(**item["box"]),
                    item["confidence"],
                    item.get("template", ""),
                    item.get("tracked", False),
                )
                for item in raw_observation["monsters"]
            ]
            now = float(value["now"])
            if not math.isfinite(now):
                raise ValueError("PolicyInput.now must be finite")
            return cls(
                Observation(
                    player,
                    monsters,
                    list(raw_observation.get("failures", [])),
                    tuple(raw_observation.get("camera_shift", (0, 0))),
                    float(raw_observation.get("camera_confidence", 0.0)),
                ),
                now,
                dict(value["last_outcome"]),
                value.get("mp_percent"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid PolicyInput: {error}") from error


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
        self.skill_ready = False

    def stop(self, reason: str) -> Decision:
        self.state, self.target, self.facing = State.IDLE, None, None
        self.attempts, self.missing_frames = 0, 0
        self.last_distance, self.stalled_steps = None, 0
        self.skill_ready = False
        return Decision(self.state, Action(), reason)

    def start(self) -> None:
        self.stop("Starting")
        self.state = State.SEARCH

    def _search(self, reason: str) -> Decision:
        self.stop(reason)
        self.state = State.SEARCH
        return self._result(reason)

    def _result(self, reason: str, action: Action | None = None) -> Decision:
        return Decision(self.state, action or Action(), reason, self.target)

    def step(self, observation: Observation, now: float) -> Decision:
        return self.step_input(PolicyInput(observation, now, {"status": "not_sent"}))

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": 1,
            "state": str(self.state),
            "target": asdict(self.target) if self.target else None,
            "facing": self.facing,
            "verify_until": self.verify_until,
            "attempts": self.attempts,
            "acquisitions": self.acquisitions,
            "missing_frames": self.missing_frames,
            "last_distance": self.last_distance,
            "stalled_steps": self.stalled_steps,
            "skill_ready": self.skill_ready,
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("version") != 1:
            raise ValueError("Unsupported policy snapshot version")
        try:
            target = snapshot["target"]
            self.state = State(snapshot["state"])
            self.target = (
                Detection(
                    target["kind"],
                    Rect(**target["box"]),
                    target["confidence"],
                    target.get("template", ""),
                    target.get("tracked", False),
                )
                if target
                else None
            )
            self.facing = snapshot["facing"]
            self.verify_until = float(snapshot["verify_until"])
            self.attempts = int(snapshot["attempts"])
            self.acquisitions = int(snapshot["acquisitions"])
            self.missing_frames = int(snapshot["missing_frames"])
            self.last_distance = snapshot["last_distance"]
            self.stalled_steps = int(snapshot["stalled_steps"])
            self.skill_ready = bool(snapshot.get("skill_ready", False))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid policy snapshot: {error}") from error

    def step_input(self, policy_input: PolicyInput) -> Decision:
        observation, now = policy_input.observation, policy_input.now
        if self.state == State.IDLE:
            return self._result("Stopped; start dry run or arm combat")
        player = observation.player
        if player is None or (player.confidence < self.confidence and not player.tracked):
            return self.stop("Uncertain player; stop and recalibrate templates")
        candidates = [
            monster
            for monster in observation.monsters
            if monster.confidence >= self.confidence
            and not monster.tracked
            and abs(monster.box.feet - player.box.feet) <= self.config.platform_tolerance
        ]
        if self.state == State.SEARCH:
            if not candidates:
                return self._result(
                    "Waiting for a fresh confident same-platform target; no movement"
                )
            self.target = min(
                candidates, key=lambda item: abs(item.box.center[0] - player.box.center[0])
            )
            self.state, self.attempts, self.missing_frames = State.APPROACH, 0, 0
            self.acquisitions += 1
            self.last_distance, self.stalled_steps = None, 0
            return self._result("Acquired nearest same-platform target")

        if self.target is None:
            return self._search("Target tracking lost; waiting for a fresh target")
        expected = self.target.box.translated(*observation.camera_shift)
        tracked = sorted(candidates, key=lambda item: math.dist(item.box.center, expected.center))
        match = tracked[0] if tracked else None
        distance = math.dist(match.box.center, expected.center) if match else math.inf
        if len(tracked) > 1:
            second = math.dist(tracked[1].box.center, expected.center)
            if abs(second - distance) < 8:
                return self._search("Ambiguous target association; waiting for a fresh target")
        if match is None or distance > 80:
            if self.state == State.VERIFY:
                self.missing_frames += 1
                if now < self.verify_until or self.missing_frames < 3:
                    return self._result("Target absent; awaiting further visual evidence")
                return self._search("Target absent for 3 frames after attack; kill unconfirmed")
            return self._search("Target missing or below confidence; waiting for a fresh target")
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
        if abs(dx) < self.config.attack_min_range:
            return self.stop("Target inside minimum attack range; reposition manually")
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
        if self.state == State.APPROACH or self.facing != direction:
            self.last_distance, self.stalled_steps = None, 0
            self.state = State.ATTACK
            # Face again if the target crosses sides before the attack is dispatched.
            self.facing = direction
            return self._result(
                "In range; face target before attack",
                Action(direction, min(0.035, self.config.movement_seconds)),
            )
        self.state = State.VERIFY
        self.attempts += 1
        self.verify_until = now + self.config.attack_seconds + self.config.verify_seconds
        kind = self._attack_kind(policy_input.mp_percent)
        return self._result(
            f"{kind.capitalize()} attack requested; inspect subsequent screenshots",
            Action(kind, self.config.attack_seconds),
        )

    def _attack_kind(self, mp: float | None) -> str:
        """Skill above the high MP mark, basic below the low mark; unreadable MP is basic."""
        if mp is None:
            self.skill_ready = False
        elif mp < self.config.skill_low_mp:
            self.skill_ready = False
        elif mp >= self.config.skill_high_mp:
            self.skill_ready = True
        return "skill" if self.skill_ready else "attack"
