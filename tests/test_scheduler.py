import heapq
import time

import pytest
from test_keyboard import Backend

from maplebot.config import InputConfig, TimingConfig
from maplebot.decision import Action
from maplebot.keyboard import PRIORITY_HP, KeyboardController
from maplebot.scheduler import Arbiter


class FakeController:
    """The controller's ordering on a fake clock: one active plan, a priority queue."""

    def __init__(self):
        self.now, self.ticket, self.queue = 0.0, 0, []
        self.active: tuple[float, int, str] | None = None
        self.log: list[tuple[float, str]] = []

    def submit(self, action, priority):
        self.ticket += 1
        heapq.heappush(self.queue, (priority, self.ticket, action))
        return self.ticket

    def stop(self):
        finished = [ticket for _, ticket, _ in self.queue]
        self.queue.clear()
        if self.active:
            finished.append(self.active[1])
            self.active = None
        return finished

    def advance(self, until):
        """Run plans until the fake time; return finished tickets."""
        finished = []
        while True:
            if self.active is None and self.queue:
                _, ticket, action = heapq.heappop(self.queue)
                self.active = (self.now + action.seconds, ticket, action.kind)
                self.log.append((round(self.now, 3), action.kind))
            if self.active is None or self.active[0] > until:
                break
            self.now, ticket, _ = self.active
            finished.append(ticket)
            self.active = None
        self.now = until
        return finished


def replay(frames, period=0.3):
    arbiter, control = Arbiter(0.06), FakeController()
    reasons = []
    for index, (sustain, combat, stop) in enumerate(frames):
        for ticket in control.advance(index * period):
            arbiter.finished(ticket)
        if stop:
            for ticket in control.stop():
                arbiter.finished(ticket)
            arbiter.reset()
            reasons.append("stopped")
            continue
        choice = arbiter.choose(sustain=sustain, combat=combat)
        reasons.append(choice.reason)
        if choice.action is not None and choice.lane is not None:
            arbiter.submitted(control.submit(choice.action, choice.priority), choice.lane)
    control.advance(len(frames) * period)
    return control.log, reasons


def test_fake_clock_replay_puts_hp_then_mp_ahead_of_combat_and_stop_clears_all():
    walk, attack = Action("right", 0.25), Action("attack", 0.2)
    log, reasons = replay([
        (None, walk, False),
        ("hp", walk, False),
        (None, attack, False),
        ("mp", attack, False),
        (None, attack, False),
        (None, walk, True),
        (None, attack, False),
    ])
    assert [kind for _, kind in log] == [
        "right", "hp_potion", "attack", "mp_potion", "attack", "attack",
    ]
    assert reasons[1] == "HP potion precedes combat"
    assert reasons[3] == "MP potion precedes combat"
    assert reasons[5] == "stopped" and reasons[6] == "Combat key"


def test_combat_waits_while_a_potion_is_in_flight():
    arbiter = Arbiter(0.06)
    arbiter.submitted(7, "hp")
    choice = arbiter.choose(sustain=None, combat=Action("attack", 0.2))
    assert choice.action is None and choice.reason == "Combat waits for the potion key"
    assert arbiter.finished(7) == "hp"
    assert arbiter.choose(sustain=None, combat=Action("attack", 0.2)).lane == "combat"
    assert arbiter.choose(sustain=None, combat=Action()).lane is None
    with pytest.raises(ValueError, match="Unknown sustain"):
        arbiter.choose(sustain="pet", combat=None)


def test_controller_runs_queued_potion_before_earlier_queued_combat():
    backend = Backend()
    control = KeyboardController(
        backend, InputConfig(), lambda: True, lambda: False, timing=TimingConfig(enabled=False)
    )
    try:
        control.enable()
        control.submit(Action("right", 0.2))
        assert backend.down.wait(1)
        control.submit(Action("attack", 0.02))
        potion = control.submit(Action("hp_potion", 0.02), priority=PRIORITY_HP)
        deadline = time.perf_counter() + 2
        done = []
        while len(done) < 3:
            done.extend(control.poll_outcomes())
            assert time.perf_counter() < deadline
            time.sleep(0.002)
        assert [item.action for item in done] == ["right", "hp_potion", "attack"]
        assert done[1].ticket == potion and done[1].result == "hp_potion completed"
        config = InputConfig()
        assert [key for key, down in backend.events if down] == [
            config.right, config.hp_potion, config.attack,
        ]
    finally:
        control.close()


def test_stop_cancels_a_queued_potion_too():
    backend = Backend()
    control = KeyboardController(
        backend, InputConfig(), lambda: True, lambda: False, timing=TimingConfig(enabled=False)
    )
    try:
        control.enable()
        control.submit(Action("right", 0.25))
        assert backend.down.wait(1)
        potion = control.submit(Action("hp_potion", 0.02), priority=PRIORITY_HP)
        control.stop("test stop", notify=False)
        deadline = time.perf_counter() + 1
        done = []
        while len(done) < 2:
            done.extend(control.poll_outcomes())
            assert time.perf_counter() < deadline
            time.sleep(0.002)
        assert next(item for item in done if item.ticket == potion).result.endswith("interrupted")
        assert [key for key, down in backend.events if down] == [InputConfig().right]
    finally:
        control.close()
