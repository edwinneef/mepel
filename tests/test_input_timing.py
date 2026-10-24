import random

import pytest

from maplebot.config import InputConfig, TimingConfig
from maplebot.input_timing import KeyHold, TimingPlanner, direction_then_jump, down_then_jump


def planner(profile=None, seed=71):
    return TimingPlanner(InputConfig(), profile or TimingConfig(), random.Random(seed))


def test_repeated_actions_have_bounded_varied_holds_and_intervals():
    timing = planner()
    schedules = [timing.plan([KeyHold("attack", 0.06)]) for _ in range(20)]
    holds = [item.events[1].at_seconds - item.events[0].at_seconds for item in schedules]
    starts = [item.events[0].at_seconds for item in schedules]
    rests = [item.rest_seconds for item in schedules]
    assert len(set(holds)) > 1
    assert len(set(starts)) > 1
    assert len(set(rests)) > 1
    assert all(0.048 <= duration <= 0.072 for duration in holds)
    assert all(0.025 <= delay <= 0.085 for delay in starts)
    assert all(0.020 <= delay <= 0.065 for delay in rests)


def test_seeded_profile_is_repeatable_and_disabled_profile_is_exact():
    holds = [KeyHold("right", 0.18), KeyHold("jump", 0.06, 0.04)]
    assert planner(seed=8).plan(holds) == planner(seed=8).plan(holds)
    schedule = planner(TimingConfig(enabled=False)).plan(holds)
    assert [(event.key, event.down, event.at_seconds) for event in schedule.events] == [
        ("right", True, 0),
        ("space", True, 0.04),
        ("space", False, 0.1),
        ("right", False, 0.18),
    ]
    assert schedule.rest_seconds == 0


def test_simultaneous_requests_are_staggered_but_compatible_holds_overlap():
    schedule = planner().plan([KeyHold("right", 0.18), KeyHold("jump", 0.06)])
    downs = [event for event in schedule.events if event.down]
    assert downs[1].at_seconds - downs[0].at_seconds >= 0.012
    right_up = next(event for event in schedule.events if event.key == "right" and not event.down)
    assert downs[1].at_seconds < right_up.at_seconds


@pytest.mark.parametrize(
    "holds",
    [
        [KeyHold("left", 0.15), KeyHold("right", 0.1, 0.04)],
        [KeyHold("attack", 0.15), KeyHold("attack", 0.1, 0.04)],
        [KeyHold("jump", 0.1, -0.02)],
        [KeyHold("attack", float("nan"))],
        [KeyHold("right", 0.2, 0.1)],
        [KeyHold("attack", 3)],
    ],
)
def test_invalid_or_conflicting_sequences_are_rejected(holds):
    with pytest.raises(ValueError):
        planner().plan(holds)


def test_variation_cannot_extend_sequence_beyond_safety_budget():
    timing = planner()
    for _ in range(100):
        schedule = timing.plan([KeyHold("right", 0.25), KeyHold("jump", 0.06, 0.04)])
        assert (
            max(event.at_seconds for event in schedule.events) - schedule.delay_seconds
            <= 0.25 + 1e-9
        )


def test_ordered_chords_keep_required_down_order_across_seeded_jitter():
    for seed in range(1_000):
        timing = planner(seed=seed)
        for holds, first in ((down_then_jump(), "down"), (direction_then_jump("right"), "right")):
            downs = [event.action for event in timing.plan(holds).events if event.down]
            assert downs.index(first) < downs.index("jump")


def test_direction_then_jump_rejects_non_direction():
    with pytest.raises(ValueError, match="left or right"):
        direction_then_jump("up")


@pytest.mark.parametrize(
    "settings",
    [
        {"hold_variation": -0.1},
        {"hold_variation": 1.1},
        {"reaction_min_seconds": 0.1, "reaction_max_seconds": 0.01},
        {"rest_min_seconds": -0.1},
        {"offset_variation_seconds": float("inf")},
        {"key_stagger_seconds": 0},
    ],
)
def test_invalid_timing_configuration_rejected(settings):
    with pytest.raises(ValueError):
        TimingConfig(**settings)
