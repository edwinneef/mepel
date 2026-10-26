"""Atomic teaching checkpoints, separate from the map used for navigation."""

import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path

from .profiles import AreaStore

_LOCK = threading.RLock()


def basis(profile: dict) -> str:
    value = {key: profile.get(key) for key in
             ("revision", "views", "minimap_calibration", "platforms", "ropes", "links")}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class TeachingDrafts:
    def __init__(self, directory: Path, area_id: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", area_id):
            raise ValueError("Invalid draft area ID")
        self.path = directory / "drafts" / f"{area_id}.json"
        self.area_id = area_id

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        if self.path.stat().st_size > 16_000_000:
            raise ValueError("Teaching draft is too large; original file preserved")
        value = json.loads(self.path.read_text("utf-8"))
        if (not isinstance(value, dict) or value.get("version") != 1
                or value.get("area_id") != self.area_id
                or type(value.get("revision")) is not int or value["revision"] < 1
                or value.get("phase") not in {"calibrating", "recording", "review",
                                             "discarded", "used"}):
            raise ValueError("Invalid teaching draft; original file preserved")
        return value

    def save(self, value: dict, expected: int) -> dict:
        with _LOCK:
            current = self.load()
            if (current["revision"] if current else 0) != expected:
                raise ValueError("Teaching draft changed elsewhere; reconnect before saving")
            saved = {**value, "version": 1, "area_id": self.area_id,
                     "revision": expected + 1, "saved_at": time.time()}
            body = (json.dumps(saved, allow_nan=False) + "\n").encode()
            if len(body) > 16_000_000:
                raise ValueError("Teaching draft is too large; previous checkpoint preserved")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            AreaStore._atomic(self.path, body)
            return saved

    def retire(self, phase: str, expected: int) -> dict:
        with _LOCK:
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix(f".{time.time_ns()}.bak"))
            try:
                self.load()
            except (ValueError, KeyError, TypeError):
                if phase != "discarded":
                    raise
                # Explicit Discard can retire a corrupt file; its exact bytes remain above.
                saved = {"version": 1, "area_id": self.area_id, "phase": phase,
                         "revision": expected + 1, "saved_at": time.time()}
                AreaStore._atomic(self.path, (json.dumps(saved) + "\n").encode())
                return saved
            return self.save({"phase": phase}, expected)
