"""Bounded, read-only evidence of a demo; never grants input or infers hits."""

import copy
import threading
import time
from collections import deque


class CombatEvidence:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.lock = threading.RLock()
        self.run = 0
        self.activity = ""
        self.started_at = 0.0
        self.started_clock = 0.0
        self.stop_reason: str | None = None
        self.events: deque[dict] = deque(maxlen=64)
        self.context: dict = {}

    def start(self, activity: str) -> None:
        with self.lock:
            self.run += 1
            self.activity = activity
            self.started_at = time.time()
            self.started_clock = time.perf_counter()
            self.stop_reason = None
            self.events.clear()
            self.context = {}
            self.record("start", activity)

    def observe(self, context: dict) -> None:
        with self.lock:
            self.context = copy.deepcopy(context)

    def record(self, kind: str, detail: str, **data: object) -> None:
        with self.lock:
            if (kind == "input_outcome"
                    and data.get("submitted_at", self.started_clock) < self.started_clock):
                return  # A canceled key from the previous run is not this run's evidence.
            if self.run:
                self.events.append({"time": time.time(), "kind": kind, "detail": detail,
                                    "observation": copy.deepcopy(self.context), **data})

    def stop(self, reason: str) -> None:
        with self.lock:
            if self.run and self.stop_reason is None:
                self.stop_reason = reason
                self.record("stop", reason)

    def snapshot(self) -> dict | None:
        with self.lock:
            if not self.run:
                return None
            return {"session_id": self.session_id, "run": self.run,
                    "activity": self.activity, "started_at": self.started_at,
                    "stop_reason": self.stop_reason, "hit_confirmed": None,
                    "events": copy.deepcopy(list(self.events))}
