import pytest

from maplebot.config import AgentConfig
from maplebot.decision import Agent, PolicyInput, State
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation


def entity(kind="monster", x=200, y=100, confidence=0.99):
    return Detection(kind, Rect(x, y, 24, 28), confidence)


def scene(monsters=None, player=None, shift=(0, 0)):
    return Observation(
        player or entity("player", 100),
        monsters if monsters is not None else [entity()],
        camera_shift=shift,
    )


def test_selects_nearest_same_platform_and_moves_in_short_steps():
    agent = Agent(AgentConfig())
    agent.start()
    targets = [entity(x=120, y=30), entity(x=250), entity(x=200)]
    acquired = agent.step(scene(targets), 0)
    assert acquired.state == State.APPROACH
    assert acquired.target.box.x == 200
    movement = agent.step(scene(targets), 0.1)
    assert movement.action.kind == "right"
    assert movement.action.seconds == 0.12


def test_ranged_attack_faces_and_fires_without_melee_approach():
    agent = Agent(AgentConfig(attack_min_range=80, attack_range=300))
    agent.start()
    target = scene([entity(x=350)])
    agent.step(target, 0)
    facing = agent.step(target, 0.1)
    assert facing.state == State.ATTACK and facing.action.kind == "right"
    assert agent.step(target, 0.2).action.kind == "attack"


def test_ranged_target_enters_dead_zone_before_firing():
    agent = Agent(AgentConfig(attack_min_range=80, attack_range=300))
    agent.start()
    target = scene([entity(x=190)])
    agent.step(target, 0)
    agent.step(target, 0.1)
    result = agent.step(scene([entity(x=170)]), 0.2)
    assert result.state == State.IDLE and result.action.kind == "release"
    assert "minimum attack range" in result.reason


def test_target_crossing_sides_requires_facing_again():
    agent = Agent(AgentConfig())
    agent.start()
    target = scene([entity(x=120)])
    agent.step(target, 0)
    agent.step(target, 0.1)
    result = agent.step(scene([entity(x=80)]), 0.2)
    assert result.state == State.ATTACK and result.action.kind == "left"


@pytest.mark.parametrize("low,high", [(-1, 65), (65, 65), (70, 65), (0, float('inf')),
                                       (float('nan'), 65)])
def test_rejects_invalid_attack_range(low, high):
    with pytest.raises(ValueError, match="attack_min_range"):
        AgentConfig(attack_min_range=low, attack_range=high)


@pytest.mark.parametrize("x,direction", [(0, "left"), (220, "right")])
def test_moves_towards_target(x, direction):
    agent = Agent(AgentConfig())
    agent.start()
    observation = scene([entity(x=x)])
    agent.step(observation, 0)
    assert agent.step(observation, 0.1).action.kind == direction


def test_attack_is_followed_by_observation_and_no_kill_claim():
    agent = Agent(AgentConfig())
    agent.start()
    close = scene([entity(x=140)])
    assert agent.step(close, 0).state == State.APPROACH
    facing = agent.step(close, 0.1)
    assert facing.state == State.ATTACK
    assert facing.action.kind == "right"
    attack = agent.step(close, 0.2)
    assert attack.state == State.VERIFY
    assert attack.action.kind == "attack"
    assert agent.step(close, 0.3).action.kind == "release"
    absent = scene([])
    assert agent.step(absent, 0.8).state == State.VERIFY
    assert agent.step(absent, 0.9).state == State.VERIFY
    result = agent.step(absent, 1.0)
    assert result.state == State.SEARCH
    assert result.action.kind == "release"
    assert "kill unconfirmed" in result.reason


@pytest.mark.parametrize(
    "observation",
    [
        Observation(None, [entity()]),
        scene(player=entity("player", 100, confidence=0.4)),
        scene([entity(confidence=0.5)]),
        scene([]),
        scene([entity(y=30)]),
    ],
)
def test_uncertainty_stops_and_releases(observation):
    agent = Agent(AgentConfig())
    agent.start()
    decision = agent.step(observation, 0)
    assert decision.state == State.IDLE
    assert decision.action.kind == "release"


def test_missing_target_stops_approach():
    agent = Agent(AgentConfig())
    agent.start()
    agent.step(scene(), 0)
    decision = agent.step(scene([]), 0.1)
    assert decision.state == State.IDLE
    assert "missing" in decision.reason


def test_target_association_compensates_camera_translation():
    agent = Agent(AgentConfig())
    agent.start()
    agent.step(scene([entity(x=220)]), 0)
    result = agent.step(scene([entity(x=120)], player=entity("player", 0), shift=(-100, 0)), 0.1)
    assert result.state == State.APPROACH
    assert result.target.box.x == 120
    assert result.action.kind == "right"


def test_attack_limit_stops_without_assuming_success():
    agent = Agent(AgentConfig(max_attack_attempts=1))
    agent.start()
    observation = scene([entity(x=140)])
    for now in (0, 0.1, 0.2):
        agent.step(observation, now)
    decision = agent.step(observation, 2)
    assert decision.state == State.IDLE
    assert "limit" in decision.reason


def test_approach_stops_when_subsequent_screenshots_show_no_progress():
    agent = Agent(AgentConfig())
    agent.start()
    for index in range(7):
        result = agent.step(scene(), index * 0.3)
    assert result.state == State.IDLE
    assert result.action.kind == "release"
    assert "No observed approach progress" in result.reason


def test_tracked_player_below_threshold_keeps_agent_running():
    agent = Agent(AgentConfig())
    agent.start()
    tracked = Detection("player", Rect(100, 100, 24, 28), 0.5, "tracked", tracked=True)
    assert agent.step(scene(player=tracked), 0).state != State.IDLE
    weak = Detection("player", Rect(100, 100, 24, 28), 0.5)
    assert agent.step(scene(player=weak), 0.1).state == State.IDLE


def attack_with(agent, mp, now):
    """Drive one in-range target to the attack decision with the given MP reading."""
    observation = scene([entity(x=130)])
    agent.start()
    agent.step_input(PolicyInput(observation, now, {"status": "not_sent"}, mp))
    agent.step_input(PolicyInput(observation, now + 0.1, {"status": "not_sent"}, mp))
    return agent.step_input(PolicyInput(observation, now + 0.2, {"status": "not_sent"}, mp))


def test_skill_attack_needs_high_mp_and_unreadable_mp_uses_basic():
    agent = Agent(AgentConfig())
    assert attack_with(agent, 80.0, 0).action.kind == "skill"
    assert attack_with(agent, None, 10).action.kind == "attack"
    assert attack_with(agent, 30.0, 20).action.kind == "attack"


def test_skill_attack_has_mp_hysteresis_between_marks():
    agent = Agent(AgentConfig())
    assert [agent._attack_kind(mp) for mp in (30.0, 80.0, 30.0, 10.0, 30.0, 40.0)] == [
        "attack", "skill", "skill", "attack", "attack", "skill",
    ]


def test_mp_reading_survives_policy_input_round_trip():
    value = PolicyInput(scene(), 1.0, {"status": "not_sent"}, 55.5).to_dict()
    assert PolicyInput.from_dict(value).mp_percent == 55.5
    del value["mp_percent"]
    assert PolicyInput.from_dict(value).mp_percent is None
