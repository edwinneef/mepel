import json
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
from maplebot.navigation_runtime import POSE_COVERAGE

app, controller = _app, _controller


@pytest.mark.parametrize(("threshold", "trusted"), [(.85, True), (.90, False)])
def test_navigation_motion_uses_configured_player_threshold(app, monkeypatch, threshold, trusted):
    import json
    from types import SimpleNamespace

    from maplebot.geometry import Rect
    from maplebot.perception import Detection, Observation

    nav = preview(app)
    app.config = replace(app.config, perception=replace(app.config.perception,
                                                      confidence=threshold))
    app.position = SimpleNamespace(profile=nav.graph.profile,
                                   tracker=SimpleNamespace(transform=SimpleNamespace(
                                       to_area=lambda x, y: (x, y))))
    path = app.areas.directory / f"{nav.graph.profile['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(nav.graph.profile), encoding="utf-8")
    monkeypatch.setattr(app, "_input_block_reason", lambda: None)
    observation = Observation(Detection("player", Rect(145, 380, 10, 20), .875421), [],
                              camera_shift=(0, 0), camera_confidence=1)
    for now in (1.0, 1.2):
        nav.observe(SimpleNamespace(dot=(150, 400)), observation, {"surface_id": "floor"}, now)
    assert nav.feedback.motion_ok is trusted
    assert app.controller.backend.events == []


@pytest.mark.parametrize(("age", "motion", "feet", "reason"), [
    (.507, True, (150, 400), "stale"),
    (.1, False, (150, 400), "motion_or_marker_uncertain"),
    (.1, False, None, "motion_or_marker_uncertain"),
])
def test_feedback_refusal_records_the_decision_pair(app, monkeypatch, age, motion, feet, reason):
    from types import SimpleNamespace

    from maplebot import navigation_runtime
    nav = preview(app)
    monkeypatch.setattr(navigation_runtime, "time", SimpleNamespace(perf_counter=lambda: 100))
    nav.feedback = replace(nav.feedback, now=100 - age, motion_ok=motion, feet=feet)
    app.mode = "navigation"
    message = app._input_block_reason()
    assert reason in message
    refused = nav.last_feedback_failure.copy()
    assert refused["reason"] == reason and refused["age_ms"] == round(age * 1000, 3)
    nav.feedback = replace(nav.feedback, now=100, motion_ok=True, feet=(150, 400))
    assert nav.trusted()
    assert nav.snapshot()["last_feedback_failure"] == refused
    assert app.controller.backend.events == []


def test_feedback_boundary_and_physical_focus_gate_are_unchanged(app, monkeypatch):
    from types import SimpleNamespace

    from maplebot import navigation_runtime
    nav = preview(app)
    monkeypatch.setattr(navigation_runtime, "time", SimpleNamespace(perf_counter=lambda: 100))
    nav.feedback = replace(nav.feedback, now=99.5)
    assert nav.trusted()
    nav.feedback = replace(nav.feedback, now=99.499)
    assert not nav.trusted()
    nav.feedback = replace(nav.feedback, now=100)
    app.mode = "navigation"
    app.windows.window = replace(app.windows.window, focused=False)
    assert "Click the actual game window" in app._input_block_reason()
    assert app.controller.backend.events == []


def test_controller_refusal_survives_a_new_frame_before_stop_callback(app, monkeypatch):
    from types import SimpleNamespace

    from maplebot import navigation_runtime
    nav = preview(app)
    monkeypatch.setattr(navigation_runtime, "time", SimpleNamespace(perf_counter=lambda: 100))
    nav.feedback = replace(nav.feedback, now=99.493)
    app.mode = "navigation"
    assert not app._input_safe()
    refusal = nav.last_input_refusal
    nav.feedback = replace(nav.feedback, now=100)
    assert app._input_safe()
    app._controller_stop("FOCUS_LOSS", "Target focus, geometry, or visibility lost")
    assert refusal in app.stop_record.message and '"age_ms": 507.0' in refusal
    assert nav.snapshot()["last_input_refusal"] == refusal
    assert app.controller.backend.events == []


def test_watchdog_recognition_timeout_is_not_reported_as_focus_loss(app):
    nav = preview(app)
    app.mode = "navigation"
    nav.last_input_refusal = "Player recognition recovery timed out"
    app._controller_stop("FOCUS_LOSS", "Target focus, geometry, or visibility lost")
    assert app.stop_record.code == "PLAYER_UNCERTAIN"
    assert app.stop_record.message == "Player recognition recovery timed out"
    assert app.mode == "capture" and not app.controller.enabled
    assert not app.controller.held
    assert app.alarm.snapshot()["active"]


def preview(app):
    profile, evidence = fixture()
    nav = app.navigation
    nav.graph = RouteMap(profile, evidence)
    nav.route = nav.graph.plan("floor", "ledge")
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400),
                            "floor", True)
    app.probed.update({"left", "right", "jump"})
    return nav


def test_routes_need_offline_verified_recognition_in_every_pose(app):
    nav = preview(app)
    path = app.areas.directory.parent / POSE_COVERAGE
    assert nav.blocker() is None
    path.write_text(json.dumps({"verified": ["walk/left", "walk/right", "air/left"]}))
    assert nav.blocker() == "Player recognition unverified for pose: air/right"
    with pytest.raises(ValueError, match="unverified for pose: air/right"):
        app._command("nav_start", {"opt_in": True})
    path.unlink()
    assert nav.blocker().startswith("Verify player recognition offline first")
    assert app.mode == "capture" and app.controller.backend.events == []


def test_proof_disk_write_waits_until_controller_is_stopped(app, monkeypatch):
    from maplebot.navigation_executor import Navigator
    nav = preview(app)
    nav.graph.profile['public_map'] = True
    nav.graph.proven.clear()
    nav.agent = Navigator(nav.graph, nav.route, time.perf_counter())
    nav.agent.completed = nav.agent.index = 1
    writes = []
    def record(*args):
        assert not app.controller.enabled
        writes.append(args)
    monkeypatch.setattr(nav.proofs, 'record', record)
    app.controller.enable()
    nav._learn()
    assert not writes and nav.pending_proofs
    assert nav.route.edges[0].id in nav.graph.proven
    app.safe_stop('OPERATOR_STOP', 'test')
    assert len(writes) == 1 and not nav.pending_proofs


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


def test_navigator_waits_for_a_running_pulse_so_a_takeoff_is_never_dropped(app, monkeypatch):
    nav = preview(app)
    app._command("nav_start", {"opt_in": True})
    app.pending_at = 0
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (150, 400), "floor", True)
    nav.tick(None, time.perf_counter())
    steps = []
    monkeypatch.setattr(nav.agent, "step", lambda f: steps.append(f) or nav.agent.stop("test"))
    nav.ticket = 41
    app.arbiter.submitted(41, "navigation")
    nav.feedback = replace(nav.feedback, now=time.perf_counter())
    nav.tick(None, time.perf_counter())
    assert steps == [] and app.mode == "navigation"
    app.arbiter.finished(41)
    nav.feedback = replace(nav.feedback, now=time.perf_counter())
    nav.tick(None, time.perf_counter())
    assert len(steps) == 1 and nav.ticket is None


@pytest.mark.parametrize(("started", "edge_started", "completed", "reason"), [
    (90, 92, 0, "Edge deadline exhausted; no blind retry"),
    (40, 99, 0, "Route time or edge budget exhausted"),
    (99, 99, 8, "Route time or edge budget exhausted"),
    (90, 92.001, 0, None),
])
def test_pending_ticket_still_enforces_budgets_and_uses_normal_stop(
        app, monkeypatch, started, edge_started, completed, reason):
    from types import SimpleNamespace

    from maplebot import navigation_runtime
    from maplebot.navigation_executor import Navigator

    nav = preview(app)
    nav.agent = Navigator(nav.graph, nav.route, started)
    nav.agent.edge_started, nav.agent.completed = edge_started, completed
    nav.feedback = replace(nav.feedback, now=100)
    nav.ticket = 41
    app.arbiter.submitted(41, "navigation")
    app.mode = "navigation"
    monkeypatch.setattr(navigation_runtime, "time", SimpleNamespace(perf_counter=lambda: 100))
    monkeypatch.setattr(app, "_input_block_reason", lambda: None)
    steps = []
    original_step = nav.agent.step
    monkeypatch.setattr(nav.agent, "step", lambda f: steps.append(nav.agent.active)
                        or original_step(f))
    with app.controller.lock:
        app.controller.held["right"] = time.perf_counter() + 1
    nav.tick(None, 100)
    if reason is None:
        assert app.mode == "navigation" and nav.ticket == 41
        assert steps == [] and app.controller.held
    else:
        assert app.mode == "capture" and nav.agent.stage == "stopped"
        assert app.stop_record.code == "NAVIGATION_FAILURE"
        assert app.stop_record.message == reason
        assert steps == [False]  # Only an already-stopped navigator is stepped.
        assert not app.controller.enabled and not app.controller.held
        assert nav.ticket is None and not app.arbiter.in_flight
        assert app.alarm.snapshot()["active"]


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

def test_focus_game_is_off_only_and_never_sends_gameplay_input(app):
    app.windows.focus = lambda hwnd: True
    assert app._command("focus_game", {}) == {
        "focused": True, "input_sent": False, "focus_click_allowed": False}
    assert not app.controller.backend.events
    app.mode = "navigation"
    with pytest.raises(ValueError, match="Stop gameplay"):
        app._command("focus_game", {})


def test_edge_step_starts_only_at_a_map_end_and_stops_once_the_name_tag_returns(app):
    nav = preview(app)
    nav.route = None
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (300, 400), None, False)
    with pytest.raises(ValueError, match="not at a map edge"):
        app._command("nav_edge", {"opt_in": True})
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (450, 400), None, False)
    with pytest.raises(ValueError, match="opt-in"):
        app._command("nav_edge", {})
    app._command("nav_edge", {"opt_in": True})
    assert app.mode == "navigation_wait" and nav.snapshot()["stage"] == "countdown"
    app.pending_at = 0
    nav.feedback = replace(nav.feedback, now=time.perf_counter())
    nav.tick(None, time.perf_counter())
    assert app.mode == "navigation" and nav.ticket is not None
    nav.ticket = None
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (430, 400), "floor", True)
    nav.tick(None, time.perf_counter())
    assert app.mode == "capture" and nav.agent.stage == "arrived"


def test_capture_only_cannot_start_an_edge_step(app):
    nav = preview(app)
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (450, 400), None, False)
    app.capture_only = True
    with pytest.raises(ValueError, match="Capture-only"):
        app._command("nav_edge", {"opt_in": True})
    assert app.controller.backend.events == []


def test_search_strip_follows_an_active_edge_step_only(app):
    from maplebot.navigation_executor import EdgeStep
    nav = preview(app)
    assert nav.search_strip(1366) is None
    nav.agent = EdgeStep(nav.graph, time.perf_counter())
    nav.feedback = Feedback(time.perf_counter(), nav.graph.fingerprint, (450, 400), None, False)
    assert nav.search_strip(1366) == (886, 1366)
    nav.feedback = replace(nav.feedback, feet=(120, 400))
    assert nav.search_strip(1366) == (0, 480)
    nav.agent.stop("done")
    assert nav.search_strip(1366) is None
