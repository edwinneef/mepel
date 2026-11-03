import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.navigation_harness import Experiment, ModelController, World, main, run, sample_graph


def stable(result):
    return {key: value for key, value in result.items() if key != "wall_seconds"}


def test_round_trip_uses_commands_and_releases_every_key():
    result = run()
    assert result["passed"] and result["arrivals"] == ["ledge", "floor"]
    assert any(event["down"] for event in result["keys"])
    assert any(frame["surface"] is None for frame in result["frames"])
    assert result["held_after"] == []
    assert result["pending_after"] == result["tickets_after"] == 0
    assert result["input_sent"] is result["native_acceptance"] is False


def test_no_delivered_commands_cannot_teleport_to_expected_trace():
    # A simulated backend swallows commands. The body must remain on its actual
    # platform instead of being moved along a prerecorded successful trajectory.
    result = run(Experiment(targets=("ledge",), drop_input=True, expected="safe_stop"))
    assert result["passed"] and not result["arrivals"]
    assert result["keys"] and all(not event["delivered"] for event in result["keys"])
    assert all(frame["feet"] == [230, 400] for frame in result["frames"])
    assert result["stops"][-1]["code"] == "NAVIGATION_FAILURE"


def test_pending_input_cannot_hide_exceeded_navigation_deadlines():
    result = run(Experiment(targets=("ledge",), input_delay=10, expected="safe_stop"))
    assert result["passed"] and result["outcome"] == "safe_stop"
    assert result["violations"] == []
    assert result["stops"][-1]["reason"] == "Edge deadline exhausted; no blind retry"
    assert result["keys"] == []
    assert result["held_after"] == []
    assert result["pending_after"] == result["tickets_after"] == 0


def test_same_seed_repeats_outputs_but_different_seed_changes_schedule():
    first = run(Experiment(seed=1))
    assert stable(first) == stable(run(Experiment(seed=1)))
    assert first["keys"] != run(Experiment(seed=2))["keys"]


@pytest.mark.parametrize("fault", ["focus", "stop", "stale", "map", "missing"])
def test_faults_stop_at_first_failure_cancel_future_events_and_release(fault):
    result = run(Experiment(fault=fault, fault_at=4, expected="safe_stop"))
    assert result["passed"] and not result["arrivals"]
    assert result["keys"]  # The route was actually moving before the fault.
    assert result["held_after"] == []
    assert result["pending_after"] == result["tickets_after"] == 0
    assert len(result["stops"]) == 1
    stop = result["stops"][0]["at"]
    assert not any(event["down"] and event["at"] > stop for event in result["keys"])


def test_recorded_handoff_signature_keeps_arrival_and_next_route_failure_separate():
    case = json.loads((Path(__file__).parents[1] / "tools/navigation_harness_case.json")
                      .read_text("utf-8"))
    result = run(Experiment(**case["experiment"]))
    assert case["observed"]["next_origin_before"] != case["observed"]["next_surface_after"]
    assert result["passed"] and result["arrivals"] == ["ledge"]
    assert result["stops"][-1]["reason"] == case["observed"]["failure"]
    assert result["stops"][-1]["code"] == "NAVIGATION_FAILURE"
    first_arrival = result["stops"][0]["at"]
    assert not any(event["down"] and event["at"] > first_arrival
                   for event in result["keys"])


def test_an_unexpected_stop_reason_is_a_failed_experiment():
    result = run(Experiment(fault="focus", expected="safe_stop", expected_reason="wrong map"))
    assert not result["passed"]


def test_delayed_sequence_keeps_runtime_waiting_for_ticket_completion():
    result = run(Experiment(targets=("ledge",), input_delay=.4))
    assert result["passed"]
    pending = [frame for frame in result["frames"] if frame["ticket"] is not None]
    assert len(pending) >= 2
    assert any(a["ticket"] == b["ticket"] and a["stage"] == b["stage"]
               for a, b in zip(pending, pending[1:], strict=False))


def test_observation_delay_uses_older_positions_and_preserves_freshness_limit():
    delayed = run(Experiment(feedback_delay=.1))
    assert any(frame["feedback_age"] >= .333 for frame in delayed["frames"])
    stale = run(Experiment(feedback_delay=.9, expected="safe_stop"))
    assert stale["passed"] and not stale["keys"]
    assert "stale" in stale["stops"][-1]["reason"]


def test_model_does_not_move_without_keys_and_gravity_does_not_snap_to_landing():
    graph = sample_graph()
    world = World(graph, (230, 400), Experiment())
    world.advance(1, {}, 1)
    assert (world.x, world.y, world.surface) == (230, 400, "floor")
    world.x, world.y, world.surface = 350, 300, None
    world.advance(.1, {}, 1.1)
    assert world.surface is None and 300 < world.y < 350


def test_model_movement_hold_expires_between_frames():
    from maplebot.config import Config
    from maplebot.scheduler import Arbiter

    world = World(sample_graph(), (230, 400), Experiment())
    control = ModelController(world, Experiment(), Config().input, Arbiter(.06))
    control.enable()
    control.refresh_movement("right", .12, navigation=True)
    control.advance(.2)
    assert not control.held
    assert control.log[-1] == {"at": .12, "action": "right", "down": False}


def test_harness_cannot_create_native_controller_or_input_or_write_data(monkeypatch, tmp_path):
    from maplebot import keyboard

    def forbidden(*args, **kwargs):
        raise AssertionError("Native controller or input constructed by offline harness")

    monkeypatch.setattr(keyboard.KeyboardController, "__init__", forbidden)
    monkeypatch.setattr(keyboard.Win32Input, "__init__", forbidden)
    monkeypatch.chdir(tmp_path)
    assert run()["passed"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("settings", [
    {"fps": 0}, {"fps": float("nan")}, {"fps": 10000}, {"input_delay": -.1},
    {"gravity": 0}, {"feedback_delay": float("inf")}, {"fault": "unknown"},
    {"targets": ()}, {"expected": "anything"},
])
def test_invalid_experiments_are_rejected(settings):
    with pytest.raises(ValueError):
        Experiment(**settings)


def test_cli_writes_report_and_refuses_to_overwrite_evidence(monkeypatch, tmp_path, capsys):
    output = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["navigation_harness", "--seeds", "2", "--output", str(output)])
    with pytest.raises(SystemExit) as done:
        main()
    assert done.value.code == 0
    report = json.loads(output.read_text("utf-8"))
    assert report["passed"] == report["total"] == 9
    assert json.loads(capsys.readouterr().out)["input_sent"] is False
    before = output.read_bytes()
    with pytest.raises(SystemExit) as refused:
        main()
    assert refused.value.code != 0
    assert output.read_bytes() == before


def test_cli_evaluates_saved_map_without_writing_native_proofs(monkeypatch, tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    profile = sample_graph().profile | {"public_map": {"id": 42}}
    path = maps / "area.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    before = path.read_bytes()
    output = tmp_path / "result.json"
    monkeypatch.setattr("sys.argv", ["navigation_harness", "--seeds", "1", "--profile", str(path),
                                   "--targets", "ledge", "--output", str(output)])
    with pytest.raises(SystemExit) as done:
        main()
    assert done.value.code == 0
    report = json.loads(output.read_text("utf-8"))
    assert report["passed"] == report["total"] == 1
    assert path.read_bytes() == before
    assert list(maps.iterdir()) == [path]


def test_cli_exits_nonzero_and_saves_counterexample(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    # An incorrect arrival expectation must still fail, even though the stall now stops.
    settings.write_text('{"targets":["ledge"],"input_delay":10,"expected":"arrived"}',
                        encoding="utf-8")
    output = tmp_path / "failed.json"
    monkeypatch.setattr("sys.argv", ["navigation_harness", "--experiment", str(settings),
                                   "--output", str(output)])
    with pytest.raises(SystemExit) as done:
        main()
    assert done.value.code == 1
    report = json.loads(output.read_text("utf-8"))
    assert report["passed"] == 0 and report["runs"][0]["outcome"] == "safe_stop"


def test_cli_refuses_output_inside_protected_data(monkeypatch):
    protected = Path(__file__).parents[1] / "data" / "harness-result.json"
    monkeypatch.setattr("sys.argv", ["navigation_harness", "--output", str(protected)])
    with pytest.raises(SystemExit) as done:
        main()
    assert done.value.code != 0


def test_rope_routes_refuse_unsupported_physics_before_running():
    from maplebot.navigation import Route

    graph = sample_graph()
    graph.profile["ropes"] = [{"id": "rope"}]
    original = graph.plan("floor", "ledge")
    edge = replace(original.edges[0], kind="climb")
    graph.plan = lambda *args, **kwargs: Route(original.area_id, original.revision,
                                              original.fingerprint, "floor", "ledge", (edge,))
    with pytest.raises(ValueError, match="Rope physics is unsupported"):
        run(graph=graph)
