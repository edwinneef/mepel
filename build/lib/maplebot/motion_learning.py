"""Bounded passive motion evidence. No commands, control tuning or route authority."""

import hashlib
import json
import math
import statistics
import time
from collections import deque
from pathlib import Path

from .profiles import AreaStore


class PassiveMovement:
    def __init__(self, cache: Path | None = None):
        self.cache = cache
        self.context = None
        self.previous = None
        self.speeds = deque(maxlen=64)
        self.held = set()
        self.sequence = 0

    def reset(self, context=None):
        self.context, self.previous = context, None
        self.speeds.clear()
        self.held.clear()
        self.sequence = 0

    def observe(self, *, context, clock, feet, surface, valid, timing, left="left", right="right"):
        # A controller lifetime is essential: identical sequence numbers across restarts
        # do not identify the same dispatched keys. No keyboard hooks or inferred inputs.
        basis = (context, timing.get("history_id"), left, right)
        if basis != self.context:
            self.reset(basis)
        history = timing.get("history", [])
        last = timing.get("history_last_sequence", 0)
        if (not timing.get("history_id") or not isinstance(history, list)
                or len(history) > 1024 or not all(isinstance(e, dict) for e in history)
                or type(last) is not int or not self.sequence <= last <= self.sequence + 1024):
            self.reset()
            return self.snapshot()
        events = [e for e in history if e.get("sequence", 0) > self.sequence]
        if [e.get("sequence") for e in events] != list(range(self.sequence + 1, last + 1)):
            self.reset()
            return self.snapshot()
        changed = bool(events)
        for event in events:
            start, end = event.get("clock"), event.get("finished_clock")
            if (type(event.get("down")) is not bool or not isinstance(event.get("key"), str)
                    or not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end))
                    or not 0 <= start <= end <= clock or event.get("history_id") != basis[1]):
                self.reset()
                return self.snapshot()
            if event["down"]:
                self.held.add(event["key"])
            else:
                self.held.discard(event["key"])
        self.sequence = last
        good = (valid and feet is not None and surface is not None
                and all(math.isfinite(v) for v in (*feet, clock)))
        # A measured position alone cannot identify braking or jump physics. Even
        # horizontal response requires an uninterrupted, single known held direction.
        direction = 1 if self.held == {right} else -1 if self.held == {left} else 0
        if good and self.previous is not None and not changed and direction:
            at, prior, prior_surface = self.previous
            dt = clock - at
            if .1 <= dt <= .5 and prior_surface == surface and abs(feet[1] - prior[1]) <= 2:
                speed = direction * (feet[0] - prior[0]) / dt
                if 20 <= speed <= 500:
                    self.speeds.append(speed)
        self.previous = (clock, feet, surface) if good and direction else None
        return self.snapshot()

    def snapshot(self):
        median = statistics.median(self.speeds) if self.speeds else None
        stable = (len(self.speeds) >= 8 and median is not None
                  and max(abs(v - median) for v in self.speeds) <= median * .15)
        return {"state": "observing", "samples": len(self.speeds),
                "observed_speed_px_s": median if stable else None,
                "parameters": {}, "unidentified": ["speed", "braking", "jump", "climb"],
                "reason": "Observed speed is not an identified input-response model",
                "input_sent": False}

    def save(self):
        # This cache is diagnostic evidence only. A later lifetime cannot promote it
        # into a control model: normal observation must establish its own context.
        if self.cache is None or not self.speeds:
            return
        body = {"version": 1, "context_hash": hashlib.sha256(
            repr(self.context).encode()).hexdigest(), "saved_at": time.time(),
            **self.snapshot()}
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        AreaStore._atomic(self.cache, (json.dumps(body, allow_nan=False) + "\n").encode())
