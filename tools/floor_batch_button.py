"""Local operator start window; opening it never starts gameplay.

Default: the prepared fh66 floor batch. `--route AREA ORIGIN TARGET --label TEXT` starts
one prepared supervised route instead (tools/prepared_route_check.py), and
`--farm AREA ORIGIN --minutes N --label TEXT` one learn_moves farming session
(tools/prepared_farm_check.py). Either way the click starts one bounded batch, which
re-checks every gate itself.
"""
import argparse
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parents[1]


def batch(argv: list[str] | None) -> tuple[str, str, str, list[str]]:
    """Window title, instructions, button text and module arguments for the batch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", nargs=3, metavar=("AREA", "ORIGIN", "TARGET"))
    parser.add_argument("--farm", nargs=2, metavar=("AREA", "ORIGIN"))
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--label", help="Where to stand and where the route goes")
    args = parser.parse_args(argv or [])
    if args.route and args.farm:
        parser.error("Choose --route or --farm, not both")
    if args.farm:
        area, origin = args.farm
        return ("Supervised learn_moves farming",
                args.label or f"Stand on {origin}; farm and learn moves",
                f"Start one {args.minutes}-minute learn_moves farm from {origin}",
                ["tools.prepared_farm_check", "--area", area, "--origin", origin,
                 "--minutes", str(args.minutes), "--run", "--focus"])
    if args.route is None:
        return ("Floor-only combat check",
                "Snail Hunting Ground III / bottom floor / mobs nearby",
                "Start one 60-second floor batch",
                ["tools.prepared_floor_check", "--run", "--focus"])
    area, origin, target = args.route
    return ("Supervised route check", args.label or f"Stand on {origin}; route to {target}",
            f"Start one route {origin} -> {target}",
            ["tools.prepared_route_check", "--area", area, "--origin", origin,
             "--target", target, "--run", "--focus"])


def main(argv: list[str] | None = None, *, runner=subprocess.run, on_ready=None):
    title, instructions, label, module = batch(argv)
    window = tk.Tk()
    window.title(title)
    window.geometry("640x340")
    tk.Label(window, text=instructions + "\n"
             "Clear the alarm first. Stay present. F8 stops gameplay.").pack(pady=10)
    output = ScrolledText(window, height=12, wrap="word")
    busy = False
    results = queue.SimpleQueue()

    def finished(text):
        nonlocal busy
        output.insert("end", text + "\n")
        output.see("end")
        busy = False
        window.deiconify()
        button.config(state="normal")

    def worker():
        try:
            result = runner(
                [str(Path(sys.executable).with_name("python.exe")), "-m", *module],
                cwd=ROOT, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
            text = result.stdout + result.stderr
        except Exception as error:
            text = str(error)
        results.put(text)

    def poll_result():
        try:
            text = results.get_nowait()
        except queue.Empty:
            window.after(25, poll_result)
        else:
            finished(text)

    def start():
        nonlocal busy
        if busy:
            return
        busy = True
        button.config(state="disabled")
        output.insert("end", "Starting one guarded batch; restoring game focus...\n")
        window.withdraw()
        threading.Thread(target=worker, daemon=True).start()
        window.after(25, poll_result)

    button = tk.Button(window, text=label, command=start)
    button.pack(pady=6)
    output.pack(fill="both", expand=True, padx=10, pady=10)

    def close():
        if busy:
            output.insert("end", "Press F8 in game to stop; wait for the result before closing.\n")
        else:
            window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    if on_ready is not None:
        window.after(0, on_ready, window, button, output)
    window.mainloop()


if __name__ == "__main__":
    main(sys.argv[1:])
