"""Computed moves that have succeeded once under supervision, per area and map version."""

import json
import re
import threading
import time
from pathlib import Path

from .profiles import AreaStore

_LOCK = threading.Lock()


class MoveProofs:
    def __init__(self, directory: Path) -> None:
        self.directory = directory / "proofs"

    def _path(self, area_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", area_id):
            raise ValueError("Invalid area ID")
        return self.directory / f"{area_id}.json"

    def _read(self, area_id: str) -> dict:
        path = self._path(area_id)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}  # unreadable proofs prove nothing; the next success rewrites them
        return value if isinstance(value, dict) else {}

    def load(self, area_id: str, fingerprint: str) -> set[str]:
        """Proven move IDs, empty when the map changed since they were proven."""
        value = self._read(area_id)
        moves = value.get("moves")
        if value.get("map_hash") != fingerprint or not isinstance(moves, dict):
            return set()
        return {key for key in moves if isinstance(key, str)}

    def record(self, area_id: str, fingerprint: str, move_id: str) -> None:
        with _LOCK:
            value = self._read(area_id)
            moves = value.get("moves") if value.get("map_hash") == fingerprint else None
            moves = dict(moves) if isinstance(moves, dict) else {}
            moves[move_id] = {"proved_at": time.time()}
            body = {"area_id": area_id, "map_hash": fingerprint, "moves": moves}
            self.directory.mkdir(parents=True, exist_ok=True)
            AreaStore._atomic(self._path(area_id),
                              (json.dumps(body, indent=2, allow_nan=False) + "\n").encode())
