"""Deterministic decisions, with no capture or keyboard dependencies."""

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .config import AgentConfig
from .enemy_tracking import EnemyTrack
from .geometry import Rect
from .perception import Detection, Observation

# A target hidden under the player, another player or an effect may still be attacked in
# place, from its tracker position, for this long after the policy last matched it.
OCCLUDED_ATTACK_SECONDS = 1.0


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
                raw_player.get("identity"),
            ) if raw_player else None
            tracks = [
                EnemyTrack(
                    item["track_id"], item["enemy_type"], item["state"],
                    tuple(item["predicted_position"]), tuple(item["ground_position"]),
                    Rect(**item["visible_bounds"]) if item.get("visible_bounds") else None,
                    item["confidence"], tuple(item["uncertainty"]), item["last_seen"],
                    item["observed"],
                )
                for item in raw_observation.get("enemy_tracks", [])
            ]
            monsters = [
                Detection(
                    item["kind"],
                    Rect(**item["box"]),
                    item["confidence"],
                    item.get("template", ""),
                    item.get("tracked", False),
                    item.get("identity"),
                    item.get("track_id"),
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
                    tracks,
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
        self.target_seen_at: float | None = None

    def stop(self, reason: str) -> Decision:
        self.state, self.target, self.facing = State.IDLE, None, None
        self.attempts, self.missing_frames = 0, 0
        self.last_distance, self.stalled_steps = None, 0
        self.skill_ready, self.target_seen_at = False, None
        return Decision(self.state, Action(), reason)

    def start(self) -> None:
        self.stop("Starting")
        self.state = State.SEARCH

    def _search(self, reason: str) -> Decision:
        self.stop(reason)
        self.state = State.SEARCH
        return self._result(reason)

    def defer_action(self, before: dict[str, Any]) -> None:
        """Undo action-dependent progress, retaining this frame's target observation."""
        self.state = State(before["state"])
        for name in ("facing", "verify_until", "attempts", "last_distance", "stalled_steps",
                     "skill_ready"):
            setattr(self, name, before[name])

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
            "target_seen_at": self.target_seen_at,
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
                    target.get("identity"),
                    target.get("track_id"),
                )
                if target
                else None
            )
            self.target_seen_at = snapshot.get("target_seen_at")
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
            self.target_seen_at = now
            self.acquisitions += 1
            self.last_distance, self.stalled_steps = None, 0
            return self._result("Acquired nearest same-platform target")

        if self.target is None:
            return self._search("Target tracking lost; waiting for a fresh target")
        expected = self.target.box.translated(*observation.camera_shift)
        # Catalog animation frames share a species; proximity alone must not swap enemies.
        def identity(item: Detection) -> str:
            if item.template.startswith("catalog:"):
                return item.template.rsplit(":", 1)[0]
            return item.template

        tracked = sorted(
            (item for item in candidates if identity(item) == identity(self.target)),
            key=lambda item: math.dist(item.box.center, expected.center),
        )
        match = tracked[0] if tracked else None
        distance = math.dist(match.box.center, expected.center) if match else math.inf
        if len(tracked) > 1:
            second = math.dist(tracked[1].box.center, expected.center)
            if abs(second - distance) < 8:
                return self._search("Ambiguous target association; waiting for a fresh target")
        if match is None or distance > 80:
            hidden = self._hidden_target(observation, player, now)
            if hidden is not None and not (self.state == State.VERIFY and now < self.verify_until):
                return self._attack_hidden(hidden, policy_input)
            if self.state == State.VERIFY:
                self.missing_frames += 1
                if now < self.verify_until or self.missing_frames < 3:
                    return self._result("Target absent; awaiting further visual evidence")
                return self._search("Target absent for 3 frames after attack; kill unconfirmed")
            return self._search("Target missing or below confidence; waiting for a fresh target")
        self.target, self.missing_frames, self.target_seen_at = match, 0, now
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
                    "No observed approach progress: target gap failed to shrink for 5 observations"
                )
            self.last_distance = abs(dx)
            self.state, self.facing = State.APPROACH, direction
            return self._result(
                "Short approach step, then observe again",
                Action(direction, self.config.movement_seconds),
            )
        outcome = policy_input.last_outcome
        approached_facing_target = (
            self.facing == direction
            and outcome.get("status") in {"completed", "held"}
            and outcome.get("action") == direction
            and outcome.get("result") == f"{direction} {outcome.get('status')}"
        )
        if (self.state == State.APPROACH and not approached_facing_target
                or self.facing != direction):
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

    def _hidden_target(self, observation: Observation, player: Detection,
                       now: float) -> float | None:
        """Horizontal offset of the current target's hidden tracker position within reach."""
        if (self.target is None or self.target.track_id is None or self.target_seen_at is None
                or not 0 <= now - self.target_seen_at <= OCCLUDED_ATTACK_SECONDS):
            return None
        track = next((t for t in observation.enemy_tracks
                      if t.track_id == self.target.track_id and not t.observed), None)
        if track is None:
            return None
        x, feet = track.ground_position
        dx = x - player.box.center[0]
        if (abs(feet - player.box.feet) > self.config.platform_tolerance
                or not self.config.attack_min_range <= abs(dx) <= self.config.attack_range):
            return None
        return dx

    def _attack_hidden(self, dx: float, policy_input: PolicyInput) -> Decision:
        """Face and attack a briefly hidden target in place; never step toward it."""
        direction = "right" if dx >= 0 else "left"
        if self.facing != direction:
            self.state, self.facing = State.ATTACK, direction
            return self._result(
                "Hidden target in reach; face before attack",
                Action(direction, min(0.035, self.config.movement_seconds)),
            )
        if self.attempts >= self.config.max_attack_attempts:
            return self._search("Hidden target attack limit reached; waiting for a fresh target")
        self.state = State.VERIFY
        self.attempts += 1
        self.verify_until = (policy_input.now + self.config.attack_seconds
                             + self.config.verify_seconds)
        kind = self._attack_kind(policy_input.mp_percent)
        return self._result(
            f"{kind.capitalize()} attack on hidden target track; no outcome assumed",
            Action(kind, self.config.attack_seconds),
        )

    def _attack_kind(self, mp: float | None) -> str:
        """Skill above the high MP mark, basic below the low mark; unreadable MP is basic."""
        if not self.config.use_skill or mp is None:
            self.skill_ready = False
        elif mp < self.config.skill_low_mp:
            self.skill_ready = False
        elif mp >= self.config.skill_high_mp:
            self.skill_ready = True
        return "skill" if self.skill_ready else "attack"
