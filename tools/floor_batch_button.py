"""Local operator button; opening the window never starts gameplay."""
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parents[1]


def main():
    window = tk.Tk()
    window.title("Floor-only combat check")
    window.geometry("640x340")
    tk.Label(window, text="Snail Hunting Ground III / bottom floor / mobs nearby\n"
             "Clear the alarm first. Stay present. F8 stops gameplay.").pack(pady=10)
    output = ScrolledText(window, height=12, wrap="word")
    busy = False

    def finished(text):
        nonlocal busy
        output.insert("end", text + "\n")
        output.see("end")
        busy = False
        button.config(state="normal")

    def worker():
        try:
            result = subprocess.run(
                [sys.executable, "-m", "tools.prepared_floor_check", "--run", "--focus"],
                cwd=ROOT, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
            text = result.stdout + result.stderr
        except Exception as error:
            text = str(error)
        window.after(0, finished, text)

    def start():
        nonlocal busy
        if busy:
            return
        busy = True
        button.config(state="disabled")
        output.insert("end", "Starting one guarded batch; restoring game focus...\n")
        threading.Thread(target=worker, daemon=True).start()

    button = tk.Button(window, text="Start one 60-second floor batch", command=start)
    button.pack(pady=6)
    output.pack(fill="both", expand=True, padx=10, pady=10)

    def close():
        if busy:
            output.insert("end", "Press F8 in game to stop; wait for the result before closing.\n")
        else:
            window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    window.mainloop()


if __name__ == "__main__":
    main()
