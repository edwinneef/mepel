import threading
import time

import pytest
from test_keyboard import controller as _controller
from test_navigation import fixture
from test_runtime import app as _app

from maplebot.input_timing import KeyHold
from maplebot.navigation import RouteMap
from maplebot.navigation_executor import Feedback

app, controller = _app, _controller


def preview(app):
    profile, evidence = fixture()
    nav = app.navigation
    nav.graph = RouteMap(profile, evidence)
    nav.route = nav.graph.plan("floor", "ledge")
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400),
                            "floor", True)
    app.probed.update({"left", "right", "jump"})
    return nav


def test_capture_only_cannot_start_navigation_even_with_supervision_flag(app):
    preview(app)
    app.capture_only = True
    with pytest.raises(ValueError, match="Capture-only"):
        app._command("nav_start", {"opt_in": True})
    assert not app.controller.enabled and app.controller.backend.events == []


def test_start_requires_explicit_optin_and_stop_cancels_countdown(app):
    nav = preview(app)
    with pytest.raises(ValueError, match="opt-in"):
        app._command("nav_start", {})
    app._command("nav_start", {"opt_in": True})
    assert app.mode == "navigation_wait" and not app.controller.enabled
    assert nav.snapshot()["stage"] == "countdown" and nav.snapshot()["active"]
    assert app.controller.backend.events == []
    app.request("stop", {})
    assert app.mode == "capture" and not nav.agent.active
    assert app.controller.backend.events == []


def test_changed_map_or_old_feedback_cannot_start(app):
    nav = preview(app)
    nav.feedback = Feedback(time.perf_counter() - 1, nav.graph.fingerprint,
                            (150, 400), "floor", True)
    with pytest.raises(ValueError, match="fresh fused"):
        app._command("nav_start", {"opt_in": True})
    assert app.controller.backend.events == []


def test_queued_chord_cancellation_does_not_cancel_potion_or_send_late_movement(controller):
    control, backend, _ = controller
    control.enable()
    entered, proceed = threading.Event(), threading.Event()
    original = control._execute_schedule
    def wait(item):
        entered.set()
        assert proceed.wait(2)
        return original(item)
    control._execute_schedule = wait
    ticket = control.submit_sequence([KeyHold("right", .04), KeyHold("jump", .02, .012)])
    assert entered.wait(2)
    control.cancel_ticket(ticket)
    proceed.set()
    deadline = time.perf_counter() + 2
    while not control.outcomes.qsize() and time.perf_counter() < deadline:
        time.sleep(.005)
    assert backend.events == [] and control.enabled
    assert control.poll_outcomes()[0].result.endswith("interrupted")


def test_chord_cannot_exceed_existing_action_cap(controller):
    control, backend, _ = controller
    with pytest.raises(ValueError, match="duration"):
        control.submit_sequence([KeyHold("jump", .06, control.config.max_action_seconds)])
    assert backend.events == []
