"""Bounded PNG encoding outside the capture worker."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class FramePacket:
    sequence: int
    stem: str
    raw: np.ndarray
    annotated: np.ndarray
    status: dict[str, Any]
    now: float


class FrameEncoder:
    """One latest-frame worker; stale packets are replaced before encoding starts."""

    def __init__(self, on_encoded: Callable[[FramePacket, bytes, bytes, float], None]) -> None:
        self.on_encoded = on_encoded
        self.condition = threading.Condition()
        self.pending: FramePacket | None = None
        self.closed = False
        self.failure: str | None = None
        self.accepted_sequence = -1
        self.encoded_sequence = -1
        self.settled_sequence = -1
        self.replaced = 0
        self.png_encode_ms = 0.0
        self.worker = threading.Thread(target=self._run, name="frame-encoder", daemon=True)
        self.worker.start()

    def publish(self, packet: FramePacket) -> None:
        with self.condition:
            if self.closed:
                raise RuntimeError("Frame encoder is closed")
            if packet.sequence <= self.accepted_sequence:
                raise ValueError("Frame packet sequence must strictly increase")
            if self.pending is not None:
                self.replaced += 1
                self.settled_sequence = max(self.settled_sequence, self.pending.sequence)
            self.pending = packet
            self.accepted_sequence = packet.sequence
            self.condition.notify()

    def flush_through(self, sequence: int, timeout: float) -> dict[str, Any]:
        if timeout <= 0:
            raise ValueError("Encoder flush timeout must be positive")
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.settled_sequence < sequence and self.failure is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {**self.snapshot(), "complete": False, "reason": "timeout"}
                self.condition.wait(remaining)
            if self.failure is not None:
                return {**self.snapshot(), "complete": False, "reason": "failure"}
            return {**self.snapshot(), "complete": True, "reason": "flushed"}

    def snapshot(self) -> dict[str, Any]:
        with self.condition:
            return {
                "accepted_sequence": self.accepted_sequence,
                "encoded_sequence": self.encoded_sequence,
                "settled_sequence": self.settled_sequence,
                "replaced": self.replaced,
                "queue_depth": int(self.pending is not None),
                "png_encode_ms": round(self.png_encode_ms, 3),
                "failure": self.failure,
            }

    def close(self, timeout: float = 2.0) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.worker.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            with self.condition:
                while self.pending is None and not self.closed:
                    self.condition.wait()
                if self.pending is None and self.closed:
                    return
                packet = self.pending
                self.pending = None
            assert packet is not None
            began = time.perf_counter()
            try:
                raw_ok, raw = cv2.imencode(".png", packet.raw)
                annotated_ok, annotated = cv2.imencode(".png", packet.annotated)
                if not raw_ok or not annotated_ok:
                    raise RuntimeError("Could not encode screenshot")
                elapsed = (time.perf_counter() - began) * 1000
                self.on_encoded(packet, raw.tobytes(), annotated.tobytes(), elapsed)
                with self.condition:
                    self.png_encode_ms = elapsed
                    self.encoded_sequence = packet.sequence
            except Exception as error:
                with self.condition:
                    self.failure = str(error)
            finally:
                with self.condition:
                    self.settled_sequence = max(self.settled_sequence, packet.sequence)
                    self.condition.notify_all()
