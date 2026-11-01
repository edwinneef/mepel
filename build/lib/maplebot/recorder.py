"""Session recording: decisions always, frames only around incidents.

Frames arrive as PNG bytes the capture loop has already encoded for the debugger,
so recording adds no encoding cost. Disk writes run on a separate thread; when it
falls behind, frames are dropped instead of stalling capture.
"""

import json
import math
import queue
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .config import RecordingConfig


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
        self.jobs.put(("prune", path, None))
        # Pre-roll: buffered frames may be flushed later, so log their decisions too.
        for line in lines:
            self.jobs.put(("line", path / "decisions.jsonl", line))
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
        self.jobs.put(("line", path / "decisions.jsonl", line))
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
        self.jobs.put(("line", path / "events.jsonl", json.dumps(event) + "\n"))
        if clip:
            self.stop()
        return path

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "path": str(self.path) if self.path else None,
                "full": self.full,
                "full_remaining": (
                    round(max(0.0, self.full_until - time.perf_counter()), 1)
                    if self.full and self.full_until < math.inf else None
                ),
                "events": self.events,
                "dropped": self.dropped,
            }

    def save_potion(self, record: dict, frames: list) -> None:
        """Queue a small ticket-specific record and matched PNGs, even after combat stops."""
        path = self.root / record["recording"]
        if record["status"] == "queued":
            with self.lock:
                self.potion_paths.add(path)
                protected = self.potion_paths | {self.path}
            self.jobs.put(("mkdir", path, None))
            self.jobs.put(("prune", path, protected))
        for frame in frames:
            self._frame(path, frame.stem, frame.raw, deduplicate=False)
            line = json.dumps({"frame": f"{frame.stem}.png", **frame.status}) + "\n"
            self.jobs.put(("line", path / "decisions.jsonl", line))
        self.jobs.put(("line", path / "potion-evidence.jsonl", json.dumps(record) + "\n"))
        if record["status"] not in {"queued", "awaiting_observation"}:
            self.jobs.put(("potion_done", path, None))

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
                return
            self.pending += 1
            if deduplicate:
                self.written.add(stem)
        self.jobs.put(("frame", path / f"{stem}.png", raw))

    def _write(self) -> None:
        while (job := self.jobs.get()) is not None:
            kind, path, data = job
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
                else:
                    self._prune(keep=path, protected=data)
            except OSError:
                if kind == "frame":
                    with self.lock:
                        self.dropped += 1
            finally:
                if kind == "frame":
                    with self.lock:
                        self.pending -= 1

    def _prune(self, keep: Path, protected: set | None = None) -> None:
        with self.lock:
            protected = (protected or set()) | self.potion_paths | {keep, self.path}
        sessions = sorted(
            (item for item in self.root.glob("session-*")
             if item.is_dir() and item not in protected),
            key=lambda item: item.stat().st_mtime,
        )
        cutoff = time.time() - self.config.max_age_days * 86400
        budget = self.config.max_total_mb * 1024 * 1024
        sizes = {
            item: sum(file.stat().st_size for file in item.iterdir() if file.is_file())
            for item in sessions
        }
        total = sum(sizes.values())
        for item in sessions:
            if item.stat().st_mtime >= cutoff and total <= budget:
                continue
            shutil.rmtree(item, ignore_errors=True)
            total -= sizes[item]
