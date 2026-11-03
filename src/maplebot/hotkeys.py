"""Bot hotkeys read straight from the keyboard state.

With MapleStory in front, the overlay's system-wide hotkeys never fired (2026-11-03), while
the engine's own stop-key reading (GetAsyncKeyState) always did. The engine counts each
press here; the dashboard and the in-game overlay act on new counts from the status.
"""
from collections.abc import Callable


class HotkeyCounter:
    """Counts presses (key-down edges) per hotkey name; reads only, never sends input."""

    def __init__(self, keys: dict[str, int]):
        self.keys = dict(keys)
        self.down = {name: False for name in self.keys}
        self.counts = {name: 0 for name in self.keys}
        self.sequence = 0
        self.last_sequence = {name: 0 for name in self.keys}
        self.start_epoch = 0

    def update(self, pressed: Callable[[int], bool], counted: Callable[[str], bool],
               *, epoch: int = 0) -> list[str]:
        """Read every key once; return the names newly pressed and counted.

        A key held down counts once. A press while `counted(name)` is false (for example
        with another window in front) is ignored, also after that window loses focus.
        """
        fired = []
        for name, key in self.keys.items():
            down = bool(pressed(key))
            if down and not self.down[name] and counted(name):
                self.counts[name] += 1
                fired.append(name)
            self.down[name] = down
        # A poll cannot determine physical order within that sample. Stop wins it.
        for name in sorted(fired, key=lambda name: name == "stop"):
            self.sequence += 1
            self.last_sequence[name] = self.sequence
            if name == "start_stop":
                self.start_epoch = epoch
        return fired

    def snapshot(self) -> dict[str, int]:
        return {**self.counts, "sequence": self.sequence,
                "start_stop_sequence": self.last_sequence.get("start_stop", 0),
                "stop_sequence": self.last_sequence.get("stop", 0),
                "start_stop_epoch": self.start_epoch}
