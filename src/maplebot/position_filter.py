"""Temporal position evidence. Held estimates are never fresh measurements."""

import math


class PositionFilter:
    def __init__(self, *, frames: int = 3, threshold: float = .90,
                 alpha: float = .5, max_gap: float = .5, hold_seconds: float = 1.) -> None:
        if (isinstance(frames, bool) or not isinstance(frames, int) or frames < 1
                or not all(math.isfinite(v) for v in (threshold, alpha, max_gap, hold_seconds))
                or not 0 < threshold <= 1 or not 0 < alpha <= 1
                or max_gap <= 0 or hold_seconds <= 0):
            raise ValueError("Invalid temporal position settings")
        self.frames, self.threshold, self.alpha = frames, threshold, alpha
        self.max_gap, self.hold_seconds = max_gap, hold_seconds
        self.reset()

    def reset(self) -> None:
        self.context = self.identity = None
        self.last_clock = self.previous = None
        self.count = 0
        self.average = self.confirmed = None

    def update(self, point, identity: str | None, confidence: float, now: float,
               context, *, fresh: bool) -> dict:
        if not math.isfinite(now):
            self.reset()
            return self._result(0.)
        if (context != self.context or (self.last_clock is not None and now < self.last_clock)
                or (identity and self.identity and identity != self.identity)):
            self.reset()
        self.context = context
        valid = (fresh and bool(identity) and math.isfinite(confidence)
                 and confidence >= self.threshold and point is not None
                 and len(point) == 2 and all(math.isfinite(v) for v in point)
                 and (self.last_clock is None or now > self.last_clock))
        self.last_clock = now
        if not valid:
            self.count, self.previous, self.average = 0, None, None
            return self._result(now)
        self.identity = identity
        if self.previous is None or now - self.previous > self.max_gap:
            self.count, self.average = 0, None
        self.previous = now
        self.count += 1
        self.average = (tuple(point) if self.average is None else tuple(
            self.alpha * value + (1 - self.alpha) * old
            for value, old in zip(point, self.average, strict=True)))
        if self.count >= self.frames:
            self.confirmed = (self.average, confidence, now)
            return self._result(now, fresh=True)
        return self._result(now)

    def _result(self, now: float, *, fresh: bool = False) -> dict:
        held = self.confirmed
        age = max(0., now - held[2]) if held else None
        available = held is not None and age < self.hold_seconds
        return {
            "feet": list(held[0]) if available else None,
            "confidence": (held[1] * max(0., 1 - age / self.hold_seconds)
                           if available else 0.),
            "age_seconds": age,
            "observed_clock": held[2] if held else None,
            "identity": self.identity,
            "consecutive": min(self.count, self.frames),
            "required": self.frames,
            "fresh": fresh,
            "held": available and not fresh,
        }
