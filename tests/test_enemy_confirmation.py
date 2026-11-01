from dataclasses import replace

import pytest

from maplebot.enemy_confirmation import SnailConfirmation, SnailEvidence


def sample(at, **changes):
    return replace(SnailEvidence(str(at), at, "one", "snail", "fh66", 50, 100, .82),
                   **changes)


def tick(confirmer, at, **changes):
    item = sample(at, **changes)
    return confirmer.observe([item], now=at, context="session", frame_id=str(at))["one"]


def test_three_fresh_observations_keep_raw_score_and_require_span():
    confirmer = SnailConfirmation(frozenset({"snail"}))
    assert not tick(confirmer, 0).confirmed
    assert not tick(confirmer, .1).confirmed
    assert not tick(confirmer, .2).confirmed
    result = tick(confirmer, .31)
    assert result.confirmed and result.raw_score == .82
    assert result.provenance == "offline-temporal-snail-candidate"


@pytest.mark.parametrize("changes", [dict(observed=False), dict(ambiguous=True),
                                    dict(live_sprite=False), dict(raw_score=.79),
                                    dict(raw_score=.85), dict(species="loot"),
                                    dict(floor="fh2"), dict(x=500), dict(y=120),
                                    dict(captured_at=-1), dict(raw_score=float("nan"))])
def test_bad_evidence_resets_chain(changes):
    confirmer = SnailConfirmation(frozenset({"snail"}))
    tick(confirmer, 0)
    tick(confirmer, .2)
    assert not tick(confirmer, .4, **changes).confirmed
    assert tick(confirmer, .6).observations == 1


def test_missing_duplicate_context_and_camera_reset():
    confirmer = SnailConfirmation(frozenset({"snail"}))
    tick(confirmer, 0)
    assert confirmer.observe([], now=.1, context="session", frame_id="empty") == {}
    assert tick(confirmer, .2).observations == 1
    assert confirmer.observe([sample(.2)], now=.3, context="session", frame_id="0.2") == {}
    assert tick(confirmer, .4).observations == 1
    result = confirmer.observe([sample(.6)], now=.6, context="new", frame_id="0.6")
    assert result["one"].observations == 1
    assert confirmer.observe([sample(.8)], now=.8, context="new", frame_id="0.8",
                             camera_continuous=False) == {}


def test_window_expiry_and_duplicate_identity():
    confirmer = SnailConfirmation(frozenset({"snail"}))
    tick(confirmer, 0)
    tick(confirmer, .2)
    assert tick(confirmer, 1.3).observations == 1
    result = confirmer.observe([sample(1.5), sample(1.5)], now=1.5,
                               context="session", frame_id="1.5")
    assert result["one"].observations == 0


def test_motion_reversal_needs_new_evidence():
    confirmer = SnailConfirmation(frozenset({"snail"}))
    tick(confirmer, 0, x=50)
    tick(confirmer, .2, x=65)
    assert tick(confirmer, .4, x=50).observations == 0
