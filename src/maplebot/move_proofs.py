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

    @staticmethod
    def _shape(entry) -> dict | None:
        shape = entry.get("geometry") if isinstance(entry, dict) else None
        if (isinstance(shape, dict) and isinstance(shape.get("from"), str)
                and isinstance(shape.get("to"), str)
                and shape.get("kind") in {"walk", "climb", "drop", "jump"}
                and isinstance(shape.get("trace"), list) and len(shape["trace"]) >= 2
                and all(isinstance(point, list) and len(point) == 2
                        and all(type(v) in (int, float) for v in point)
                        for point in shape["trace"])):
            return shape
        return None

    def failures(self, area_id: str, fingerprint: str) -> dict[str, dict]:
        """Moves a learn_moves batch tried and missed, with the geometry that missed."""
        value = self._read(area_id)
        failed = value.get("failed")
        if value.get("map_hash") != fingerprint or not isinstance(failed, dict):
            return {}
        return {key: shape for key, entry in failed.items()
                if (shape := self._shape(entry)) is not None}

    def record_failure(self, area_id: str, fingerprint: str, move_id: str,
                       geometry: dict) -> None:
        self._write(area_id, fingerprint, move_id, geometry, failed=True)

    def geometry(self, area_id: str, fingerprint: str) -> dict[str, dict]:
        """The from/to/kind/trace each proven move had when it succeeded.

        A move generator change must not carry a proof over to new, untried geometry;
        entries without a valid recorded geometry are left out.
        """
        value = self._read(area_id)
        moves = value.get("moves")
        if value.get("map_hash") != fingerprint or not isinstance(moves, dict):
            return {}
        return {key: shape for key, entry in moves.items()
                if (shape := self._shape(entry)) is not None}

    def record(self, area_id: str, fingerprint: str, move_id: str,
               geometry: dict | None = None) -> None:
        self._write(area_id, fingerprint, move_id, geometry, failed=False)

    def _write(self, area_id: str, fingerprint: str, move_id: str, geometry: dict | None,
               *, failed: bool) -> None:
        with _LOCK:
            value = self._read(area_id)
            same = value.get("map_hash") == fingerprint
            moves, misses = ((value.get(key) if same else None) for key in ("moves", "failed"))
            moves = dict(moves) if isinstance(moves, dict) else {}
            misses = dict(misses) if isinstance(misses, dict) else {}
            # A success clears an earlier miss of the move; a miss never revokes a proof.
            entry = {"failed_at" if failed else "proved_at": time.time()}
            if geometry is not None:
                entry["geometry"] = geometry
            (misses if failed else moves)[move_id] = entry
            if not failed:
                misses.pop(move_id, None)
            body = {"area_id": area_id, "map_hash": fingerprint, "moves": moves}
            if misses:
                body["failed"] = misses
            self.directory.mkdir(parents=True, exist_ok=True)
            AreaStore._atomic(self._path(area_id),
                              (json.dumps(body, indent=2, allow_nan=False) + "\n").encode())
