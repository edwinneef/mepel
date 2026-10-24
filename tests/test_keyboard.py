import threading
import time

import pytest

from maplebot.config import InputConfig, TimingConfig
from maplebot.decision import Action
from maplebot.input_timing import KeyHold
from maplebot.keyboard import KeyboardController


class Backend:
    def __init__(self):
        self.events = []
        self.down = threading.Event()
        self.released = threading.Event()

    def send(self, key, down):
        self.events.append((key, down))
        (self.down if down else self.released).set()


@pytest.fixture
def controller():
    backend = Backend()
    flags = {"focus": True, "emergency": False}
    controller = KeyboardController(
        backend, InputConfig(), lambda: flags["focus"], lambda: flags["emergency"]
    )
    yield controller, backend, flags
    controller.close()


def test_disabled_input_and_replay_send_no_keys(controller):
    control, backend, _ = controller
    assert control.execute(Action("right", 0.02)).startswith("blocked")
    control.replay = True
    with pytest.raises(RuntimeError, match="Replay"):
        control.enable()
    assert backend.events == []


def test_short_press_releases_and_duration_limit_blocks(controller):
    control, backend, _ = controller
    control.enable()
    control.execute(Action("right", 0.02))
    assert backend.events == [("right", True), ("right", False)]
    assert control.execute(Action("attack", 3)) == "blocked: duration"
    assert len(backend.events) == 2
    assert not control.held


@pytest.mark.parametrize("flag", ["focus", "emergency"])
def test_watchdog_releases_immediately_on_focus_loss_or_emergency(controller, flag):
    control, backend, flags = controller
    control.enable()
    thread = threading.Thread(target=control.execute, args=(Action("left", 0.24),))
    thread.start()
    assert backend.down.wait(1)
    flags[flag] = flag == "emergency"
    assert backend.released.wait(0.15)
    thread.join(1)
    assert not thread.is_alive()
    assert backend.events == [("left", True), ("left", False)]
    assert not control.enabled


def test_lost_focus_prevents_key_down(controller):
    control, backend, flags = controller
    flags["focus"] = False
    with pytest.raises(RuntimeError, match="safe/focused"):
        control.enable()
    assert backend.events == []


def test_backend_exception_still_releases_key(controller):
    control, backend, _ = controller
    send = backend.send

    def fail_after_down(key, down):
        send(key, down)
        if down:
            raise OSError("simulated backend crash")

    backend.send = fail_after_down
    control.enable()
    with pytest.raises(OSError, match="crash"):
        control.execute(Action("attack", 0.02))
    assert backend.events == [("z", True), ("z", False)]
    assert not control.held


def test_close_releases_held_movement(controller):
    control, backend, _ = controller
    control.enable()
    thread = threading.Thread(target=control.execute, args=(Action("left", 0.24),))
    thread.start()
    assert backend.down.wait(1)
    control.close()
    thread.join(1)
    assert backend.events[-1] == ("left", False)
    assert not control.held


def test_watchdog_caps_held_key_even_if_action_thread_stalls(controller):
    control, backend, _ = controller
    control.enable()
    with control.lock:
        control.held["right"] = time.perf_counter() + 0.02
        backend.send("right", True)
    assert backend.released.wait(0.15)
    assert not control.held


def test_overlapping_keys_release_independently_and_backend_can_be_replaced():
    backend = Backend()
    control = KeyboardController(
        backend, InputConfig(), lambda: True, lambda: False, timing=TimingConfig(enabled=False)
    )
    try:
        control.enable()
        control.execute_sequence([KeyHold("right", 0.10), KeyHold("jump", 0.03, 0.02)])
        assert backend.events == [
            ("right", True),
            ("space", True),
            ("space", False),
            ("right", False),
        ]
        assert not control.held
        assert len(control.timing_snapshot()["events"]) == 4
    finally:
        control.close()


def test_stop_during_reaction_delay_prevents_every_key_down():
    backend = Backend()
    control = KeyboardController(
        backend,
        InputConfig(),
        lambda: True,
        lambda: False,
        timing=TimingConfig(reaction_min_seconds=0.15, reaction_max_seconds=0.15),
    )
    try:
        control.enable()
        thread = threading.Thread(target=control.execute, args=(Action("right", 0.05),))
        thread.start()
        time.sleep(0.02)
        control.stop("test stop during reaction")
        thread.join(1)
        assert not thread.is_alive()
        assert backend.events == []
    finally:
        control.close()


def test_explicit_release_does_not_release_other_overlapping_key():
    backend = Backend()
    control = KeyboardController(
        backend, InputConfig(), lambda: True, lambda: False, timing=TimingConfig(enabled=False)
    )
    try:
        control.enable()
        thread = threading.Thread(
            target=control.execute_sequence,
            args=([KeyHold("right", 0.2), KeyHold("jump", 0.1, 0.02)],),
        )
        thread.start()
        deadline = time.perf_counter() + 1
        while ("space", True) not in backend.events:
            assert time.perf_counter() < deadline
            time.sleep(0.002)
        control.release("jump")
        assert "right" in control.held
        thread.join(1)
        assert backend.events == [
            ("right", True),
            ("space", True),
            ("space", False),
            ("right", False),
        ]
    finally:
        control.close()


@pytest.mark.parametrize("emergency", [False, True])
def test_focus_loss_or_emergency_releases_every_overlapping_key(emergency):
    backend = Backend()
    flags = {"safe": True, "emergency": False}
    control = KeyboardController(
        backend,
        InputConfig(),
        lambda: flags["safe"],
        lambda: flags["emergency"],
        timing=TimingConfig(enabled=False),
    )
    try:
        control.enable()
        thread = threading.Thread(
            target=control.execute_sequence,
            args=([KeyHold("right", 0.24), KeyHold("jump", 0.2, 0.02)],),
        )
        thread.start()
        deadline = time.perf_counter() + 1
        while ("space", True) not in backend.events:
            assert time.perf_counter() < deadline
            time.sleep(0.002)
        flags["emergency" if emergency else "safe"] = emergency
        thread.join(0.15)
        assert not thread.is_alive()
        assert ("right", False) in backend.events
        assert ("space", False) in backend.events
        assert not control.held
        assert not control.enabled
    finally:
        control.close()
