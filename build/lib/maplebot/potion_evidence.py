"""Passive, bounded observations of normal potion tickets; never sends input."""

import copy
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass

from .keyboard import ActionOutcome


@dataclass(frozen=True)
class PotionFrame:
    stem: str
    raw: bytes
    status: dict
    clock: float
    source: tuple[int, int]

    def reading(self, resource: str) -> dict | None:
        reading = self.status.get("autopotter", {}).get("readings", {}).get(resource, {})
        if (not self.status.get("potion_evidence_safe") or not self.status.get("focused")
                or reading.get("percent") is None or reading.get("confidence", 0) < .9):
            return None
        return {
            "frame": f"{self.stem}.png", "sequence": self.status["sequence"],
            "captured_at": self.status["captured_at"], "capture_clock": self.clock,
            "percent": reading["percent"], "confidence": reading["confidence"],
        }


class PotionEvidence:
    def __init__(self, session_id: str, save: Callable, *, seconds: float = 2.0,
                 minimum_gain: float = 1.0, enabled: bool = True) -> None:
        self.session_id, self.save = session_id, save
        self.seconds, self.minimum_gain, self.enabled = seconds, minimum_gain, enabled
        self.lock = threading.RLock()
        self.latest: PotionFrame | None = None
        self.pending: dict[int, dict] = {}
        self.records: deque[dict] = deque(maxlen=32)

    def queued(self, ticket: int, resource: str, clock: float,
               source: tuple[int, int]) -> None:
        if not self.enabled:
            return
        with self.lock:
            for old in list(self.pending.values()):
                if old["record"]["resource"] == resource:
                    self._finish(old, "superseded")
            frame = self.latest
            before = (frame.reading(resource) if frame and frame.source == source
                      and 0 <= clock - frame.clock <= .5 else None)
            record = {
                "id": f"{self.session_id}:{ticket}", "session_id": self.session_id,
                "recording": f"session-{time.time_ns()}-potion-{resource}-t{ticket}",
                "ticket": ticket, "resource": resource, "queued_clock": clock,
                "view_generation": source[0], "source_generation": source[1],
                "window_seconds": self.seconds, "minimum_gain_percent": self.minimum_gain,
                "status": "queued", "before": before, "after": None, "outcome": None,
                "baseline_usable": before is not None,
                "note": "Bar gain is an observation, not proof the potion caused recovery.",
            }
            item = {"record": record, "source": source, "after_frame": None}
            self.records.append(record)
            self.pending[ticket] = item
            self.save(copy.deepcopy(record), [frame] if before else [])

    def outcome(self, outcome: ActionOutcome) -> None:
        with self.lock:
            item = self.pending.get(outcome.ticket)
            if item is None:
                return
            record = item["record"]
            if (record["outcome"] is not None
                    or outcome.action != f"{record['resource']}_potion"
                    or outcome.submitted_at < record["queued_clock"]):
                return
            record["outcome"] = asdict(outcome)
            if outcome.result != f"{outcome.action} completed":
                self._finish(item, "input_not_completed")
            else:
                before = record["before"]
                record["baseline_usable"] = bool(
                    before and outcome.started_at is not None
                    and 0 <= outcome.started_at - before["capture_clock"] <= .5
                )
                record["status"] = "awaiting_observation"
                self.save(copy.deepcopy(record), [])

    def observe(self, frame: PotionFrame) -> None:
        with self.lock:
            self.latest = frame
            for item in list(self.pending.values()):
                record = item["record"]
                if frame.source != item["source"]:
                    self._finish(item, "source_changed")
                    continue
                outcome = record["outcome"]
                if outcome is None:
                    if frame.clock - record["queued_clock"] > 5:
                        self._finish(item, "outcome_unavailable")
                    continue
                elapsed = frame.clock - outcome["finished_at"]
                if elapsed <= 0:
                    continue
                if elapsed > self.seconds:
                    status = ("baseline_unavailable" if not record["baseline_usable"] else
                              "no_observed_gain" if record["after"] else
                              "observation_unavailable")
                    self._finish(item, status)
                    continue
                after = frame.reading(record["resource"])
                if after is None:
                    continue
                record["after"], item["after_frame"] = after, frame
                before = record["before"]
                if not record["baseline_usable"]:
                    self._finish(item, "baseline_unavailable")
                elif after["percent"] - before["percent"] >= self.minimum_gain:
                    self._finish(item, "observed_bar_gain")

    def close(self) -> None:
        with self.lock:
            for item in list(self.pending.values()):
                self._finish(item, "capture_ended")
            self.latest = None

    def snapshot(self) -> dict:
        with self.lock:
            return {"enabled": self.enabled, "records": copy.deepcopy(list(self.records))}

    def _finish(self, item: dict, status: str) -> None:
        record = item["record"]
        record["status"] = status
        self.pending.pop(record["ticket"], None)
        frame = item["after_frame"]
        self.save(copy.deepcopy(record), [frame] if frame else [])
