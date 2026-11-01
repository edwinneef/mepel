from dataclasses import replace

import pytest

from maplebot.floor_search import FloorSearch, SearchEvidence


def evidence(frame, **changes):
    return replace(SearchEvidence(frame, float(frame), .1, True, False, True,
                                  True, True, "left", True, 100, 20, 5, 100), **changes)


@pytest.mark.parametrize("direction", ["left", "right"])
def test_two_scans_release_reobserve_and_bounded_episode(direction):
    search = FloorSearch(15)
    assert search.propose(evidence(1, direction=direction)) == 0
    assert search.propose(evidence(1, direction=direction)) == 0
    assert search.propose(evidence(2, input_idle=False)) == 0
    assert search.propose(evidence(3, released=False)) == 0
    for frame in range(4, 8):
        assert search.propose(evidence(frame, direction=direction)) == .24
    assert search.propose(evidence(8)) == 0
    assert search.closed and search.seconds == .96


@pytest.mark.parametrize("changes", [
    {"corridor_proven": False}, {"clearance": 49}, {"stopping_margin": 0},
    {"speed_bound": 0}, {"uncertainty": -1}, {"direction": "up"},
])
def test_unproven_or_edge_movement_is_refused(changes):
    search = FloorSearch(15)
    search.propose(evidence(1))
    assert search.propose(evidence(2, **changes)) == 0
    assert search.pulses == 0


@pytest.mark.parametrize("changes", [
    {"target": True}, {"safe": False}, {"age": .51}, {"now": float("nan")},
])
def test_target_or_safety_loss_closes_episode(changes):
    search = FloorSearch(15)
    search.propose(evidence(1))
    assert search.propose(evidence(2, **changes)) == 0
    assert search.propose(evidence(3)) == 0
    assert search.closed


def test_search_does_not_extend_combat_deadline():
    search = FloorSearch(2.2)
    search.propose(evidence(1))
    assert search.propose(evidence(2)) == 0
    assert search.deadline == 2.2 and search.closed
