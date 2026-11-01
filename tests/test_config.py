import math
from pathlib import Path

import pytest

from maplebot.config import AgentConfig, Config, InputConfig, ProbeConfig


def test_input_bindings_load_only_from_input_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[input]\nup="up"\ndown="down"\nhp_potion="insert"\n'
                    'mp_potion="delete"\npet_food="home"\nskill="ctrl"\n[probe]\n')
    config = Config.load(path)
    assert (
        config.input.up,
        config.input.down,
        config.input.hp_potion,
        config.input.mp_potion,
        config.input.pet_food,
        config.input.skill,
    ) == ("up", "down", "insert", "delete", "home", "ctrl")
    assert config.input.vertical_lease_seconds == 1.0
    assert config.input.vertical_lease_max_seconds == 8.0


@pytest.mark.parametrize(
    "settings",
    [
        {"vertical_lease_seconds": math.nan},
        {"vertical_lease_seconds": math.inf},
        {"vertical_lease_seconds": 0},
        {"vertical_lease_max_seconds": 31},
        {"vertical_lease_seconds": 2, "vertical_lease_max_seconds": 1},
        {"up": ""},
    ],
)
def test_input_config_rejects_invalid_lease_or_binding(settings):
    with pytest.raises(ValueError):
        InputConfig(**settings)


def test_probe_settings_load_from_the_validated_probe_section():
    config = Config.load(Path("config.toml"))
    assert config.probe.potion_effect_seconds == 2.0
    assert config.probe.potion_min_gain_percent == 1.0
    assert config.probe.potion_full_percent == 95.0


@pytest.mark.parametrize(
    "settings",
    [
        {"potion_effect_seconds": math.nan},
        {"potion_effect_seconds": 0},
        {"potion_min_gain_percent": 0},
        {"potion_full_percent": 101},
    ],
)
def test_probe_config_rejects_unbounded_or_non_finite_values(settings):
    with pytest.raises(ValueError):
        ProbeConfig(**settings)


@pytest.mark.parametrize("seconds", [math.nan, 0.5, 61])
def test_agent_config_rejects_unbounded_clear_time(seconds):
    with pytest.raises(ValueError, match="clear_seconds"):
        AgentConfig(clear_seconds=seconds)


def test_pose_collection_config_limits(tmp_path):
    from maplebot.config import PoseCollectionConfig

    assert PoseCollectionConfig().limit == 32
    for changes in ({"limit": 0}, {"limit": 129}, {"interval": 0}, {"interval": float('nan')}):
        with pytest.raises(ValueError):
            PoseCollectionConfig(**changes)
    path = tmp_path / 'poses.toml'
    path.write_text('[pose_collection]\nlimit=12\ninterval=5\n')
    assert Config.load(path).pose_collection == PoseCollectionConfig(12, 5)
