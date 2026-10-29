import pytest
from test_runtime import app as _app

from maplebot.decision import Action
from maplebot.farming import Farming

app = _app


def readings(hp=80, mp=80):
    return {r: {"percent": value, "confidence": 1} for r, value in (("hp", hp), ("mp", mp))}


def test_interval_requires_explicit_configuration():
    for value in (None, True, 0, float("nan"), 3601):
        with pytest.raises(ValueError, match="feed_seconds"):
            Farming({"feed_seconds": value})


def test_pet_recovery_deadline_resets_only_above_threshold():
    farm = Farming({"feed_seconds": 60})
    farm.start(0)
    assert farm.check(1, readings(hp=40), True) is None
    assert farm.check(5, readings(hp=49), True) is None
    assert "HP recovery failed" in farm.check(6, readings(hp=50), True)
    assert farm.check(7, readings(), True) is None
    assert farm.check(8, readings(hp=40), True) is None
    assert "MP recovery failed" in (farm.check(8, readings(mp=40), True)
                                   or farm.check(13, readings(mp=40), True))


def test_stop_conditions():
    farm = Farming({"feed_seconds": 60})
    farm.start(10)
    assert farm.check(909, readings(), True) is None
    assert "session limit" in farm.check(910, readings(), True)
    assert "possible death" in farm.check(11, readings(hp=0), True)
    assert "unavailable" in farm.check(11, readings(), False)
    assert "unreadable" in farm.check(11, {}, True)


def test_farming_disables_bot_potions_and_stop_clears_session(app):
    app.farming = Farming({"feed_seconds": 60})
    app.sustain = ("hp", "mp")
    app._start_sustain()
    assert app.sustain == () and not app.potter.enabled
    assert app.farming.started is not None
    app._stop("POLICY_STOP", "test session stop")
    assert app.farming is None and app.sustain == ()
    assert app.controller.stopped.is_set()


def test_feeding_waits_for_combat_and_queues_once(app):
    app.farming = Farming({"feed_seconds": 60})
    app._start_sustain()
    app.farming.next_feed = 0
    app.arbiter.submitted(100, "combat")
    assert app._arbitrate(Action("attack", .1), "hp") == "deferred: waiting to feed pet"
    app.arbiter.finished(100)
    app.controller.enable()
    assert "pet food queued" in app._arbitrate(Action("attack", .1), "mp")
    ticket = app.farming.feed_ticket
    assert app.arbiter.in_flight[ticket] == "pet_food"
    assert app._arbitrate(Action("attack", .1), None) == "deferred: pet food in flight"
