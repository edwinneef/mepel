import threading
import time
from dataclasses import replace

import pytest

from maplebot.config import InputConfig, TimingConfig
from maplebot.decision import Action
from maplebot.input_timing import KeyHold
from maplebot.keyboard import EXTENDED_KEYS, KEYS, KeyboardController, Win32Input


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


def test_alt_jump_is_supported_and_released():
    backend = Backend()
    control = KeyboardController(
        backend, replace(InputConfig(), jump="alt"), lambda: True, lambda: False
    )
    try:
        assert KEYS["alt"] == 0xA4
        assert Win32Input.flags_for("alt", True) == 0x0008
        assert Win32Input.flags_for("alt", False) == 0x000A
        control.enable()
        assert control.execute(Action("jump", 0.02)) == "jump completed"
        assert backend.events == [("alt", True), ("alt", False)]
        assert not control.held
    finally:
        control.close()


def test_single_probe_disables_input_before_publishing_completion(controller):
    control, backend, flags = controller
    stops = []
    control.on_stop = lambda code, reason: stops.append(code)
    control.enable()
    ticket = control.submit(Action("left", 0.02), disable_after=True)
    deadline = time.perf_counter() + 2
    outcomes = []
    while not outcomes:
        outcomes = control.poll_outcomes()
        assert time.perf_counter() < deadline
        time.sleep(0.002)
    assert outcomes[0].ticket == ticket
    assert outcomes[0].result == "left completed"
    assert not control.enabled
    assert not control.held
    flags["focus"] = False
    time.sleep(0.03)
    assert stops == []
    assert backend.events == [("left", True), ("left", False)]
    assert control.submit(Action("right", 0.02)) == "blocked: input disabled"


@pytest.mark.parametrize("key", sorted(EXTENDED_KEYS))
def test_navigation_keys_use_extended_flags_for_down_and_up(key):
    assert Win32Input.flags_for(key, True) & 0x0001
    assert Win32Input.flags_for(key, False) & 0x0001


@pytest.mark.parametrize("key", ["a", "1", "space"])
def test_ordinary_keys_do_not_use_extended_flags(key):
    assert not Win32Input.flags_for(key, True) & 0x0001
    assert not Win32Input.flags_for(key, False) & 0x0001


def test_short_press_releases_and_duration_limit_blocks(controller):
    control, backend, _ = controller
    control.enable()
    control.execute(Action("right", 0.02))
    assert backend.events == [("right", True), ("right", False)]
    assert control.execute(Action("attack", 3)) == "blocked: duration"
    assert len(backend.events) == 2
    assert not control.held


def test_submit_returns_before_hold_completes_and_reports_terminal_outcome(controller):
    control, backend, _ = controller
    control.enable()
    started = time.perf_counter()
    ticket = control.submit(Action("right", 0.25))
    assert isinstance(ticket, int)
    assert time.perf_counter() - started < 0.05
    assert backend.down.wait(1)
    assert control.poll_outcomes() == []
    deadline = time.perf_counter() + 1
    outcomes = []
    while not outcomes:
        outcomes = control.poll_outcomes()
        assert time.perf_counter() < deadline
        time.sleep(0.002)
    outcome = outcomes[0]
    assert outcome.ticket == ticket
    assert outcome.action == "right"
    assert outcome.result == "right completed"
    assert outcome.started_at is not None
    assert outcome.finished_at is not None
    assert outcome.finished_at >= outcome.started_at >= outcome.submitted_at


def test_stop_cancels_queued_and_active_submissions_without_later_key_down():
    backend = Backend()
    control = KeyboardController(
        backend, InputConfig(), lambda: True, lambda: False, timing=TimingConfig(enabled=False)
    )
    try:
        control.enable()
        first = control.submit(Action("right", 0.25))
        second = control.submit(Action("jump", 0.05))
        assert backend.down.wait(1)
        control.stop("test stop")
        deadline = time.perf_counter() + 1
        outcomes = []
        while len(outcomes) < 2:
            outcomes.extend(control.poll_outcomes())
            assert time.perf_counter() < deadline
            time.sleep(0.002)
        assert {item.ticket for item in outcomes} == {first, second}
        assert all(item.result.endswith("interrupted") for item in outcomes)
        assert backend.events == [("right", True), ("right", False)]
    finally:
        control.close()


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


def test_vertical_lease_renews_only_before_expiry_and_respects_total_cap():
    backend = Backend()
    config = InputConfig(vertical_lease_seconds=0.03, vertical_lease_max_seconds=0.06)
    control = KeyboardController(backend, config, lambda: True, lambda: False)
    try:
        control.enable()
        lease = control.start_vertical_lease("up")
        time.sleep(0.01)
        assert control.renew_vertical_lease(lease)
        time.sleep(0.06)
        assert not control.renew_vertical_lease(lease)
        assert backend.events == [("up", True), ("up", False)]
        assert not control.release_vertical_lease(lease)
    finally:
        control.close()


def test_vertical_lease_rejects_non_vertical_actions_and_empty_operations(controller):
    control, backend, _ = controller
    control.enable()
    with pytest.raises(ValueError, match="up/down"):
        control.start_vertical_lease("right")
    assert not control.renew_vertical_lease(404)
    assert not control.release_vertical_lease(404)
    assert backend.events == []


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
