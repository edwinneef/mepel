import math
from pathlib import Path

import pytest

from maplebot.config import Config, InputConfig, ProbeConfig


def test_input_bindings_load_only_from_input_section():
    config = Config.load(Path("config.toml"))
    assert (
        config.input.up,
        config.input.down,
        config.input.hp_potion,
        config.input.mp_potion,
        config.input.pet_food,
        config.input.skill,
    ) == ("up", "down", "insert", "delete", "home", "a")
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
