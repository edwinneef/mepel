"""Capture our own colored test window, never the game or another application."""

import json
import time
import tkinter as tk
from dataclasses import asdict
from pathlib import Path

import numpy as np

from maplebot.capture import Calibration, Capture
from maplebot.geometry import Rect
from maplebot.runtime import png
from maplebot.windows import Windows


def main() -> None:
    windows = Windows()
    root = tk.Tk()
    root.title("MapleBot capture smoke fixture")
    root.geometry("1024x768+60+60")
    root.configure(background="#163b27")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, width=1024, height=768, highlightthickness=0, bg="#163b27")
    canvas.pack()
    canvas.create_rectangle(100, 100, 300, 250, fill="#ff0000", outline="")
    canvas.create_rectangle(700, 500, 900, 650, fill="#0000ff", outline="")
    root.update()
    root.lift()
    root.update()
    time.sleep(0.15)
    try:
        window = next(w for w in windows.list() if w.title == root.title())
        capture = Capture(windows)
        try:
            timings = []
            for _ in range(20):
                began = time.perf_counter()
                image, state, _ = capture.window(window.hwnd, None)
                timings.append(time.perf_counter() - began)
            assert image.shape == (768, 1024, 3), image.shape
            assert np.max(np.abs(image[150, 150].astype(int) - [0, 0, 255])) < 3, image[150, 150]
            assert np.max(np.abs(image[550, 750].astype(int) - [255, 0, 0])) < 3
            calibration = Calibration(state.title, 1024, 768, state.dpi, Rect(100, 100, 200, 150))
            cropped, _, _ = capture.window(window.hwnd, calibration)
            assert cropped.shape == (150, 200, 3)
            assert np.all(cropped[20:100, 20:150, 2] >= 253)
            root.geometry("1040x768+60+60")
            root.update()
            try:
                capture.window(window.hwnd, calibration)
            except RuntimeError as error:
                assert "recalibrate" in str(error)
            else:
                raise AssertionError("Resize was not detected")
            directory = Path("artifacts")
            directory.mkdir(exist_ok=True)
            (directory / "capture-smoke.png").write_bytes(png(image))
            evidence = {
                "source": "own Tk test window, not MapleUnity",
                "frames": 20,
                "size": [1024, 768],
                "window": asdict(window),
                "mean_capture_ms": round(1000 * np.mean(timings), 3),
                "unpaced_capture_fps": round(1 / np.mean(timings), 2),
                "pixel_checks": "passed",
                "crop": "passed",
                "resize": "passed",
            }
            (directory / "capture-smoke.json").write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence, indent=2))
        finally:
            capture.close()
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
