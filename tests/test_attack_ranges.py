import json

import pytest

from maplebot.attack_ranges import PROFILES, RangeStore
from maplebot.config import AgentConfig, Config
from maplebot.decision import Agent, PolicyInput, State
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation


@pytest.mark.parametrize("profile", PROFILES, ids=lambda item: item.id)
@pytest.mark.parametrize("side", [-1, 1])
@pytest.mark.parametrize("mp,action", [(None, "attack"), (100, "skill")])
def test_profile_drives_approach_attack_and_minimum_stop(profile, side, mp, action):
    config = AgentConfig(range_profile=profile.id)
    assert (config.attack_min_range, config.attack_range) == (
        profile.minimum_px, profile.maximum_px,
    )
    if profile.minimum_px == 0:
        assert config.attack_range <= min(profile.basic_reaches_px) - 10

    def decision_at(distance):
        observation = Observation(
            Detection("player", Rect(500, 100, 24, 28), 1),
            [Detection("monster", Rect(500 + side * distance, 100, 24, 28), 1)],
        )
        agent = Agent(config)
        agent.start()
        agent.step_input(PolicyInput(observation, 0, {}, mp))
        first = agent.step_input(PolicyInput(observation, .1, {}, mp))
        return agent, first, observation

    agent, first, observation = decision_at(profile.maximum_px)
    assert first.action.kind == ("left" if side < 0 else "right")
    assert agent.step_input(PolicyInput(observation, .2, {}, mp)).action.kind == action
    _, first, _ = decision_at(profile.maximum_px + 1)
    assert first.state == State.APPROACH
    assert first.action.kind == ("left" if side < 0 else "right")
    if profile.minimum_px:
        _, first, _ = decision_at(profile.minimum_px - 1)
        assert first.state == State.IDLE and first.action.kind == "release"


def test_custom_range_and_config_file_selection(tmp_path):
    assert AgentConfig(attack_range=91).attack_range == 91
    path = tmp_path / "config.toml"
    path.write_text('[agent]\nrange_profile = "classic_spear"\nattack_range = 999\n')
    assert Config.load(path).agent.attack_range == 100
    with pytest.raises(ValueError, match="Unknown attack range"):
        AgentConfig(range_profile="typo")


def test_range_choice_persists_with_backup_without_input_state(tmp_path):
    store = RangeStore(tmp_path / "combat-range.json")
    assert store.load("custom") == "custom"
    store.save("classic_bow")
    store.save("classic_spear")
    assert RangeStore(store.path).load("custom") == "classic_spear"
    backup, = tmp_path.glob("*.bak")
    assert json.loads(backup.read_text())["profile"] == "classic_bow"
    assert json.loads(store.path.read_text()) == {"version": 1, "profile": "classic_spear"}
    store.path.write_text('{"version": 1, "profile": "unknown"}')
    with pytest.raises(ValueError, match="Unknown attack range"):
        store.load("classic_bow")
