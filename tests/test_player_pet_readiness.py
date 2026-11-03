"""Fresh player and binding-specific pet-food permission regressions; fake input only."""
import threading
import time
from dataclasses import replace

import pytest
from test_runtime import app as _app

from maplebot.decision import Action
from maplebot.farming import Farming
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation
from maplebot.runtime import PROBE_ACTIONS, REQUIRED_PROBES

app = _app


@pytest.mark.parametrize("tracked,confidence", [(True, 1.0), (False, .1)])
@pytest.mark.parametrize("mode", ["probe_wait", "pending_arm"])
def test_countdown_rejects_unconfirmed_player(app, monkeypatch, tracked, confidence, mode):
    app.request_probe({"action": "left"})
    app.mode = mode
    player = Detection("player", Rect(10, 20, 20, 30), 1.0)
    monkeypatch.setattr(app.detector, "detect", lambda *args, **kwargs: Observation(player, []))
    app._process(app.image, time.perf_counter())  # Confirmed at the start of the countdown.
    app.pending_at = 0
    player = replace(player, confidence=confidence, tracked=tracked)
    with pytest.raises(RuntimeError, match="Player detection uncertain"):
        app._process(app.image, time.perf_counter())
    assert not app.controller.enabled
    assert not any(down for _, down in app.controller.backend.events)


def test_fresh_player_allows_bounded_pet_probe_and_signature_confirmation(app, monkeypatch):
    assert "pet_food" in PROBE_ACTIONS
    player = Detection("player", Rect(10, 20, 20, 30), 1.0)
    monkeypatch.setattr(app.detector, "detect", lambda *args, **kwargs: Observation(player, []))
    released = threading.Event()
    original_send = app.controller.backend.send

    def send(key, down):
        original_send(key, down)
        if not down:
            released.set()

    monkeypatch.setattr(app.controller.backend, "send", send)
    app.controller.planner.config = replace(app.controller.planner.config, enabled=False)
    app.request_probe({"action": "pet_food"})
    app.pending_at = 0
    app._process(app.image, time.perf_counter())
    assert released.wait(2)
    # Completion is published after release; wait only for that executor bookkeeping.
    deadline = time.perf_counter() + 2
    while app.controller.active is not None:
        assert time.perf_counter() < deadline
        time.sleep(.001)
    app._process(app.image, time.perf_counter())
    active = app.active_probe
    assert active.phase == "awaiting_confirmation"
    assert app.controller.backend.events == [(app.config.input.pet_food, True),
                                              (app.config.input.pet_food, False)]
    schedule = app.controller.last_timing["schedule"]
    assert max(event["at_seconds"] for event in schedule["events"]) <= .12
    assert app.confirm_probe({"id": active.id, "generation": active.generation})["confirmed"]
    app.probed.clear()
    app._restore_probes()
    assert "pet_food" in app.probed
    app.config = replace(app.config, input=replace(app.config.input, pet_food="g"))
    app._restore_probes()
    assert "pet_food" not in app.probed


def test_unconfirmed_food_never_submits_at_feeding_deadline(app, monkeypatch):
    app.farming = Farming({"feed_seconds": 60})
    app.farming.start(time.perf_counter())
    app.farming.next_feed = 0
    submit = []
    monkeypatch.setattr(app.controller, "submit",
                        lambda action, **kwargs: submit.append(action) or 1)
    app._arbitrate(Action(), None)
    assert app.farming.next_feed is None
    assert not any(action.kind == "pet_food" for action in submit)


@pytest.mark.parametrize("mode", ["arm", "dry_run"])
def test_farming_preparation_disables_unconfirmed_feeding(app, mode):
    app.probed.update(REQUIRED_PROBES)
    app.potter.bars = {"hp": object(), "mp": object()}
    app._command(mode, {"farming": {"single_platform": True}})
    if mode == "arm":
        assert app.farming.settings["feed_seconds"] is None
    else:
        assert app.farming is None and not app.controller.enabled
