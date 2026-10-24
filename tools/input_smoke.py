"""Exercise SendInput only against this script's own temporary Tk window."""

import json
import threading
import time
import tkinter as tk
from pathlib import Path

from maplebot.config import InputConfig
from maplebot.decision import Action
from maplebot.input_timing import KeyHold
from maplebot.keyboard import KeyboardController, Win32Input
from maplebot.windows import Windows


def main() -> None:
    windows = Windows()
    root = tk.Tk()
    root.title("MapleBot input smoke fixture")
    root.geometry("500x220+80+80")
    root.attributes("-topmost", True)
    tk.Label(root, text="Testing ordinary keyboard input in this test window only.").pack(pady=40)
    events = []
    root.bind("<KeyPress>", lambda event: events.append([event.keysym, "down"]))
    root.bind("<KeyRelease>", lambda event: events.append([event.keysym, "up"]))
    root.update()
    root.focus_force()
    root.update()
    window = next(w for w in windows.list() if w.title == root.title())
    root.focus_force()
    focus_deadline = time.perf_counter() + 1
    while not windows.get(window.hwnd).focused and time.perf_counter() < focus_deadline:
        root.update()
        time.sleep(0.01)
    controller = KeyboardController(
        Win32Input(), InputConfig(), lambda: windows.get(window.hwnd).focused, lambda: False
    )
    try:
        controller.enable()
        timings = []
        for action in ("left", "right", "attack", "jump", "overlap"):
            errors = []

            def execute(name=action, failures=errors):
                try:
                    if name == "overlap":
                        result = controller.execute_sequence(
                            [
                                KeyHold("right", 0.18),
                                KeyHold("jump", 0.06, 0.04),
                            ]
                        )
                    else:
                        result = controller.execute(Action(name, 0.06))
                    if not result.endswith("completed"):
                        failures.append(result)
                except Exception as error:
                    failures.append(str(error))

            worker = threading.Thread(target=execute)
            worker.start()
            while worker.is_alive():
                root.update()
                time.sleep(0.003)
            root.update()
            assert not errors, errors
            timings.append(controller.timing_snapshot())
        expected = [
            [key, direction]
            for key in ("Left", "Right", "z", "space")
            for direction in ("down", "up")
        ]
        expected.extend([["Right", "down"], ["space", "down"], ["space", "up"], ["Right", "up"]])
        assert events == expected, events
        result = {
            "source": "own Tk test window, NOT Unity Game view",
            "backend": "SendInput scan codes",
            "events": events,
            "result": "passed",
            "unity_verified": False,
            "timing_executions": timings,
            "compatible_overlap": "right + jump; independent releases observed",
        }
        directory = Path("artifacts")
        directory.mkdir(exist_ok=True)
        path = directory / f"input-realism-smoke-{time.time_ns()}.json"
        path.write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {
                    "result": "passed",
                    "events": events,
                    "evidence": str(path),
                    "unity_verified": False,
                },
                indent=2,
            )
        )
    finally:
        controller.close()
        root.destroy()


if __name__ == "__main__":
    main()
