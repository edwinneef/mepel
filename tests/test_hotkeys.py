"""Bot hotkeys counted from the keyboard state; the engine's polling thread gates them on focus."""
import threading
from types import SimpleNamespace

from maplebot.hotkeys import HotkeyCounter
from maplebot.runtime import Application


def test_counts_each_press_once_and_ignores_presses_that_may_not_count():
    counter = HotkeyCounter({"start_stop": 117, "stop": 119})
    down: set[int] = set()
    allowed = {"start_stop": True, "stop": True}

    def step():
        return counter.update(lambda key: key in down, lambda name: allowed[name])

    assert step() == []
    down.add(117)
    assert step() == ["start_stop"]
    assert step() == []  # held: still one press
    down.clear()
    step()
    allowed["start_stop"] = False
    down.add(117)
    assert step() == []  # pressed while it may not count
    allowed["start_stop"] = True
    assert step() == []  # and not counted later either, while still held
    assert counter.counts == {"start_stop": 1, "stop": 0}


def test_engine_counts_start_stop_only_with_the_game_in_front_and_stop_always(monkeypatch):
    app = Application.__new__(Application)
    app.closed = threading.Event()
    app.window = SimpleNamespace(hwnd=5)
    app.mode = "capture"
    app.stop_requested = threading.Event()
    stops = []
    app.safe_stop = lambda code, message: stops.append(message)
    app.hotkeys = HotkeyCounter({"start_stop": 117, "drawings": 120, "stop": 119})
    state = {"down": set(), "front": 5, "ticks": []}
    app.windows = SimpleNamespace(pressed=lambda key: key in state["down"],
                                  foreground=lambda hwnd: hwnd == state["front"])
    script = [({117}, 5), (set(), 5), ({117}, 9), (set(), 9), ({119}, 9), (set(), 9)]

    def wait(_seconds):
        if not script:
            return True
        state["down"], state["front"] = script.pop(0)
        return False

    app.closed.wait = wait
    app._poll_hotkeys()
    assert app.hotkeys.counts == {"start_stop": 1, "drawings": 0, "stop": 1}
    assert stops == ["Stop key pressed"]  # Off can still have a pending start.
    assert app.stop_requested.is_set()
    app.mode = "live"
    script[:] = [({119}, 9), (set(), 9)]
    app._poll_hotkeys()
    assert stops == ["Stop key pressed", "Stop key pressed"] and app.stop_requested.is_set()


def test_ordered_hotkeys_record_original_epoch_and_stop_wins_simultaneous_sample():
    counter = HotkeyCounter({"stop": 119, "start_stop": 117})
    counter.update(lambda key: key == 117, lambda name: True, epoch=4)
    counter.update(lambda key: key == 119, lambda name: True, epoch=4)
    snapshot = counter.snapshot()
    assert snapshot["stop_sequence"] > snapshot["start_stop_sequence"]
    assert snapshot["start_stop_epoch"] == 4
    counter.update(lambda key: key == 117, lambda name: True, epoch=5)
    snapshot = counter.snapshot()
    assert snapshot["start_stop_sequence"] > snapshot["stop_sequence"]
    assert snapshot["start_stop_epoch"] == 5
    counter.update(lambda key: False, lambda name: True)
    counter.update(lambda key: True, lambda name: True, epoch=6)
    snapshot = counter.snapshot()
    assert snapshot["stop_sequence"] > snapshot["start_stop_sequence"]
    assert snapshot["sequence"] == 5
