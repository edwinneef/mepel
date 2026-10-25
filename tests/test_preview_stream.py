import threading
import time

import numpy as np

from maplebot.preview_stream import PreviewSource, PreviewStream


class Capture:
    def window(self, hwnd, calibration):
        return np.zeros((24, 32, 3), dtype=np.uint8), None, None

    def close(self):
        pass


def test_preview_keeps_refreshing_while_recognition_is_blocked():
    source = PreviewSource("session:source:1", 1, None, None)
    preview = PreviewStream(lambda: source, 30, capture_factory=Capture)
    blocked = threading.Event()
    recognition = threading.Thread(target=lambda: blocked.wait(2))
    recognition.start()
    preview.start()
    try:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            frame = preview.snapshot(source.id)
            if frame["available"] and frame["sequence"] >= 2:
                break
            time.sleep(0.01)
        assert frame["available"] and frame["sequence"] >= 2
        assert frame["age_ms"] < 500
        assert recognition.is_alive()
        assert preview.frame(frame["id"], source.id).startswith(b"\x89PNG")
        assert preview.frame(frame["id"], "another-source") is None
    finally:
        preview.close()
        blocked.set()
        recognition.join()


def test_preview_discards_capture_if_source_changes_before_publication():
    current = PreviewSource("first", 1, None, None)

    class ChangingCapture(Capture):
        def window(self, hwnd, calibration):
            nonlocal current
            current = PreviewSource("second", 2, None, None)
            return super().window(hwnd, calibration)

    preview = PreviewStream(lambda: current, 12)
    preview._capture_once(ChangingCapture())
    assert not preview.snapshot("second")["available"]
    preview._capture_once(Capture())
    assert preview.snapshot("second")["available"]
    assert not preview.snapshot("first")["available"]


def test_preview_failure_does_not_republish_an_old_frame_as_fresh():
    source = PreviewSource("source", 1, None, None)
    preview = PreviewStream(lambda: source, 12)
    preview._capture_once(Capture())

    class FailedCapture(Capture):
        def window(self, hwnd, calibration):
            raise RuntimeError("Target unavailable")

    preview._capture_once(FailedCapture())
    assert not preview.snapshot(source.id)["available"]

