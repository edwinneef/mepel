import threading
import time
from dataclasses import replace

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



def test_go_plans_from_the_current_platform_and_starts_one_countdown(app):
    nav = preview(app)
    nav.route = None
    with pytest.raises(ValueError, match="opt-in"):
        app._command("nav_go", {"target": "ledge"})
    with pytest.raises(ValueError, match="already on"):
        app._command("nav_go", {"target": "floor", "opt_in": True})
    app._command("nav_go", {"target": "ledge", "opt_in": True})
    assert (nav.route.origin, nav.route.target) == ("floor", "ledge")
    assert app.mode == "navigation_wait" and nav.snapshot()["stage"] == "countdown"
    assert app.controller.backend.events == []


def test_go_refuses_an_unknown_platform_and_slightly_old_feedback_still_counts(app):
    nav = preview(app)
    nav.feedback = Feedback(time.perf_counter() - 1, nav.graph.fingerprint, (150, 400),
                            None, True)
    with pytest.raises(ValueError, match="platform is unknown"):
        app._command("nav_go", {"target": "ledge", "opt_in": True})
    nav.feedback = Feedback(time.perf_counter() - 1, nav.graph.fingerprint, (150, 400),
                            "floor", True)
    app._command("nav_go", {"target": "ledge", "opt_in": True})
    assert app.mode == "navigation_wait"


def test_navigation_start_clears_the_previous_stop_so_a_later_alarm_gets_its_own_record(app):
    nav = preview(app)
    app._command("nav_start", {"opt_in": True})
    previous = app.stop_record
    assert previous is not None and app.mode == "navigation_wait"
    app.pending_at = 0
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), "floor", True)
    nav.tick(None, time.perf_counter())
    assert app.mode == "navigation" and app.stop_record is None
    app.windows.window = replace(app.windows.window, focused=False)
    app._controller_stop("FOCUS_LOSS", "Target focus, geometry, or visibility lost")
    assert app.stop_record.id != previous.id and app.stop_record.code == "FOCUS_LOSS"
    assert "Click the actual game window" in app.stop_record.message

def test_changed_map_or_old_feedback_cannot_start(app):
    nav = preview(app)
    nav.feedback = Feedback(time.perf_counter() - 2, nav.graph.fingerprint,
                            (150, 400), "floor", True)
    with pytest.raises(ValueError, match="fresh fused"):
        app._command("nav_start", {"opt_in": True})
    assert app.controller.backend.events == []


def test_navigation_potion_is_registered_for_passive_evidence(app):
    nav = preview(app)
    app._command("nav_start", {"opt_in": True})
    app.pending_at = 0
    nav.tick(None, time.perf_counter())
    app.sustain = ("hp",)
    nav.feedback = replace(nav.feedback, now=time.perf_counter())
    nav.tick("hp", time.perf_counter())
    record = app.potion_evidence.snapshot()["records"][-1]
    assert record["ticket"] == app.live_potion_ticket
    assert record["resource"] == "hp" and record["status"] == "queued"
    assert app.active_probe is None
    app._stop("OPERATOR_STOP", "offline test complete")
    app.potion_evidence.close()
    app.recorder.close()


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


def test_a_brief_marker_name_tag_disagreement_mid_jump_does_not_stop_the_route(app):
    nav = preview(app)
    app._command("nav_start", {"opt_in": True})
    app.pending_at = 0
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), "floor", True)
    nav.tick(None, time.perf_counter())
    assert app.mode == "navigation"
    nav.agent.stage, nav.agent.takeoff_at = "flight", time.perf_counter()
    nav.agreed_at = time.perf_counter()
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (200, 330), None, False)
    nav.tick(None, time.perf_counter())
    assert app.mode == "navigation" and app.stop_record is None
    nav.agreed_at = time.perf_counter() - 1.0  # disagreement outlasted the grace
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (220, 300), None, False)
    nav.tick(None, time.perf_counter())
    assert app.mode == "capture" and app.stop_record.code == "PLAYER_UNCERTAIN"


def test_disagreement_outside_flight_still_stops_at_once(app):
    nav = preview(app)
    app._command("nav_start", {"opt_in": True})
    app.pending_at = 0
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), "floor", True)
    nav.tick(None, time.perf_counter())
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), "floor", False)
    nav.tick(None, time.perf_counter())
    assert app.mode == "capture" and app.stop_record.code == "PLAYER_UNCERTAIN"


def test_a_brief_name_tag_dropout_while_walking_to_the_launch_point_is_ridden_out(app):
    nav = preview(app)
    app._command("nav_start", {"opt_in": True})
    app.pending_at = 0
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), "floor", True)
    nav.tick(None, time.perf_counter())
    nav.agent.stage, nav.agreed_at = "approach", time.perf_counter()
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (140, 400), None, False)
    nav.tick(None, time.perf_counter())
    assert app.mode == "navigation" and app.stop_record is None
    nav.agreed_at = time.perf_counter() - 1.0  # the tag stayed missing past the grace
    nav.tick(None, time.perf_counter())
    assert app.mode == "capture" and app.stop_record.code == "PLAYER_UNCERTAIN"


def test_start_and_settling_ride_out_a_name_tag_dropout_on_the_origin(app):
    nav = preview(app)
    now = time.perf_counter()
    nav.confirmed = ("floor", now)  # agreed a moment ago; this frame lost the name tag
    nav.feedback = Feedback(now, nav.graph.fingerprint, (150, 400), None, False)
    assert nav.blocker() is None
    nav.confirmed = ("floor", now - 2)
    assert nav.blocker() == "Waiting for fresh fused position on the previewed origin"
    nav.confirmed = ("floor", now)
    app._command("nav_start", {"opt_in": True})
    app.pending_at = 0
    nav.agreed_at = time.perf_counter()
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), None, False)
    nav.tick(None, time.perf_counter())
    assert app.mode == "navigation" and nav.agent.stage == "settle_origin"

@pytest.mark.parametrize("kind", ["drop", "climb"])
def test_marker_only_move_is_bounded_by_path_and_eight_seconds(app, kind):
    from maplebot.navigation_executor import Navigator
    nav = preview(app)
    now = time.perf_counter()
    nav.route = replace(nav.route, edges=(replace(nav.route.edges[0], kind=kind),))
    nav.agent = Navigator(nav.graph, nav.route, now - 2)
    nav.agent.stage = "flight"
    edge = nav.route.edges[0]
    nav.feedback = Feedback(now, nav.graph.fingerprint, edge.launch, None, False)
    assert nav.trusted()
    nav.feedback = replace(nav.feedback, feet=(10000, 10000))
    assert not nav.trusted()
    nav.feedback = replace(nav.feedback, feet=edge.launch)
    nav.agent.edge_started = now - 8
    assert not nav.trusted()
    nav.agent.edge_started = now - 2
    nav.agent.stage = "settle_origin"
    assert not nav.trusted()
