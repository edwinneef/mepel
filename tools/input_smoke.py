"""Exercise SendInput only against this script's own temporary Tk window."""

import json
import threading
import time
import tkinter as tk
from pathlib import Path

from maplebot.config import InputConfig
from maplebot.decision import Action
from maplebot.input_timing import direction_then_jump, down_then_jump
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
        for action in (
            "left", "right", "up", "down", "attack", "jump", "down_jump", "direction_jump"
        ):
            errors = []

            def execute(name=action, failures=errors):
                try:
                    if name == "down_jump":
                        result = controller.execute_sequence(down_then_jump())
                    elif name == "direction_jump":
                        result = controller.execute_sequence(direction_then_jump("right"))
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
            for key in ("Left", "Right", "Up", "Down", "z", "space")
            for direction in ("down", "up")
        ]
        expected.extend([["Down", "down"], ["space", "down"], ["space", "up"], ["Down", "up"]])
        expected.extend([["Right", "down"], ["space", "down"], ["space", "up"], ["Right", "up"]])
        assert events == expected, events
        result = {
            "source": "own Tk test window, NOT a game view",
            "backend": "SendInput scan codes",
            "events": events,
            "result": "passed",
            "game_verified": False,
            "timing_executions": timings,
            "ordered_chords": "Down+Jump and Right+Jump; own-window receipt only",
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
                    "game_verified": False,
                },
                indent=2,
            )
        )
    finally:
        controller.close()
        root.destroy()


if __name__ == "__main__":
    main()
