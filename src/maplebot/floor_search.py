"""Offline floor-search budget. Proposals confer no keyboard authority."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchEvidence:
    frame: int
    now: float
    age: float
    wide_empty: bool
    target: bool
    safe: bool
    input_idle: bool
    released: bool
    direction: str
    corridor_proven: bool
    clearance: float
    stopping_margin: float
    uncertainty: float
    speed_bound: float


class FloorSearch:
    """One empty episode, explicitly discarded on target or safety failure.

    The caller must supply independently calibrated bounds and a proven continuous
    corridor without portals or edges. No inferred/default calibration is accepted.
    This module is not wired to the live controller pending that evidence.
    """

    def __init__(self, deadline: float):
        if not math.isfinite(deadline):
            raise ValueError("Search needs the existing combat deadline")
        self.deadline = deadline
        self.last_frame = -1
        self.last_time = -math.inf
        self.empty_scans = 0
        self.pulses = 0
        self.seconds = 0.0
        self.closed = False
        self.reason = "Waiting for two fresh empty wide scans"

    def propose(self, evidence: SearchEvidence) -> float:
        """Reserve at most one .24-second pulse; caller releases then reobserves."""
        e = evidence
        if self.closed:
            return 0.0
        numbers = (e.now, e.age, e.clearance, e.stopping_margin,
                   e.uncertainty, e.speed_bound)
        if (not all(math.isfinite(v) for v in numbers) or not e.safe
                or not 0 <= e.age <= .5 or e.now >= self.deadline or e.target):
            self.closed = True
            self.reason = "Target, deadline or unsafe observation; release"
            return 0.0
        if e.frame <= self.last_frame or e.now <= self.last_time:
            self.reason = "Fresh observation required"
            return 0.0
        self.last_frame, self.last_time = e.frame, e.now
        if not e.input_idle or not e.released:
            self.reason = "Release and finish pending input before reobserving"
            return 0.0
        if e.wide_empty:
            self.empty_scans += 1
        if self.empty_scans < 2:
            return 0.0
        if self.pulses >= 4 or self.seconds + .24 > 2:
            self.closed = True
            self.reason = "Empty-episode search budget exhausted"
            return 0.0
        if (not e.corridor_proven or e.direction not in {"left", "right"}
                or e.stopping_margin <= 0 or e.uncertainty < 0 or e.speed_bound <= 0
                or e.clearance <= e.stopping_margin + e.uncertainty + e.speed_bound * .24):
            self.reason = "Proven corridor and calibrated stopping clearance required"
            return 0.0
        if e.now + .24 >= self.deadline:
            self.closed = True
            self.reason = "Pulse would cross the existing combat deadline"
            return 0.0
        self.pulses += 1
        self.seconds += .24
        self.reason = "Bounded pulse reserved; release and reobserve"
        return .24
