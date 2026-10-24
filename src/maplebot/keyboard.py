"""Bounded ordinary Win32 keyboard input; no Unity-specific interfaces."""

import atexit
import copy
import ctypes
import threading
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import asdict
from typing import Protocol

from .config import InputConfig, TimingConfig
from .decision import Action
from .input_timing import ACTIONS, KeyHold, TimingPlanner

KEYS = {
    "left": 0x25,
    "right": 0x27,
    "a": 0x41,
    "d": 0x44,
    "z": 0x5A,
    "ctrl": 0xA2,
    "space": 0x20,
    "f8": 0x77,
}


class InputBackend(Protocol):
    def send(self, key: str, down: bool) -> None: ...


class DisabledInput:
    """No OS input implementation exists in a capture-only session."""

    def send(self, key: str, down: bool) -> None:
        raise RuntimeError("Capture-only session: keyboard output is locked")


class Win32Input:
    def __init__(self) -> None:
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        self.api.MapVirtualKeyW.restype = wintypes.UINT
        self.api.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
        self.api.SendInput.restype = wintypes.UINT

    def send(self, key: str, down: bool) -> None:
        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("vk", wintypes.WORD),
                ("scan", wintypes.WORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("extra", ctypes.c_size_t),
            ]

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("data", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("extra", ctypes.c_size_t),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]

        class Input(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("value", InputUnion)]

        vk = KEYS[key]
        flags = 0x0008 | (0 if down else 0x0002)
        if key in ("left", "right"):
            flags |= 0x0001
        event = Input(
            type=1,
            value=InputUnion(
                keyboard=KeyboardInput(0, self.api.MapVirtualKeyW(vk, 0), flags, 0, 0)
            ),
        )
        if self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError("SendInput failed (focus/integrity restriction possible); input stopped")


class KeyboardController:
    def __init__(
        self,
        backend: InputBackend,
        config: InputConfig,
        safe: Callable[[], bool],
        emergency: Callable[[], bool],
        *,
        replay: bool = False,
        timing: TimingConfig | None = None,
    ) -> None:
        for key in (config.left, config.right, config.attack, config.jump, config.emergency_key):
            if key not in KEYS:
                raise ValueError(f"Unsupported key: {key}")
        self.backend, self.config = backend, config
        self.safe, self.emergency, self.replay = safe, emergency, replay
        self.enabled = False
        self.stopped = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.RLock()
        self.execution_lock = threading.Lock()
        self.held: dict[str, float] = {}
        self.planner = TimingPlanner(config, timing or TimingConfig())
        self.execution_started = time.perf_counter()
        self.last_timing: dict = {"schedule": None, "events": [], "outcome": "none"}
        self.reason = "Input disabled"
        self.watchdog = threading.Thread(target=self._watch, name="key-watchdog", daemon=True)
        self.watchdog.start()
        atexit.register(self.close)

    def enable(self) -> None:
        if self.replay:
            raise RuntimeError("Replay cannot enable real keyboard input")
        if not self.safe() or self.emergency():
            raise RuntimeError("Target not safe/focused, or emergency key held")
        with self.lock:
            self.stopped.clear()
            self.reason, self.enabled = "Ready", True

    def stop(self, reason: str = "Stopped") -> None:
        with self.lock:
            self.enabled = False
            self.stopped.set()
            self.reason = reason
            self.release_all()

    def release_all(self) -> None:
        with self.lock:
            self._release_keys(list(self.held))

    def release(self, action: str) -> None:
        """Release one currently held logical action, without releasing compatible keys."""
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        with self.lock:
            self._release_keys([getattr(self.config, action)])

    def _send(self, key: str, down: bool) -> None:
        at_seconds = time.perf_counter() - self.execution_started
        self.backend.send(key, down)
        self.last_timing["events"].append({"key": key, "down": down, "at_seconds": at_seconds})

    def _release_keys(self, keys: list[str]) -> None:
        for key in keys:
            if key not in self.held:
                continue
            try:
                self._send(key, False)
                del self.held[key]
            except Exception as error:
                self.reason = f"Key release failed: {error}"
                self.stopped.set()
                self.enabled = False

    def timing_snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.last_timing)

    def execute(self, action: Action) -> str:
        if action.kind == "release":
            self.release_all()
            return "release"
        if self.replay or not self.enabled or self.stopped.is_set():
            return "blocked: input disabled"
        if not 0 < action.seconds <= self.config.max_action_seconds:
            self.stop("Maximum action duration exceeded")
            return "blocked: duration"
        if action.kind not in ("left", "right", "attack", "jump"):
            raise ValueError(f"Unknown action: {action.kind}")
        return self.execute_sequence([KeyHold(action.kind, action.seconds)]).replace(
            "sequence", action.kind, 1
        )

    def execute_sequence(self, holds: Sequence[KeyHold]) -> str:
        """Execute one bounded plan. Movement/jump/attack may overlap; opposites may not."""
        with self.execution_lock:
            return self._execute_sequence(holds)

    def _execute_sequence(self, holds: Sequence[KeyHold]) -> str:
        self.release_all()
        if not holds:
            return "release"
        if self.replay or not self.enabled or self.stopped.is_set():
            return "blocked: input disabled"
        try:
            schedule = self.planner.plan(holds)
            with self.lock:
                self.execution_started = time.perf_counter()
                self.last_timing = {
                    "schedule": asdict(schedule),
                    "events": [],
                    "outcome": "running",
                }
            last_down = float("-inf")
            for index, event in enumerate(schedule.events):
                due = self.execution_started + event.at_seconds
                if event.down and self.planner.config.enabled:
                    due = max(due, last_down + self.planner.config.key_stagger_seconds)
                wait = due - time.perf_counter()
                if self.stopped.wait(max(0, wait)):
                    return "sequence interrupted"
                with self.lock:
                    if not self.enabled or self.emergency() or not self.safe():
                        self.stop("Focus/safety lost or emergency stop")
                        return "sequence interrupted"
                    if event.down:
                        up = next(
                            item
                            for item in schedule.events[index + 1 :]
                            if item.key == event.key and not item.down
                        )
                        deadline = self.execution_started + up.at_seconds
                        if time.perf_counter() >= deadline:
                            self.stop("Input schedule expired before key down")
                            return "sequence interrupted"
                        self.held[event.key] = deadline
                        self._send(event.key, True)
                        last_down = (
                            self.execution_started + self.last_timing["events"][-1]["at_seconds"]
                        )
                    else:
                        self._release_keys([event.key])
            if self.stopped.wait(schedule.rest_seconds):
                return "sequence interrupted"
            with self.lock:
                self.last_timing["outcome"] = "completed"
            return "sequence completed"
        except ValueError:
            self.stop("Invalid input sequence")
            raise
        except Exception:
            self.stop("Keyboard backend failure")
            raise
        finally:
            self.release_all()
            with self.lock:
                if self.last_timing["outcome"] == "running":
                    self.last_timing["outcome"] = "interrupted"

    def _watch(self) -> None:
        while not self.closed.wait(0.005):
            try:
                if self.emergency():
                    self.stop("Emergency stop hotkey")
                elif self.enabled and not self.safe():
                    self.stop("Target focus, geometry, or visibility lost")
                else:
                    with self.lock:
                        expired = [
                            key
                            for key, deadline in self.held.items()
                            if time.perf_counter() >= deadline
                        ]
                        self._release_keys(expired)
            except Exception as error:
                self.stop(f"Input watchdog failure: {error}")

    def close(self) -> None:
        self.stop("Controller closed")
        self.closed.set()
        if threading.current_thread() is not self.watchdog:
            self.watchdog.join(timeout=1)
        atexit.unregister(self.close)
