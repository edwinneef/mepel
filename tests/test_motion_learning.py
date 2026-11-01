import json

import pytest

from maplebot.motion_learning import PassiveMovement


def history(sequence=1, key="right"):
    event = {"sequence": 1, "key": key, "down": True, "clock": 1., "finished_clock": 1.01,
             "history_id": "a" * 32}
    return {"history_id": "a" * 32, "history_last_sequence": sequence,
            "history": [event]}


def observe(model, index, **kwargs):
    return model.observe(context="player/map", clock=2 + index * .2,
                         feet=(index * 20., 400.), surface="floor", valid=True,
                         timing=kwargs.pop("timing", history()), **kwargs)


def test_normal_motion_is_evidence_without_promoting_control_parameters(tmp_path):
    model = PassiveMovement(tmp_path / "evidence.json")
    for i in range(15):
        result = observe(model, i)
    assert result["observed_speed_px_s"] == pytest.approx(100)
    assert result["parameters"] == {} and result["input_sent"] is False
    assert "braking" in result["unidentified"]
    model.save()
    assert json.loads(model.cache.read_text())["version"] == 1
    assert PassiveMovement(model.cache).snapshot()["parameters"] == {}


def test_missing_or_discontinuous_events_cannot_identify_motion():
    model = PassiveMovement()
    for i in range(20):
        result = observe(model, i, timing={})
    assert result["samples"] == 0
    observe(model, 0)
    result = observe(model, 1, timing=history(1000000000000))
    assert result["samples"] == 0


def test_opposing_motion_and_changed_character_are_not_accepted():
    model = PassiveMovement()
    for i in range(15):
        result = observe(model, i, timing=history(key="left"))
    assert result["samples"] == 0
    for i in range(15):
        observe(model, i)
    result = model.observe(context="different-player", clock=20., feet=(1., 400.),
                           surface="floor", valid=True, timing=history())
    assert result["samples"] == 0


def test_invalid_dispatch_and_vertical_motion_do_not_train():
    model = PassiveMovement()
    bad = history()
    bad["history"][0]["finished_clock"] = float("nan")
    for i in range(15):
        assert observe(model, i, timing=bad)["samples"] == 0
    for i in range(15):
        result = model.observe(context="jump", clock=2 + i * .2, feet=(i * 20., i * 10.),
                               surface="floor", valid=True, timing=history())
    assert result["samples"] == 0
