import pytest
from test_runtime import app as _app

from maplebot.decision import Action
from maplebot.farming import Farming

app = _app


def readings(hp=80, mp=80):
    return {r: {"percent": value, "confidence": 1} for r, value in (("hp", hp), ("mp", mp))}


def test_interval_requires_explicit_configuration():
    for value in (True, 0, float("nan"), 3601):
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


def test_optional_food_and_three_fps_stall_deadline():
    farm = Farming({"pet_recovery": False})
    farm.start(0)
    assert farm.next_feed is None
    for frame in range(45):
        assert farm.progress(frame / 3, active=False) is None
    assert "no combat progress" in farm.progress(15, active=False)
    assert farm.progress(15, active=True) is None
    assert farm.progress(29, active=False) is None


def test_no_pet_uses_existing_verified_potion_lane(app):
    app.farming = Farming({"pet_recovery": False})
    app.potter.bars = {"hp": object(), "mp": object()}
    app.probed.update({"hp_potion", "mp_potion"})
    app._start_sustain()
    assert app.sustain == ("hp", "mp")
    assert app.potter.enabled


def test_crowded_ambiguous_targets_stop_instead_of_waiting_forever():
    from maplebot.config import AgentConfig
    from maplebot.decision import Agent
    from maplebot.geometry import Rect
    from maplebot.perception import Detection, Observation
    agent = Agent(AgentConfig())
    agent.start()
    player = Detection("player", Rect(100, 100, 24, 28), .99)
    monsters = [Detection("monster", Rect(x, 100, 24, 28), .99) for x in (140, 144)]
    observation = Observation(player, monsters)
    farm = Farming({"pet_recovery": False})
    farm.start(0)
    for frame in range(46):
        now = frame / 3
        decision = agent.step(observation, now)
        reason = farm.progress(now, active=decision.action.kind != "release")
        if reason:
            break
    assert reason and now == 15
    assert "no combat progress" in reason


def test_farming_policy_stop_releases_and_alarms_with_clip(app):
    app.farming = Farming({"pet_recovery": False})
    app._start_sustain()
    app._stop("POLICY_STOP", "Farming session limit reached; restart manually")
    assert app.controller.stopped.is_set()
    assert app.alarm.snapshot()["active"]
    assert app.stop_record.clip_path


def test_no_consumables_disables_all_sustain_and_food(app):
    app.farming = Farming({"pet_recovery": False, "no_consumables": True, "feed_seconds": 1})
    app.probed.update({"hp_potion", "mp_potion"})
    app._start_sustain()
    assert app.sustain == () and not app.potter.enabled
    assert app.farming.next_feed is None
    now = app.farming.started
    assert app.farming.check(now, readings(), True) is None
    assert "HP low" in app.farming.check(now, readings(hp=50), True)
    assert "MP low" in app.farming.check(now, readings(mp=50), True)
