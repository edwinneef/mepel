import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from maplebot.config import InputConfig, TimingConfig
from maplebot.decision import Action
from maplebot.input_timing import KeyHold
from maplebot.keyboard import (
    EXTENDED_KEYS,
    KEYS,
    InputObservation,
    KeyboardController,
    Win32Input,
)


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


def test_movement_facing_requires_key_down_and_cancel_preserves_potion(controller):
    control, backend, _ = controller
    control.planner.config = replace(control.planner.config, enabled=False)
    control.enable()
    with control.lock:
        movement = control.submit(Action("right", .25))
        assert control.running_movement(movement) is None
    assert backend.down.wait(1)
    assert control.running_movement(movement) == "right"
    potion = control.submit(Action("hp_potion", .04), priority=1)
    assert control.cancel_movement_plans() == {movement}
    assert control.running_movement(movement) is None
    assert potion not in control.cancelled_tickets
    assert backend.events[:2] == [("right", True), ("right", False)]
    deadline = time.perf_counter() + 1
    while ("insert", False) not in backend.events:
        assert time.perf_counter() < deadline
        time.sleep(.005)
    assert ("insert", True) in backend.events


def test_disabled_input_and_replay_send_no_keys(controller):
    control, backend, _ = controller
    assert control.execute(Action("right", 0.02)).startswith("blocked")
    control.replay = True
    with pytest.raises(RuntimeError, match="Replay"):
        control.enable()
    assert backend.events == []


def test_key_event_clocks_bracket_backend_call_and_keep_relative_time(controller, monkeypatch):
    from types import SimpleNamespace

    from maplebot import keyboard

    control, backend, _ = controller
    clock = [100.25]
    monkeypatch.setattr(keyboard, "time", SimpleNamespace(
        perf_counter=lambda: clock[0], time=lambda: 1800000000.5))
    control.execution_started = 100

    def send(key, down):
        backend.events.append((key, down))
        clock[0] += .02

    monkeypatch.setattr(backend, "send", send)
    with control.lock:
        control._send("right", True)
        control._send("right", False)
    events = control.timing_snapshot()["events"]
    assert [event["down"] for event in events] == [True, False]
    for event in events:
        assert event["clock"] - 100 == pytest.approx(event["at_seconds"])
        assert event["finished_clock"] - event["clock"] == pytest.approx(.02)
        assert event["issued_at"] == 1800000000.5
    assert events[1]["clock"] == events[0]["finished_clock"]


def test_failed_backend_call_is_not_recorded_as_a_sent_event(controller, monkeypatch):
    control, backend, _ = controller

    def fail(key, down):
        raise OSError("test backend rejected event")

    monkeypatch.setattr(backend, "send", fail)
    with pytest.raises(OSError):
        control._send("right", True)
    assert control.timing_snapshot()["events"] == []
    assert control.timing_snapshot()["history"] == []
    assert control.event_sequence == 0


def test_event_history_survives_plans_without_draining_or_exposing_mutable_state(controller):
    control, _, _ = controller
    control.planner.config = TimingConfig(enabled=False)
    control.enable()
    for action in ("right", "left", "jump"):
        control.execute(Action(action, .01))
    snapshot = control.timing_snapshot()
    assert len(snapshot["events"]) == 2
    assert [e["sequence"] for e in snapshot["history"]] == list(range(1, 7))
    assert len(control.timing_snapshot()["history"]) == 6
    snapshot["history"][0]["key"] = "changed"
    snapshot["events"].clear()
    assert control.timing_snapshot()["history"][0]["key"] == "right"
    assert len(control.timing_snapshot()["events"]) == 2


def test_event_history_has_a_fixed_bound_and_reports_evictions(controller):
    from maplebot.keyboard import EVENT_HISTORY_LIMIT

    control, _, _ = controller
    with control.lock:
        for _ in range(EVENT_HISTORY_LIMIT + 4):
            control.last_timing = {"events": []}
            control._send("right", True)
    snapshot = control.timing_snapshot()
    assert len(snapshot["history"]) == snapshot["history_limit"] == EVENT_HISTORY_LIMIT
    assert snapshot["history_dropped"] == 4
    assert snapshot["history"][0]["sequence"] == 5
    assert snapshot["history"][-1]["sequence"] == snapshot["history_last_sequence"]


def test_stop_retains_history_including_physical_release_request(controller):
    control, _, _ = controller
    control.enable()
    history_id = control.timing_snapshot()["history_id"]
    control.refresh_movement("right", .25)
    control.stop(notify=False)
    snapshot = control.timing_snapshot()
    assert snapshot["history_id"] == history_id
    assert all(e["history_id"] == history_id for e in snapshot["history"])
    assert [(e["key"], e["down"]) for e in snapshot["history"]] == [
        ("right", True), ("right", False)]
    assert not control.held and not control.enabled


def test_new_controller_gets_a_distinct_history_id(controller):
    import uuid

    control, _, _ = controller
    other = KeyboardController(Backend(), InputConfig(), lambda: True, lambda: False)
    try:
        first = control.timing_snapshot()["history_id"]
        second = other.timing_snapshot()["history_id"]
        assert first != second and uuid.UUID(hex=first).hex == first
        assert uuid.UUID(hex=second).hex == second
    finally:
        other.close()


def test_repeated_movement_renewals_do_not_repress_the_key(controller):
    control, backend, _ = controller
    control.enable()
    for _ in range(8):
        assert control.refresh_movement("right", .25) == "held: right"
    assert backend.events == [("right", True)]
    control.release_movement()
    assert backend.events == [("right", True), ("right", False)]


def test_navigation_jump_preserves_up_and_horizontal_holds(controller):
    control, backend, _ = controller
    control.enable()
    lease = control.start_vertical_lease("up")
    assert control.refresh_movement("right", .25, navigation=True) == "held: right"
    ticket = control.submit_sequence((KeyHold("jump", .02),), preserve_movement=True)
    deadline = time.monotonic() + 1
    outcomes = []
    while not outcomes and time.monotonic() < deadline:
        outcomes = control.poll_outcomes()
        time.sleep(.001)
    assert outcomes and outcomes[0].ticket == ticket
    assert (control.config.jump, True) in backend.events
    assert (control.config.jump, False) in backend.events
    assert ("up", False) not in backend.events and ("right", False) not in backend.events
    assert control.renew_vertical_lease(lease)
    control.release_all()
    assert backend.events.count(("up", True)) == backend.events.count(("up", False)) == 1


def test_suspension_releases_and_blocks_all_input_until_explicit_resume(controller):
    control, backend, _ = controller
    control.enable()
    control.refresh_movement("right", .25)
    assert control.suspend()
    assert backend.events == [("right", True), ("right", False)]
    assert control.submit(Action("jump", .02)).startswith("blocked")
    assert control.submit_sequence((KeyHold("jump", .02),)).startswith("blocked")
    assert control.refresh_movement("left", .25).startswith("blocked")
    with pytest.raises(RuntimeError):
        control.start_vertical_lease("up")
    with pytest.raises(RuntimeError):
        control.enable()
    assert control.resume()
    assert backend.events == [("right", True), ("right", False)]  # Resume itself sends no key.


def test_focus_watchdog_remains_active_while_input_is_suspended(controller):
    control, _, flags = controller
    control.enable()
    assert control.suspend()
    flags["focus"] = False
    assert control.stopped.wait(.15)
    assert not control.enabled and not control.resume()


def test_preserving_input_is_restricted_to_jump(controller):
    control, _, _ = controller
    control.enable()
    with pytest.raises(ValueError, match="Only a navigation jump"):
        control.submit_sequence((KeyHold("attack", .02),), preserve_movement=True)


def test_canceled_old_plan_cannot_release_a_new_movement_hold(controller):
    from maplebot.keyboard import _QueuedPlan

    control, backend, _ = controller
    control.enable()
    old = _QueuedPlan(123, control.generation, "navigation",
                      control.planner.plan((KeyHold("jump", .02),)), time.perf_counter())
    assert control.suspend() and control.resume()
    control.refresh_movement("right", .25)
    assert control._execute_schedule(old).endswith("interrupted")
    assert backend.events == [("right", True)]


def test_expired_vertical_lease_cannot_enter_resumable_suspension(controller):
    control, _, _ = controller
    control.enable()
    lease = control.start_vertical_lease("up")
    control.release_vertical_lease(lease)
    assert not control.suspend(lease=lease)


def test_movement_renewal_keeps_one_keydown_and_expires_without_another_frame(controller):
    control, backend, _ = controller
    control.enable()
    assert control.refresh_movement("right", .2) == "held: right"
    first_deadline = control.held[control.config.right]
    time.sleep(.05)
    assert control.refresh_movement("right", .2) == "held: right"
    assert control.held[control.config.right] > first_deadline
    assert backend.events == [(control.config.right, True)]
    assert backend.released.wait(.5)
    assert backend.events == [(control.config.right, True), (control.config.right, False)]
    assert not control.held and control.movement_key is None


def test_expired_movement_is_released_before_a_new_hold(controller):
    control, backend, _ = controller
    control.enable()
    with control.lock:
        control.refresh_movement("right", .25)
        control.held[control.config.right] = time.perf_counter() - 1
        control.refresh_movement("right", .25)
        assert backend.events == [("right", True), ("right", False), ("right", True)]


def test_movement_direction_change_releases_before_pressing_and_stop_cannot_renew(controller):
    control, backend, _ = controller
    control.enable()
    control.refresh_movement("left", .25)
    control.refresh_movement("right", .25)
    control.stop("F8", notify=False)
    assert control.refresh_movement("right", .25).startswith("blocked")
    assert backend.events == [("left", True), ("left", False),
                              ("right", True), ("right", False)]


@pytest.mark.parametrize("flag", ["focus", "emergency"])
def test_movement_refresh_rechecks_focus_and_emergency(controller, flag):
    control, backend, flags = controller
    control.enable()
    control.refresh_movement("left", .25)
    flags[flag] = flag == "emergency"
    assert control.refresh_movement("left", .25).startswith("blocked")
    assert backend.released.wait(.5)
    assert not control.enabled


@pytest.mark.parametrize("action,seconds", [("attack", .2), ("left", .251),
                                           ("left", float("nan")), ("left", 0)])
def test_movement_refresh_preserves_action_and_duration_limits(controller, action, seconds):
    control, backend, _ = controller
    control.enable()
    with pytest.raises(ValueError, match="bounded"):
        control.refresh_movement(action, seconds)
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


@pytest.fixture
def observation_clock(controller, monkeypatch):
    from maplebot import keyboard

    control, backend, _ = controller
    # Stop background threads; drive the real queue/schedule with a deterministic clock.
    control.close()
    while not control.queue.empty():
        control.queue.get_nowait()
    clock = [100.1]
    source = [InputObservation(100., 100.5, 1, 2, 3)]
    monkeypatch.setattr(keyboard, "time", SimpleNamespace(
        perf_counter=lambda: clock[0], time=lambda: 1800000000. + clock[0]))

    def wait(seconds):
        clock[0] += max(0, seconds)
        return control.stopped.is_set()

    monkeypatch.setattr(control.stopped, "wait", wait)
    control.observation = lambda: source[0]
    control.planner.config = TimingConfig(enabled=False)
    control.enable()
    return control, backend, clock, source


def queued_plan(control):
    return control.queue.get_nowait()[2]


def test_reaction_delay_cannot_dispatch_from_expired_originating_frame(observation_clock):
    control, backend, clock, _ = observation_clock
    clock[0] = 100.49
    control.planner.config = TimingConfig(reaction_min_seconds=.025, reaction_max_seconds=.025,
                                          rest_min_seconds=0, rest_max_seconds=0)
    ticket = control.submit(Action("attack", .06))
    item = queued_plan(control)
    assert item.ticket == ticket and item.observation.capture_clock == 100.
    assert control._execute_schedule(item) == "attack interrupted"
    assert clock[0] == pytest.approx(100.515)
    assert backend.events == [] and not control.held and not control.enabled
    assert "observation expired" in control.reason


def test_newer_frame_cannot_renew_an_expired_queued_plan(observation_clock):
    control, backend, clock, source = observation_clock
    control.submit(Action("right", .1))
    item = queued_plan(control)
    clock[0] = 100.51
    source[0] = replace(source[0], capture_clock=100.4, deadline=100.9, sequence=4)
    result = control._execute_schedule(item)
    control._finish(item, result, clock[0])
    outcome = control.poll_outcomes()[0]
    assert result == "right interrupted" and backend.events == []
    assert outcome.observation.sequence == 3 and outcome.observation.deadline == 100.5


@pytest.mark.parametrize("field", ["source_generation", "view_generation"])
def test_queued_plan_rejects_changed_source_or_view(observation_clock, field):
    control, backend, _, source = observation_clock
    control.submit_sequence((KeyHold("jump", .03),))
    item = queued_plan(control)
    source[0] = replace(source[0], **{field: getattr(source[0], field) + 1})
    assert control._execute_schedule(item) == "navigation interrupted"
    assert backend.events == [] and not control.held


@pytest.mark.parametrize("captured,deadline", [(-1., -1.), (float("nan"), 100.5),
                                              (99., 99.5), (101., 101.5)])
def test_invalid_current_observation_rejects_old_plan_and_releases_hold(
        observation_clock, captured, deadline):
    control, backend, _, source = observation_clock
    control.refresh_movement("left", .2)
    control.submit(Action("attack", .05))
    item = queued_plan(control)
    source[0] = replace(source[0], capture_clock=captured, deadline=deadline)
    assert control._execute_schedule(item) == "attack interrupted"
    assert backend.events == [("left", True), ("left", False)]
    assert not control.held and not control.enabled


def test_sequence_regression_cannot_authorize_queued_plan(observation_clock):
    control, backend, _, source = observation_clock
    control.submit(Action("right", .1))
    item = queued_plan(control)
    source[0] = replace(source[0], sequence=source[0].sequence - 1)
    assert control._execute_schedule(item) == "right interrupted"
    assert backend.events == [] and not control.held


def test_expiry_between_chord_downs_releases_first_key(observation_clock):
    control, backend, clock, _ = observation_clock
    clock[0] = 100.48
    control.submit_sequence((KeyHold("right", .1), KeyHold("jump", .05, .04)))
    assert control._execute_schedule(queued_plan(control)) == "navigation interrupted"
    assert backend.events == [("right", True), ("right", False)]
    assert not control.held


def test_key_up_still_runs_after_observation_deadline(observation_clock):
    control, backend, clock, _ = observation_clock
    clock[0] = 100.48
    ticket = control.submit(Action("attack", .1))
    item = queued_plan(control)
    assert control._execute_schedule(item) == "attack completed"
    assert backend.events == [("z", True), ("z", False)] and not control.held
    events = control.timing_snapshot()["events"]
    assert events[0]["capture_age_ms"] == pytest.approx(480)
    assert events[1]["capture_age_ms"] == pytest.approx(580)
    assert all(e["ticket"] == ticket and e["observation"]["sequence"] == 3 for e in events)


def test_fresh_priority_potion_precedes_stale_combat_without_rebinding_it(observation_clock):
    control, backend, clock, source = observation_clock
    old = control.submit(Action("attack", .1))
    source[0] = replace(source[0], capture_clock=100.4, deadline=100.9, sequence=4)
    clock[0] = 100.51
    potion = control.submit(Action("hp_potion", .02), priority=1)
    item = queued_plan(control)
    assert item.ticket == potion
    assert control._execute_schedule(item) == "hp_potion completed"
    item = queued_plan(control)
    assert item.ticket == old
    assert control._execute_schedule(item) == "attack interrupted"
    assert backend.events == [("insert", True), ("insert", False)]


def test_stop_cancels_bound_plan_without_late_down_or_lost_origin(observation_clock):
    control, backend, _, _ = observation_clock
    ticket = control.submit(Action("right", .1))
    control.stop("operator stop")
    outcome = control.poll_outcomes()[0]
    assert outcome.ticket == ticket and outcome.started_at is None
    assert outcome.observation.capture_clock == 100.
    assert outcome.result == "right interrupted" and backend.events == []


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
