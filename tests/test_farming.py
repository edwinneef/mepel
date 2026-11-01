import pytest
from test_runtime import app as _app
from test_runtime import potion_app as _potion_app

from maplebot.decision import Action
from maplebot.farming import CHECKPOINT_STOP, Farming

app = _app
potion_app = _potion_app


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


@pytest.mark.parametrize("seconds", [True, 0, 11, 1.5, float("nan")])
def test_checkpoint_rejects_invalid_bound(seconds):
    with pytest.raises(ValueError, match="checkpoint_seconds"):
        Farming({"checkpoint_seconds": seconds, "no_consumables": True,
                 "pet_recovery": False})


def test_checkpoint_is_explicit_no_consumables_and_does_not_replace_session_limit():
    with pytest.raises(ValueError, match="no consumables"):
        Farming({"checkpoint_seconds": 10})
    farm = Farming({"checkpoint_seconds": 10, "no_consumables": True, "pet_recovery": False})
    farm.start(100)
    assert farm.checkpoint_reason(109.999) is None
    assert farm.check(110, readings(), True) == CHECKPOINT_STOP
    assert farm.settings["session_minutes"] == 15


@pytest.mark.parametrize("resource", ["hp", "mp"])
@pytest.mark.parametrize("field,value", [
    ("confidence", float("nan")), ("confidence", float("inf")),
    ("confidence", True), ("confidence", None), ("confidence", "1"),
    ("percent", -1), ("percent", 101), ("percent", True),
    ("percent", "80"), ("percent", float("inf")), ("percent", float("nan")),
])
def test_invalid_hud_evidence_stops_farming(resource, field, value):
    farm = Farming({"no_consumables": True})
    farm.start(0)
    evidence = readings()
    evidence[resource][field] = value
    assert farm.check(1, evidence, True) == f"Farming {resource.upper()} unreadable; stopped"


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


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_single_platform_flag_is_explicit_boolean(value):
    with pytest.raises(ValueError, match="single_platform"):
        Farming({"single_platform": value})


def test_single_platform_arms_without_routes_preserving_health_stops(app):
    from maplebot.runtime import REQUIRED_PROBES

    app.probed.update(REQUIRED_PROBES)
    app.potter.bars = {"hp": object(), "mp": object()}
    settings = {"single_platform": True, "no_consumables": True, "pet_recovery": False}
    assert app._command("arm", {"farming": settings})["mode"] == "pending_arm"
    assert not app.rotating
    app._clear_stop_banner()  # The live countdown clears the preparation Stop banner.
    app._start_sustain()
    app.recorder.start("combat")  # Live activation opens the combat recording.
    assert app.farming.snapshot()["settings"]["single_platform"]
    assert not app.sustain and app.farming.next_feed is None
    reason = app.farming.check(app.farming.started, readings(mp=50), True)
    app._stop("POLICY_STOP", reason)
    assert app.controller.stopped.is_set() and app.farming is None
    assert app.alarm.snapshot()["active"] and app.stop_record.clip_path


def test_rotation_stays_required_for_existing_farming_mode(app):
    from maplebot.runtime import REQUIRED_PROBES

    app.probed.update(REQUIRED_PROBES)
    app.potter.bars = {"hp": object(), "mp": object()}
    with pytest.raises(ValueError, match="Track a saved map"):
        app._command("arm", {"farming": {"no_consumables": True}})


def test_one_platform_policy_repeats_approach_attack_and_reacquisition():
    from maplebot.config import AgentConfig
    from maplebot.decision import Agent
    from maplebot.geometry import Rect
    from maplebot.perception import Detection, Observation

    agent = Agent(AgentConfig(attack_range=65))
    agent.start()
    player = Detection("player", Rect(100, 100, 24, 28), .99)
    far = Observation(player, [Detection("monster", Rect(240, 100, 24, 28), .99)])
    near = Observation(player, [Detection("monster", Rect(165, 100, 24, 28), .99)])
    farm = Farming({"single_platform": True, "no_consumables": True})
    farm.start(0)
    now = 0
    for acquisition in (1, 2):
        assert agent.step(far, now).state == "APPROACH"
        assert agent.acquisitions == acquisition
        now += 1 / 3
        assert agent.step(far, now).action.kind == "right"
        now += 1 / 3
        assert agent.step(near, now).action.kind in {"right", "release"}
        now += 1 / 3
        assert agent.step(near, now).action.kind == "attack"
        assert farm.check(now, readings(), True) is None
        # Missing pixels never establish a kill; release before acquiring again.
        for _ in range(5):
            now += 1 / 3
            decision = agent.step(Observation(player, []), now)
            assert decision.action.kind == "release"
        assert agent.state == "SEARCH"


def test_live_pipeline_links_attack_ticket_to_acquisition(potion_app, monkeypatch):
    import time
    from dataclasses import replace

    from test_autopotter import hud

    from maplebot.decision import State
    from maplebot.geometry import Rect
    from maplebot.perception import Detection, Observation

    app = potion_app
    player = Detection("player", Rect(622, 498, 44, 64), 1)
    enemy = Detection("monster", Rect(524, 505, 65, 73), .99)
    monkeypatch.setattr(app.detector, "detect",
                        lambda *args, **kwargs: Observation(player, [enemy]))
    monkeypatch.setattr("maplebot.runtime.annotate", lambda image, *args: image.copy())
    app.agent.config = replace(app.agent.config, attack_range=90)
    app.agent.state, app.agent.target, app.agent.facing = State.ATTACK, enemy, "left"
    app.agent.acquisitions = 2
    app.farming = Farming({"single_platform": True, "no_consumables": True})
    app._start_sustain()
    app.combat_evidence.start("combat")
    app.mode = "live"
    app.stop_requested.clear()
    app.controller.enable()
    app._process(hud(), time.perf_counter())
    event = app.combat_evidence.snapshot()["events"][-1]
    assert event["kind"] == "decision" and event["action"] in {"attack", "skill"}
    assert event["acquisition"] == 2 and type(event["ticket"]) is int
    app._stop("OPERATOR_STOP", "Offline test complete")
    assert app.controller.stopped.is_set() and not app.rotating
