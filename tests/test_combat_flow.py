import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from maplebot.config import AgentConfig
from maplebot.decision import Agent, PolicyInput, State
from maplebot.geometry import Rect
from maplebot.localization import Platform
from maplebot.perception import Detection, Observation
from maplebot.runtime import Application


def policy(monsters, *, player_y=100, outcome=None, platforms=()):
    player = Detection("player", Rect(100, player_y, 24, 28), 1)
    return PolicyInput(Observation(player, monsters), 1, outcome or {},
                       platforms=platforms, immediate_actions=True)


def enemy(x=150, y=100, track="enemy:1"):
    return Detection("monster", Rect(x, y, 24, 28), 1, "catalog:Slime:jump-0",
                     track_id=track)


def test_recorded_fh374_wait_uses_projected_support_without_extra_handoff():
    records = json.loads((Path(__file__).parent / "fixtures/fh374-combat-flow.json").read_text())
    for record in records:
        agent = Agent(AgentConfig(attack_range=65, use_skill=False))
        agent.restore(record["policy_before"])
        inputs = PolicyInput.from_dict(record["policy_input"])
        legacy = replace(inputs, platforms=(), immediate_actions=False)
        assert agent.step_input(legacy).action.kind == "release"
        agent.restore(record["policy_before"])
        result = agent.step_input(inputs)
        assert result.action.kind == record["expected_action"]
        assert result.target is not None
        assert PolicyInput.from_dict(inputs.to_dict()) == inputs


@pytest.mark.parametrize("platforms,player_y,expected", [
    ((("floor", 0, 128, 400, 128),), 100, "right"),
    ((("upper", 0, 88, 400, 88), ("floor", 0, 128, 400, 128)), 100, "release"),
    ((("floor", 0, 128, 400, 128),), 60, "release"),
    ((("floor", 0, 128, 120, 128),), 100, "release"),
    ((("a", 0, 128, 400, 128), ("b", 0, 130, 400, 130)), 100, "release"),
    ((), 100, "release"),
])
def test_jumping_enemy_requires_unique_shared_support(platforms, player_y, expected):
    agent = Agent(AgentConfig())
    agent.start()
    result = agent.step_input(policy([enemy(x=240, y=60)], player_y=player_y,
                                    platforms=platforms))
    assert result.action.kind == expected


def test_acquisition_faces_immediately_then_attacks_at_completed_boundary():
    agent = Agent(AgentConfig(use_skill=False))
    agent.start()
    inputs = policy([enemy()])
    assert agent.step_input(inputs).action.kind == "right"
    pending = replace(inputs, now=1.1, last_outcome={"status": "pending"})
    assert agent.step_input(pending).action.kind == "release"
    completed = replace(inputs, now=1.2, last_outcome={
        "status": "completed", "action": "right", "result": "right completed"})
    assert agent.step_input(completed).action.kind == "attack"
    assert agent.attempts == 1
    assert agent.step_input(replace(completed, now=1.3)).action.kind == "release"


@pytest.mark.parametrize("replacement_track", ["enemy:1", "enemy:2"])
def test_replacement_target_acts_without_release_and_preserves_verify_budget(replacement_track):
    agent = Agent(AgentConfig(use_skill=False))
    agent.start()
    inputs = policy([enemy(x=300)])
    assert agent.step_input(inputs).action.kind == "right"
    inputs = replace(inputs, now=2, observation=Observation(inputs.observation.player,
                     [enemy(track=replacement_track)]), last_outcome={
                         "status": "completed", "action": "right", "result": "right completed"})
    assert agent.step_input(inputs).action.kind == "attack"
    deadline = agent.verify_until
    # An in-range challenger on the other side cannot buy an early second attack.
    replacement = replace(inputs, now=2.1, observation=Observation(inputs.observation.player,
                          [enemy(x=90, track="enemy:3")]))
    assert agent.step_input(replacement).action.kind == "release"
    assert agent.verify_until == deadline and agent.attempts == 1


@pytest.mark.parametrize("invalid", [{"stale": True}, {"held": True}, {"provisional": True},
                                  {"kind": "unknown"}, {"area_id": "other"},
                                  {"projection": None},
                                  {"projection": {"x": 0, "y": 0, "scale": 1, "revision": 2}}])
def test_runtime_projects_only_current_confirmed_map_geometry(invalid):
    locator = SimpleNamespace(profile={"id": "map", "revision": 1},
                              platforms=(Platform("floor", 0, 400, 128),))
    app = SimpleNamespace(position=locator)
    position = {"kind": "platform", "area_id": "map", "projection": {
        "x": 10, "y": 20, "scale": 2, "revision": 1}}
    assert Application._combat_platforms(app, position) == (("floor", 10, 276, 810, 276),)
    assert Application._combat_platforms(app, {**position, **invalid}) == ()


def test_fast_handoff_cannot_act_on_uncertain_player():
    agent = Agent(AgentConfig())
    agent.start()
    inputs = policy([enemy()])
    inputs = replace(inputs, observation=replace(inputs.observation, player=None))
    result = agent.step_input(inputs)
    assert result.state == State.IDLE and result.action.kind == "release"


def test_jump_keeps_identity_but_waits_for_strike_height_before_attack():
    agent = Agent(AgentConfig(use_skill=False))
    agent.start()
    inputs = policy([enemy(y=60)], platforms=(("floor", 0, 128, 400, 128),))
    result = agent.step_input(inputs)
    assert result.action.kind == "release" and result.target.track_id == "enemy:1"
    assert "strike height" in result.reason
    landed = replace(inputs, now=1.2, observation=replace(inputs.observation, monsters=[enemy()]))
    assert agent.step_input(landed).action.kind == "right"
    assert agent.step_input(replace(landed, now=1.4)).action.kind == "attack"
