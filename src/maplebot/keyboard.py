"""Bounded ordinary Win32 keyboard input; no Unity-specific interfaces."""

import atexit
import copy
import ctypes
import queue
import threading
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Protocol

from .config import InputConfig, TimingConfig
from .decision import Action
from .input_timing import ACTIONS, KeyHold, TimingPlanner

KEYS = {
    "left": 0x25,
    "right": 0x27,
    "up": 0x26,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "a": 0x41,
    "d": 0x44,
    "z": 0x5A,
    "ctrl": 0xA2,
    "space": 0x20,
    "f8": 0x77,
    **{chr(code): code - 0x20 for code in range(ord("a"), ord("z") + 1)},
    **{str(digit): 0x30 + digit for digit in range(10)},
    **{f"f{number}": 0x6F + number for number in range(1, 13)},
}

EXTENDED_KEYS = frozenset(
    {"left", "right", "up", "down", "insert", "delete", "home", "end", "pageup", "pagedown"}
)


class InputBackend(Protocol):
    def send(self, key: str, down: bool) -> None: ...


class DisabledInput:
    """No OS input implementation exists in a capture-only session."""

    def send(self, key: str, down: bool) -> None:
        raise RuntimeError("Capture-only session: keyboard output is locked")


@dataclass(frozen=True)
class ActionOutcome:
    ticket: int
    generation: int
    action: str
    result: str
    submitted_at: float
    started_at: float | None
    finished_at: float


@dataclass(frozen=True)
class _QueuedPlan:
    ticket: int
    generation: int
    action: str
    schedule: object
    submitted_at: float


@dataclass(frozen=True)
class VerticalLease:
    lease_id: int
    generation: int
    action: str
    key: str
    deadline: float
    total_deadline: float


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
        flags = self.flags_for(key, down)
        event = Input(
            type=1,
            value=InputUnion(
                keyboard=KeyboardInput(0, self.api.MapVirtualKeyW(vk, 0), flags, 0, 0)
            ),
        )
        if self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
            raise OSError("SendInput failed (focus/integrity restriction possible); input stopped")

    @staticmethod
    def flags_for(key: str, down: bool) -> int:
        return 0x0008 | (0 if down else 0x0002) | (0x0001 if key in EXTENDED_KEYS else 0)


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
        on_stop: Callable[[str, str], None] | None = None,
    ) -> None:
        for key in (
            config.left, config.right, config.attack, config.jump, config.up, config.down,
            config.hp_potion, config.mp_potion, config.pet_food, config.skill, config.emergency_key,
        ):
            if key not in KEYS:
                raise ValueError(f"Unsupported key: {key}")
        self.backend, self.config = backend, config
        self.safe, self.emergency, self.replay = safe, emergency, replay
        self.on_stop = on_stop
        self.enabled = False
        self.stopped = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.RLock()
        self.execution_lock = threading.Lock()
        self.generation = 0
        self.next_ticket = 1
        self.queue: queue.Queue[_QueuedPlan | None] = queue.Queue(maxsize=32)
        self.outcomes: queue.SimpleQueue[ActionOutcome] = queue.SimpleQueue()
        self.active: _QueuedPlan | None = None
        self.errors: dict[int, Exception] = {}
        self.leases: dict[int, VerticalLease] = {}
        self.next_lease_id = 1
        self.held: dict[str, float] = {}
        self.planner = TimingPlanner(config, timing or TimingConfig())
        self.execution_started = time.perf_counter()
        self.last_timing: dict = {"schedule": None, "events": [], "outcome": "none"}
        self.reason = "Input disabled"
        self.watchdog = threading.Thread(target=self._watch, name="key-watchdog", daemon=True)
        self.executor = threading.Thread(
            target=self._execute_queued, name="key-executor", daemon=True
        )
        self.watchdog.start()
        self.executor.start()
        atexit.register(self.close)

    def enable(self) -> None:
        if self.replay:
            raise RuntimeError("Replay cannot enable real keyboard input")
        if not self.safe() or self.emergency():
            raise RuntimeError("Target not safe/focused, or emergency key held")
        with self.lock:
            self.stopped.clear()
            self.reason, self.enabled = "Ready", True

    def stop(
        self,
        reason: str = "Stopped",
        *,
        code: str = "INPUT_BACKEND_FAILURE",
        notify: bool = True,
    ) -> None:
        with self.lock:
            self.enabled = False
            self.stopped.set()
            self.generation += 1
            self.reason = reason
            self._cancel_queued()
            self.release_all()
        if notify and self.on_stop is not None:
            self.on_stop(code, reason)

    def _cancel_queued(self) -> None:
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                return
            if item is not None:
                self._finish(item, f"{item.action} interrupted", None)

    def _finish(self, item: _QueuedPlan, result: str, started_at: float | None) -> None:
        self.outcomes.put(
            ActionOutcome(
                item.ticket,
                item.generation,
                item.action,
                result,
                item.submitted_at,
                started_at,
                time.perf_counter(),
            )
        )

    def poll_outcomes(self) -> list[ActionOutcome]:
        result: list[ActionOutcome] = []
        while True:
            try:
                result.append(self.outcomes.get_nowait())
            except queue.Empty:
                return result

    def submit(self, action: Action) -> int | str:
        if action.kind == "release":
            self.release_all()
            return "release"
        if action.kind not in ACTIONS:
            raise ValueError(f"Unknown action: {action.kind}")
        if not 0 < action.seconds <= self.config.max_action_seconds:
            self.stop("Maximum action duration exceeded", code="INPUT_BACKEND_FAILURE")
            return "blocked: duration"
        with self.lock:
            if self.replay or not self.enabled or self.stopped.is_set():
                return "blocked: input disabled"
            try:
                schedule = self.planner.plan([KeyHold(action.kind, action.seconds)])
                ticket = self.next_ticket
                self.next_ticket += 1
                item = _QueuedPlan(
                    ticket, self.generation, action.kind, schedule, time.perf_counter()
                )
                self.queue.put_nowait(item)
                return ticket
            except queue.Full:
                return "blocked: queue full"

    def _execute_queued(self) -> None:
        while not self.closed.is_set():
            try:
                item = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is None:
                return
            started_at = time.perf_counter()
            with self.lock:
                self.active = item
            try:
                result = self._execute_schedule(item)
            except Exception as error:
                self.errors[item.ticket] = error
                self.stop("Keyboard backend failure", code="INPUT_BACKEND_FAILURE")
                result = f"{item.action} interrupted"
            finally:
                with self.lock:
                    self.active = None
            self._finish(item, result, started_at)

    def _cancelled(self, item: _QueuedPlan) -> bool:
        return self._cancelled_generation(item.generation)

    def release_all(self) -> None:
        with self.lock:
            self._release_keys(list(self.held))

    def release(self, action: str) -> None:
        """Release one currently held logical action, without releasing compatible keys."""
        if action not in ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        with self.lock:
            self._release_keys([getattr(self.config, action)])

    def start_vertical_lease(self, action: str) -> int:
        if action not in {"up", "down"}:
            raise ValueError("Only configured up/down actions may use a vertical lease")
        with self.lock:
            if self._cancelled_generation(self.generation) or self.emergency() or not self.safe():
                raise RuntimeError("Input is not safe for a vertical lease")
            now = time.perf_counter()
            key = getattr(self.config, action)
            lease_id = self.next_lease_id
            self.next_lease_id += 1
            lease = VerticalLease(
                lease_id, self.generation, action, key,
                now + self.config.vertical_lease_seconds,
                now + self.config.vertical_lease_max_seconds,
            )
            self.held[key] = lease.deadline
            self.leases[lease_id] = lease
            try:
                self._send(key, True)
            except Exception:
                self.stop("Keyboard backend failure", code="INPUT_BACKEND_FAILURE")
                raise
            return lease_id

    def renew_vertical_lease(self, lease_id: int) -> bool:
        with self.lock:
            lease = self.leases.get(lease_id)
            if lease is None:
                return False
            now = time.perf_counter()
            if (
                now >= lease.deadline
                or now >= lease.total_deadline
                or lease.generation != self.generation
                or self._cancelled_generation(lease.generation)
                or self.emergency()
                or not self.safe()
            ):
                self._release_lease(lease_id)
                return False
            renewed = VerticalLease(
                lease.lease_id, lease.generation, lease.action, lease.key,
                min(now + self.config.vertical_lease_seconds, lease.total_deadline),
                lease.total_deadline,
            )
            self.leases[lease_id] = renewed
            self.held[lease.key] = renewed.deadline
            return True

    def release_vertical_lease(self, lease_id: int) -> bool:
        with self.lock:
            return self._release_lease(lease_id)

    def _release_lease(self, lease_id: int) -> bool:
        lease = self.leases.pop(lease_id, None)
        if lease is None:
            return False
        self._release_keys([lease.key])
        return True

    def _cancelled_generation(self, generation: int) -> bool:
        return self.stopped.is_set() or generation != self.generation or not self.enabled

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
                for lease_id, lease in tuple(self.leases.items()):
                    if lease.key == key:
                        del self.leases[lease_id]
            except Exception as error:
                self.reason = f"Key release failed: {error}"
                self.stopped.set()
                self.enabled = False

    def timing_snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.last_timing)

    def execute(self, action: Action) -> str:
        submitted = self.submit(action)
        if not isinstance(submitted, int):
            return submitted
        while not self.closed.is_set():
            for outcome in self.poll_outcomes():
                if outcome.ticket == submitted:
                    if error := self.errors.pop(submitted, None):
                        raise error
                    return outcome.result
                self.outcomes.put(outcome)
            self.closed.wait(0.001)
        return f"{action.kind} interrupted"

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
                        self.stop("Focus/safety lost or emergency stop", code="FOCUS_LOSS")
                        return "sequence interrupted"
                    if event.down:
                        up = next(
                            item
                            for item in schedule.events[index + 1 :]
                            if item.key == event.key and not item.down
                        )
                        deadline = self.execution_started + up.at_seconds
                        if time.perf_counter() >= deadline:
                            self.stop(
                                "Input schedule expired before key down",
                                code="INPUT_BACKEND_FAILURE",
                            )
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
            self.stop("Invalid input sequence", code="INPUT_BACKEND_FAILURE")
            raise
        except Exception:
            self.stop("Keyboard backend failure", code="INPUT_BACKEND_FAILURE")
            raise
        finally:
            self.release_all()
            with self.lock:
                if self.last_timing["outcome"] == "running":
                    self.last_timing["outcome"] = "interrupted"

    def _execute_schedule(self, item: _QueuedPlan) -> str:
        schedule = item.schedule
        self.release_all()
        with self.lock:
            if self._cancelled(item) or self.emergency() or not self.safe():
                self.stop("Focus/safety lost or emergency stop", code="FOCUS_LOSS")
                return f"{item.action} interrupted"
            self.execution_started = time.perf_counter()
            self.last_timing = {"schedule": asdict(schedule), "events": [], "outcome": "running"}
        last_down = float("-inf")
        try:
            for index, event in enumerate(schedule.events):
                due = self.execution_started + event.at_seconds
                if event.down and self.planner.config.enabled:
                    due = max(due, last_down + self.planner.config.key_stagger_seconds)
                if self.stopped.wait(max(0, due - time.perf_counter())):
                    return f"{item.action} interrupted"
                with self.lock:
                    if self._cancelled(item) or self.emergency() or not self.safe():
                        self.stop("Focus/safety lost or emergency stop", code="FOCUS_LOSS")
                        return f"{item.action} interrupted"
                    if event.down:
                        up = next(
                            later
                            for later in schedule.events[index + 1 :]
                            if later.key == event.key and not later.down
                        )
                        if time.perf_counter() >= self.execution_started + up.at_seconds:
                            self.stop(
                                "Input schedule expired before key down",
                                code="INPUT_BACKEND_FAILURE",
                            )
                            return f"{item.action} interrupted"
                        self.held[event.key] = self.execution_started + up.at_seconds
                        self._send(event.key, True)
                        last_down = (
                            self.execution_started + self.last_timing["events"][-1]["at_seconds"]
                        )
                    else:
                        self._release_keys([event.key])
            if self.stopped.wait(schedule.rest_seconds):
                return f"{item.action} interrupted"
            with self.lock:
                self.last_timing["outcome"] = "completed"
            return f"{item.action} completed"
        finally:
            self.release_all()
            with self.lock:
                if self.last_timing["outcome"] == "running":
                    self.last_timing["outcome"] = "interrupted"

    def _watch(self) -> None:
        while not self.closed.wait(0.005):
            try:
                if self.emergency():
                    self.stop("Emergency stop hotkey", code="EMERGENCY_STOP")
                elif self.enabled and not self.safe():
                    self.stop("Target focus, geometry, or visibility lost", code="FOCUS_LOSS")
                else:
                    with self.lock:
                        expired = [
                            key
                            for key, deadline in self.held.items()
                            if time.perf_counter() >= deadline
                        ]
                        self._release_keys(expired)
            except Exception as error:
                self.stop(f"Input watchdog failure: {error}", code="INPUT_WATCHDOG_FAILURE")

    def close(self) -> None:
        self.stop("Controller closed", notify=False)
        self.closed.set()
        self.queue.put_nowait(None)
        if threading.current_thread() is not self.executor:
            self.executor.join(timeout=1)
        if threading.current_thread() is not self.watchdog:
            self.watchdog.join(timeout=1)
        atexit.unregister(self.close)
