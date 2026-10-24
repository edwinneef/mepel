"""Bounded timing variation for permitted software input, independent of its backend."""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from .config import InputConfig, TimingConfig

ACTIONS = ("left", "right", "attack", "jump")


@dataclass(frozen=True)
class KeyHold:
    action: str
    seconds: float
    start_seconds: float = 0


@dataclass(frozen=True)
class KeyEvent:
    action: str
    key: str
    down: bool
    at_seconds: float


@dataclass(frozen=True)
class InputSchedule:
    events: tuple[KeyEvent, ...]
    delay_seconds: float
    rest_seconds: float


class TimingPlanner:
    def __init__(
        self, bindings: InputConfig, config: TimingConfig, rng: random.Random | None = None
    ) -> None:
        self.bindings, self.config = bindings, config
        self.rng = rng if rng is not None else random.Random(config.seed)

    def _conflicts(self, first: KeyHold, second: KeyHold) -> bool:
        return getattr(self.bindings, first.action) == getattr(self.bindings, second.action) or {
            first.action,
            second.action,
        } == {"left", "right"}

    def plan(self, holds: Sequence[KeyHold]) -> InputSchedule:
        limit, profile = self.bindings.max_action_seconds, self.config
        for hold in holds:
            if hold.action not in ACTIONS:
                raise ValueError(f"Unknown input action: {hold.action}")
            if (
                not math.isfinite(hold.seconds)
                or not math.isfinite(hold.start_seconds)
                or hold.seconds <= 0
                or hold.start_seconds < 0
                or hold.start_seconds + hold.seconds > limit
            ):
                raise ValueError(
                    "Input sequence exceeds maximum action duration or has invalid timing"
                )
        ordered = sorted(holds, key=lambda hold: hold.start_seconds)
        for index, first in enumerate(ordered):
            for second in ordered[index + 1 :]:
                if (
                    self._conflicts(first, second)
                    and second.start_seconds < first.start_seconds + first.seconds
                ):
                    raise ValueError(
                        "Overlapping duplicate keys or opposite directions are not allowed"
                    )
        if not ordered:
            return InputSchedule((), 0, 0)
        if not profile.enabled:
            events = [
                KeyEvent(hold.action, getattr(self.bindings, hold.action), down, at)
                for hold in ordered
                for down, at in (
                    (True, hold.start_seconds),
                    (False, hold.start_seconds + hold.seconds),
                )
            ]
            return InputSchedule(
                tuple(sorted(events, key=lambda event: (event.at_seconds, event.down))), 0, 0
            )

        delay = self.rng.uniform(profile.reaction_min_seconds, profile.reaction_max_seconds)
        rest = self.rng.uniform(profile.rest_min_seconds, profile.rest_max_seconds)
        starts: list[float] = []
        for hold in ordered:
            variation = (
                self.rng.uniform(
                    -profile.offset_variation_seconds, profile.offset_variation_seconds
                )
                if hold.start_seconds
                else 0
            )
            start = max(0, hold.start_seconds + variation)
            if starts:
                start = max(
                    start,
                    starts[-1]
                    + profile.key_stagger_seconds
                    + self.rng.uniform(0, profile.offset_variation_seconds),
                )
            starts.append(start)
        events = []
        for index, hold in enumerate(ordered):
            start = starts[index]
            maximum = limit - start
            for other_index in range(index + 1, len(ordered)):
                if self._conflicts(hold, ordered[other_index]):
                    maximum = min(
                        maximum, starts[other_index] - start - profile.key_stagger_seconds
                    )
                    break
            if maximum <= 0:
                raise ValueError(
                    "Staggered input sequence cannot fit within the action duration limit"
                )
            low = min(
                maximum,
                max(
                    min(profile.min_hold_seconds, hold.seconds),
                    hold.seconds * (1 - profile.hold_variation),
                ),
            )
            high = min(maximum, hold.seconds * (1 + profile.hold_variation))
            duration = self.rng.triangular(low, high, min(high, max(low, hold.seconds)))
            key = getattr(self.bindings, hold.action)
            events.extend(
                (
                    KeyEvent(hold.action, key, True, delay + start),
                    KeyEvent(hold.action, key, False, delay + start + duration),
                )
            )
        return InputSchedule(
            tuple(sorted(events, key=lambda event: (event.at_seconds, event.down))), delay, rest
        )
