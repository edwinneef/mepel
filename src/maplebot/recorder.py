"""Session recording: decisions always, frames only around incidents.

Frames arrive as PNG bytes the capture loop has already encoded for the debugger,
so recording adds no encoding cost. Disk writes run on a separate thread; when it
falls behind, frames are dropped instead of stalling capture.
Existing recordings are never deleted automatically, regardless of age or size.
"""

import json
import math
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .config import RecordingConfig

WRITER_ERROR_LIMIT = 8
WRITER_ERROR_MESSAGE_LIMIT = 512


class SessionRecorder:
    def __init__(self, root: Path, config: RecordingConfig, fps: float) -> None:
        self.root = root
        self.config = config
        self.buffer: deque[tuple[str, bytes, str]] = deque(
            maxlen=max(1, math.ceil(config.buffer_seconds * fps))
        )
        self.path: Path | None = None
        self.full = False
        self.full_until = math.inf
        self.manual = False
        self.closing = False
        self.post_until = 0.0
        self.last_keyframe = float("-inf")
        self.written: set[str] = set()
        self.events = 0
        self.dropped = 0
        self.pending = 0
        # Lifetime counters must survive session switches while older writes are pending.
        self.writer_pending = dict.fromkeys(("frame", "line", "mkdir", "potion_done"), 0)
        self.writer_errors = dict.fromkeys(("frame", "line", "mkdir"), 0)
        self.writer_recent_errors: deque[dict] = deque(maxlen=WRITER_ERROR_LIMIT)
        self.writer_active: dict | None = None
        self.writer_last_success: dict | None = None
        self.writer_dropped_frames = 0
        self.potion_paths: set[Path] = set()
        self.lock = threading.RLock()
        self.jobs: queue.Queue[tuple[str, Path, Any] | None] = queue.Queue()
        self.writer = threading.Thread(target=self._write, name="recorder", daemon=True)
        self.writer.start()

    @property
    def active(self) -> bool:
        with self.lock:
            return self.path is not None and not self.closing

    def start(self, label: str, *, manual: bool = False) -> Path:
        with self.lock:
            if self.closing:
                self.stop()
            if self.path is None:
                self.path = self.root / f"session-{time.time_ns()}-{label}"
                self.path.mkdir(parents=True)
                self.written.clear()
                self.post_until, self.last_keyframe = 0.0, float("-inf")
                self.events = self.dropped = 0
                self.manual = manual
                path = self.path
                lines = [line for _, _, line in self.buffer]
            else:
                path, lines = self.path, []
        # Pre-roll: buffered frames may be flushed later, so log their decisions too.
        for line in lines:
            self._enqueue("line", path / "decisions.jsonl", line)
        return path

    def stop(self) -> Path | None:
        with self.lock:
            path, self.path, self.full, self.manual = self.path, None, False, False
            self.full_until = math.inf
            self.closing = False
            return path

    def start_full(self, seconds: float | None = None) -> Path:
        """Save every frame; with `seconds`, full recording ends by itself after that long.

        The deadline uses perf_counter, not observe's `now`: frame times are
        session-relative and would never reach a perf_counter deadline.
        """
        with self.lock:
            path = self.start("manual", manual=True)
            self.full_until = math.inf if seconds is None else time.perf_counter() + seconds
            self.full = True
            return path

    def stop_full(self) -> Path | None:
        with self.lock:
            path = self.path
            self.full, self.full_until = False, math.inf
            if self.manual:
                self.stop()
            return path

    def observe(self, stem: str, raw: bytes, status: dict, now: float) -> None:
        line = json.dumps({"frame": f"{stem}.png", **status}) + "\n"
        with self.lock:
            self.buffer.append((stem, raw, line))
            path = self.path
            if path is None:
                return
            if self.full and time.perf_counter() >= self.full_until:
                self.full, self.full_until = False, math.inf
                self.closing = self.closing or self.manual
            keyframe = (
                self.config.keyframe_seconds > 0
                and now - self.last_keyframe >= self.config.keyframe_seconds
            )
            frame = self.full or now < self.post_until or keyframe
            if keyframe:
                self.last_keyframe = now
            closing = self.closing
        self._enqueue("line", path / "decisions.jsonl", line)
        if frame:
            self._frame(path, stem, raw)
        if closing:
            self.stop()

    def trigger(self, reason: str, now: float, *, close: bool = False) -> Path:
        """Flush the buffered frames and log why. Without a session, saves a one-off clip.

        `close` ends the session after the next observed frame, so the decision that
        caused the stop is still logged.
        """
        with self.lock:
            clip = self.path is None or self.closing
            path = self.start("clip") if clip else self.path
            assert path is not None
            frames = list(self.buffer)
            self.events += 1
            self.post_until = now + self.config.post_seconds
            if not clip and close:
                self.closing = True
        for stem, raw, _ in frames:
            self._frame(path, stem, raw)
        event = {"time": round(time.time(), 3), "reason": reason}
        self._enqueue("line", path / "events.jsonl", json.dumps(event) + "\n")
        if clip:
            self.stop()
        return path

    def snapshot(self) -> dict:
        with self.lock:
            pending = sum(self.writer_pending.values())
            incomplete = any(self.writer_errors.values()) or self.writer_dropped_frames > 0
            return {
                "path": str(self.path) if self.path else None,
                "full": self.full,
                "full_remaining": (
                    round(max(0.0, self.full_until - time.perf_counter()), 1)
                    if self.full and self.full_until < math.inf else None
                ),
                "events": self.events,
                "dropped": self.dropped,
                "writer": {
                    "scope": "recorder_lifetime",
                    # Complete means requested jobs drained without known loss, not fsync
                    # durability or coverage of frames the recording policy did not request.
                    "status": (
                        "incomplete" if incomplete else
                        "pending" if pending or self.pending else "complete"
                    ),
                    "pending_jobs": pending,
                    "pending_by_kind": dict(self.writer_pending),
                    "pending_frames": self.pending,
                    "active": dict(self.writer_active) if self.writer_active else None,
                    "errors_by_kind": dict(self.writer_errors),
                    "recent_errors": [dict(error) for error in self.writer_recent_errors],
                    "error_history_limit": WRITER_ERROR_LIMIT,
                    "dropped_frames": self.writer_dropped_frames,
                    "last_success": (
                        dict(self.writer_last_success) if self.writer_last_success else None
                    ),
                    "thread_alive": self.writer.is_alive(),
                },
            }

    def save_potion(self, record: dict, frames: list) -> None:
        """Queue a small ticket-specific record and matched PNGs, even after combat stops."""
        path = self.root / record["recording"]
        if record["status"] == "queued":
            with self.lock:
                self.potion_paths.add(path)
            self._enqueue("mkdir", path, None)
        for frame in frames:
            self._frame(path, frame.stem, frame.raw, deduplicate=False)
            line = json.dumps({"frame": f"{frame.stem}.png", **frame.status}) + "\n"
            self._enqueue("line", path / "decisions.jsonl", line)
        self._enqueue("line", path / "potion-evidence.jsonl", json.dumps(record) + "\n")
        if record["status"] not in {"queued", "awaiting_observation"}:
            self._enqueue("potion_done", path, None)

    def close(self) -> None:
        self.stop()
        self.jobs.put(None)
        self.writer.join(timeout=5)

    def _frame(self, path: Path, stem: str, raw: bytes, *, deduplicate: bool = True) -> None:
        with self.lock:
            if deduplicate and stem in self.written:
                return
            if self.pending >= self.config.max_queue_frames:
                self.dropped += 1
                self.writer_dropped_frames += 1
                return
            self.pending += 1
            if deduplicate:
                self.written.add(stem)
        self._enqueue("frame", path / f"{stem}.png", raw)

    def _enqueue(self, kind: str, path: Path, data: Any) -> None:
        with self.lock:
            self.writer_pending[kind] += 1
            self.jobs.put((kind, path, data))

    def _write(self) -> None:
        while (job := self.jobs.get()) is not None:
            kind, path, data = job
            with self.lock:
                self.writer_active = {"kind": kind, "path": str(path)}
            try:
                if kind == "frame":
                    path.write_bytes(data)
                elif kind == "mkdir":
                    path.mkdir(parents=True, exist_ok=True)
                elif kind == "potion_done":
                    with self.lock:
                        self.potion_paths.discard(path)
                elif kind == "line":
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(data)
            except OSError as error:
                with self.lock:
                    self.writer_errors[kind] += 1
                    self.writer_recent_errors.append({
                        "kind": kind, "path": str(path), "errno": error.errno,
                        "message": str(error)[:WRITER_ERROR_MESSAGE_LIMIT],
                    })
                    if kind == "frame":
                        self.dropped += 1
                        self.writer_dropped_frames += 1
            else:
                with self.lock:
                    self.writer_last_success = {"kind": kind, "path": str(path)}
            finally:
                with self.lock:
                    self.writer_active = None
                    self.writer_pending[kind] -= 1
                    if kind == "frame":
                        self.pending -= 1
