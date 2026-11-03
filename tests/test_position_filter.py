import pytest

from maplebot.position_filter import PositionFilter


def sample(tracker, now, x=10., **changes):
    values = dict(point=(x, 20.), identity="nametag:own", confidence=1., now=now,
                  context=("map", 1, "floor"), fresh=True)
    return tracker.update(**(values | changes))


def confirmed():
    tracker = PositionFilter()
    sample(tracker, 0.)
    sample(tracker, .1)
    assert sample(tracker, .2)["fresh"]
    return tracker


def test_three_consecutive_matches_publish_smoothed_estimate():
    tracker = PositionFilter()
    assert sample(tracker, 0., 10.)["feet"] is None
    assert sample(tracker, .1, 14.)["feet"] is None
    result = sample(tracker, .2, 10.)
    assert result["fresh"] and result["feet"] == [11., 20.]
    assert result["observed_clock"] == .2


@pytest.mark.parametrize("changes", [dict(fresh=False), dict(identity=None),
                                    dict(confidence=.89), dict(confidence=float("nan")),
                                    dict(point=(float("inf"), 0.))])
def test_uncertain_frame_resets_confirmation_and_only_holds_decaying_estimate(changes):
    tracker = confirmed()
    result = sample(tracker, .4, **changes)
    assert not result["fresh"] and result["held"]
    assert result["feet"] == [10., 20.] and result["confidence"] == pytest.approx(.8)
    assert result["observed_clock"] == .2
    assert not sample(tracker, .5)["fresh"]
    assert not sample(tracker, .6)["fresh"]
    assert sample(tracker, .7)["fresh"]


def test_dropouts_do_not_extend_hold_lifetime():
    tracker = confirmed()
    assert sample(tracker, .8, fresh=False)["confidence"] == pytest.approx(.4)
    result = sample(tracker, 1.21, fresh=False)
    assert not result["fresh"] and not result["held"] and result["feet"] is None
    assert result["observed_clock"] == .2


@pytest.mark.parametrize("changes", [dict(identity="nametag:other"),
                                    dict(context=("other-map", 1, "floor")),
                                    dict(context=("map", 2, "floor")),
                                    dict(context=("map", 1, "other-floor"))])
def test_identity_or_coordinate_basis_change_clears_old_estimate(changes):
    result = sample(confirmed(), .3, **changes)
    assert not result["fresh"] and result["feet"] is None
    assert result["consecutive"] == 1


def test_gap_duplicate_and_backwards_clock_cannot_satisfy_streak():
    tracker = PositionFilter()
    sample(tracker, 0.)
    assert not sample(tracker, .6)["fresh"]
    assert sample(tracker, .6)["consecutive"] == 0
    assert sample(tracker, .5)["consecutive"] == 1
