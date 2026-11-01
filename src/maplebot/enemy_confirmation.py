"""Offline candidate evidence only; this module never admits gameplay targets."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SnailEvidence:
    frame_id: str
    captured_at: float
    track_id: str
    species: str
    floor: str
    x: float
    y: float
    raw_score: float
    observed: bool = True
    ambiguous: bool = False
    live_sprite: bool = True


@dataclass(frozen=True)
class Confirmation:
    raw_score: float
    confirmed: bool
    observations: int
    reason: str
    provenance: str = "offline-temporal-snail-candidate"


class SnailConfirmation:
    """Caller supplies independently verified species/floor/sprite labels.

    Positions must already compensate camera motion. Unknown/discontinuous camera
    motion invalidates history. Results are diagnostics, not confidence overrides.
    """

    def __init__(self, snail_species: frozenset[str]):
        self.snail_species = snail_species
        self.history: dict[str, list[SnailEvidence]] = {}
        self.context = None
        self.at: float | None = None
        self.frames: set[str] = set()

    def observe(self, evidence: list[SnailEvidence], *, now: float,
                context: object, frame_id: str, camera_continuous: bool = True
                ) -> dict[str, Confirmation]:
        if (context != self.context or not camera_continuous or not math.isfinite(now)
                or self.at is not None and now <= self.at):
            self.history.clear()
            self.frames.clear()
        self.context = context
        if not math.isfinite(now):
            return {}
        self.at = now
        if not camera_continuous or not frame_id or frame_id in self.frames:
            self.history.clear()
            return {}
        self.frames.add(frame_id)
        # A missing detection ends its evidence chain; retained predictions cannot count.
        present = {item.track_id for item in evidence}
        self.history = {key: value for key, value in self.history.items() if key in present}
        result = {}
        for item in evidence:
            invalid = (sum(other.track_id == item.track_id for other in evidence) != 1
                       or not item.track_id or item.frame_id != frame_id
                       or not all(math.isfinite(v) for v in
                                  (item.captured_at, item.x, item.y, item.raw_score))
                       or not 0 <= now - item.captured_at <= .5
                       or not .80 <= item.raw_score < .85
                       or item.species not in self.snail_species or not item.floor
                       or not item.observed or item.ambiguous or not item.live_sprite)
            chain = self.history.get(item.track_id, [])
            if chain:
                previous = chain[-1]
                dt = item.captured_at - previous.captured_at
                invalid |= (item.species != previous.species or item.floor != previous.floor
                            or dt <= 0 or abs(item.y - previous.y) > 6
                            or abs(item.x - previous.x) > 120 * max(0, dt) + 4)
                if len(chain) >= 2:
                    before = previous.x - chain[-2].x
                    after = item.x - previous.x
                    invalid |= abs(before) > 4 and abs(after) > 4 and before * after < 0
            if invalid:
                self.history.pop(item.track_id, None)
                result[item.track_id] = Confirmation(item.raw_score, False, 0, "rejected")
                continue
            chain = [old for old in chain if item.captured_at - old.captured_at <= 1]
            chain.append(item)
            self.history[item.track_id] = chain
            confirmed = len(chain) >= 3 and item.captured_at - chain[0].captured_at >= .3
            result[item.track_id] = Confirmation(
                item.raw_score, confirmed, len(chain), "confirmed" if confirmed else "collecting")
        return result
