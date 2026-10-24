"""Run the full debugger against our own synthetic window, never MapleUnity."""

import argparse
import json
import shutil
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from maplebot.config import Config
from maplebot.debugger import serve
from maplebot.runtime import Application
from maplebot.windows import Windows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=120)
    args = parser.parse_args()
    windows = Windows()
    root = tk.Tk()
    root.title("MapleBot debugger smoke fixture")
    root.geometry("1024x768+60+60")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    image = tk.PhotoImage(file="artifacts/synthetic/frames/0000.png")
    tk.Label(root, image=image, borderwidth=0).pack()
    root.update()
    window = next(w for w in windows.list() if w.title == root.title())
    directory = Path("artifacts/ui-smoke") / str(time.time_ns())
    shutil.copytree("artifacts/synthetic/templates", directory / "templates")
    config = Config()
    config = replace(
        config,
        capture=replace(config.capture, data_dir=str(directory)),
        debugger=replace(config.debugger, port=8766),
    )
    app = Application(config)
    server = serve(app, 8766)
    app.start()
    executor = ThreadPoolExecutor(max_workers=1)

    def request(name, payload):
        # GetWindowText on our own process needs Tk's UI thread to keep pumping events.
        future = executor.submit(app.request, name, payload)
        while not future.done():
            root.update()
            time.sleep(0.005)
        return future.result()

    def pump_until(predicate, seconds=5):
        deadline = time.perf_counter() + seconds
        while not predicate():
            root.update()
            time.sleep(0.01)
            if time.perf_counter() > deadline:
                raise RuntimeError(f"Debugger fixture timed out: {app.snapshot()}")

    try:
        request("attach", {"hwnd": window.hwnd})
        pump_until(app.frame_ready.is_set)
        frozen = request("freeze", {})
        request("crop", {"id": frozen["id"], "x": 0, "y": 0, "width": 1024, "height": 768})
        pump_until(lambda: app.image is not None)
        request("confirm_capture", {})
        request("dry_run", {})
        print("Synthetic debugger smoke: http://127.0.0.1:8766 (no gameplay input)", flush=True)
        deadline = time.perf_counter() + args.seconds
        while time.perf_counter() < deadline:
            root.update()
            time.sleep(0.02)
        (directory / "status.json").write_text(
            json.dumps(app.snapshot(), indent=2), encoding="utf-8"
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        app.close()
        server.shutdown()
        server.server_close()
        root.destroy()


if __name__ == "__main__":
    main()
