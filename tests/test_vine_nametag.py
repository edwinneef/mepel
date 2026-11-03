"""Recorded pixels, isolated name matching, fake input and a deterministic input clock.

These crops reproduce tag occlusion, not the full live sprite catalog or capture timing.
No local recordings, mutable character settings, network or native input are required.
"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest
from test_keyboard import controller as _controller
from test_keyboard import observation_clock as _observation_clock
from test_keyboard import queued_plan
from test_runtime import app as _app

from maplebot.config import PerceptionConfig
from maplebot.decision import Action
from maplebot.perception import Detection, Observation, TemplateDetector

FIXTURE = Path(__file__).parent / "fixtures" / "vine-nametag"
app = _app
controller = _controller
observation_clock = _observation_clock


@pytest.fixture
def detector():
    instance = TemplateDetector(FIXTURE, PerceptionConfig(nametag_confidence=.85))
    yield instance
    instance.pool.shutdown()
    instance.map_filter.close()


def frame(name):
    image = cv2.imread(str(FIXTURE / f"{name}.png"))
    assert image is not None, f"Missing committed fixture: {name}"
    return image


def test_recorded_vine_lowers_tag_score_and_clear_pixels_restore_identity(detector):
    players = []
    for name, expected in [("clear-before", .939682), ("occluded", .776557),
                           ("clear-after", 1.0)]:
        gray = cv2.cvtColor(frame(name), cv2.COLOR_BGR2GRAY)
        matches = detector._nametag_candidates(gray)
        assert matches[0][0].confidence == pytest.approx(expected, abs=1e-5)
        # No independent fresh sprite: the obscured name alone cannot prove identity.
        players.append(detector._fuse_nametag(matches, None, [], gray)[0])
    before, obscured, after = players
    assert before is not None and after is not None
    assert before.template == after.template
    assert not before.tracked and not after.tracked
    assert obscured is None


@pytest.mark.parametrize("mode", ["probe_wait", "pending_arm"])
@pytest.mark.parametrize("coasting", [False, True])
def test_vine_gap_cannot_finish_start_countdown(app, detector, monkeypatch, mode, coasting):
    from maplebot import runtime

    clock = [100.]
    monkeypatch.setattr(runtime, "time", SimpleNamespace(
        perf_counter=lambda: clock[0], time=lambda: 1800000000. + clock[0]))
    gray = cv2.cvtColor(frame("clear-before"), cv2.COLOR_BGR2GRAY)
    confirmed = detector._fuse_nametag(detector._nametag_candidates(gray), None, [], gray)[0]
    assert confirmed is not None
    app.request_probe({"action": "left"})
    app.mode = mode
    player = confirmed
    monkeypatch.setattr(app.detector, "detect", lambda *a, **kw: Observation(player, []))
    app._process(app.image, 100.)
    gray = cv2.cvtColor(frame("occluded"), cv2.COLOR_BGR2GRAY)
    matches = detector._nametag_candidates(gray)
    sprite = (Detection("player", detector.body_from_nametag(matches[0][1], matches[0][0].box),
                        1., confirmed.template, tracked=True) if coasting else None)
    player = detector._fuse_nametag(matches, sprite, [], gray)[0]
    assert player is None or player.tracked
    app.pending_at = 0
    clock[0] = 100.3
    with pytest.raises(RuntimeError, match="Player detection uncertain"):
        app._process(app.image, 100.3)
    assert not app.controller.enabled and not app.controller.held
    assert not any(down for _, down in app.controller.backend.events)


def test_clear_name_after_gap_cannot_refresh_queued_input(detector, observation_clock):
    control, backend, clock, source = observation_clock
    before = detector.detect(frame("clear-before"), 100., monsters=False).player
    assert before is not None and not before.tracked
    control.submit(Action("right", .1))
    pending = queued_plan(control)
    gray = cv2.cvtColor(frame("occluded"), cv2.COLOR_BGR2GRAY)
    assert detector._fuse_nametag(detector._nametag_candidates(gray), None, [], gray)[0] is None
    clock[0] = 100.6
    after = detector.detect(frame("clear-after"), clock[0], monsters=False).player
    assert after is not None and not after.tracked
    assert after.template == before.template
    source[0] = replace(source[0], capture_clock=100.6, deadline=101.1, sequence=4)
    assert control._execute_schedule(pending) == "right interrupted"
    assert "observation expired" in control.reason
    assert pending.observation.deadline == 100.5
    assert not backend.events and not control.held and not control.enabled
