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

    def geometry(self, area_id: str, fingerprint: str) -> dict[str, dict]:
        """The from/to/kind/trace each proven move had when it succeeded.

        A move generator change must not carry a proof over to new, untried geometry;
        entries without a valid recorded geometry are left out.
        """
        value = self._read(area_id)
        moves = value.get("moves")
        if value.get("map_hash") != fingerprint or not isinstance(moves, dict):
            return {}
        found = {}
        for key, entry in moves.items():
            shape = entry.get("geometry") if isinstance(entry, dict) else None
            if (isinstance(shape, dict) and isinstance(shape.get("from"), str)
                    and isinstance(shape.get("to"), str)
                    and shape.get("kind") in {"walk", "climb", "drop", "jump"}
                    and isinstance(shape.get("trace"), list) and len(shape["trace"]) >= 2
                    and all(isinstance(point, list) and len(point) == 2
                            and all(type(v) in (int, float) for v in point)
                            for point in shape["trace"])):
                found[key] = shape
        return found

    def record(self, area_id: str, fingerprint: str, move_id: str,
               geometry: dict | None = None) -> None:
        with _LOCK:
            value = self._read(area_id)
            moves = value.get("moves") if value.get("map_hash") == fingerprint else None
            moves = dict(moves) if isinstance(moves, dict) else {}
            moves[move_id] = {"proved_at": time.time()}
            if geometry is not None:
                moves[move_id]["geometry"] = geometry
            body = {"area_id": area_id, "map_hash": fingerprint, "moves": moves}
            self.directory.mkdir(parents=True, exist_ok=True)
            AreaStore._atomic(self._path(area_id),
                              (json.dumps(body, indent=2, allow_nan=False) + "\n").encode())
