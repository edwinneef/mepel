"""Read-only screenshots for the workbench, independent of expensive recognition."""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import cv2

from .capture import Calibration, Capture
from .geometry import Rect
from .windows import Windows


@dataclass(frozen=True)
class PreviewSource:
    id: str
    hwnd: int | None
    manual: Rect | None
    calibration: Calibration | None


class PreviewStream:
    def __init__(self, source: Callable[[], PreviewSource], fps: float, *,
                 capture_factory: Callable | None = None) -> None:
        self.source = source
        self.interval = 1 / max(1, min(fps, 12))
        self.capture_factory = capture_factory or (lambda: Capture(Windows()))
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.worker: threading.Thread | None = None
        self.frames: deque[tuple[dict, bytes]] = deque(maxlen=3)
        self.sequence = 0
        self.available = False
        self.latest_capture: tuple | None = None

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._run, name="preview-stream", daemon=True)
        self.worker.start()

    def close(self) -> None:
        self.closed.set()
        if self.worker:
            self.worker.join(timeout=2)

    def _run(self) -> None:
        capture = None
        try:
            capture = self.capture_factory()
            while not self.closed.is_set():
                began = time.perf_counter()
                self._capture_once(capture)
                self.closed.wait(max(0, self.interval - (time.perf_counter() - began)))
        finally:
            if capture:
                capture.close()

    def _capture_once(self, capture: Capture) -> None:
        source = self.source()
        try:
            captured_at = time.time()
            if source.hwnd:
                image, window, region = capture.window(source.hwnd, source.calibration)
            elif source.manual:
                image = capture.grab(source.manual)
                window, region = None, source.manual
            else:
                raise RuntimeError("No capture source")
            ok, encoded = cv2.imencode(".png", image)
            if not ok or source != self.source():
                raise RuntimeError("Preview source changed")
            with self.lock:
                self.sequence += 1
                self.frames.append(({
                    "source_id": source.id, "id": f"{source.id}:preview:{self.sequence}",
                    "sequence": self.sequence, "captured_at": captured_at,
                    "width": image.shape[1], "height": image.shape[0],
                }, encoded.tobytes()))
                self.available = True
                self.latest_capture = (source.id, captured_at, image, window, region)
        except Exception:
            # This stream cannot authorize input or change the engine's safety state.
            with self.lock:
                self.available = False

    def snapshot(self, source_id: str) -> dict:
        with self.lock:
            frame = self.frames[-1][0] if self.frames else None
            if (self.available and frame and frame["source_id"] == source_id
                    and time.time() - frame["captured_at"] <= 1):
                return {**frame, "available": True,
                        "age_ms": max(0, (time.time() - frame["captured_at"]) * 1000)}
        return {"source_id": source_id, "id": None, "sequence": None, "captured_at": None,
                "width": 0, "height": 0, "age_ms": None, "available": False}

    def frame(self, frame_id: str, source_id: str) -> bytes | None:
        with self.lock:
            return next((body for frame, body in self.frames
                         if frame["id"] == frame_id and frame["source_id"] == source_id), None)

    def frozen(self, source_id: str) -> tuple | None:
        with self.lock:
            packet = self.latest_capture
            if (self.available and packet and packet[0] == source_id
                    and time.time() - packet[1] <= 1):
                return packet[2].copy(), packet[3], packet[4]
            return None
