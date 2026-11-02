from pathlib import Path
from types import SimpleNamespace

import pytest

from maplebot import key_settings
from maplebot.config import Config
from maplebot.runtime import Application

ACTIVE = {"hp_potion": "insert", "mp_potion": "delete", "pet_food": "f", "attack": "ctrl",
          "skill": "ctrl", "jump": "alt", "emergency_key": "f8", "start_stop": "f6",
          "widget": "f7", "drawings": "f9", "pet_feed_seconds": 600}


def test_valid_change_returns_the_full_key_set():
    keys = key_settings.validate(ACTIVE, {"hp_potion": "Home", "pet_feed_seconds": 300})
    assert keys == {**ACTIVE, "hp_potion": "home", "pet_feed_seconds": 300}


@pytest.mark.parametrize("change, message", [
    ({"hp_potion": "f"}, "F is used for both HP potion and Pet food"),
    ({"start_stop": "f8"}, "used for both Stop and Start or stop"),
    ({"emergency_key": "q"}, "Stop must be one of F1 to F12"),
    ({"emergency_key": ""}, "cannot be pressed"),
    ({"widget": "ctrl"}, "Show or hide the widget must be one of F1 to F12"),
    ({"jump": "up"}, "Arrow keys"),
    ({"hp_potion": "numlock"}, "cannot be pressed"),
    ({"left": "a"}, "Unknown key setting"),
    ({"pet_feed_seconds": 30}, "every 1 to 60 minutes"),
    ({}, "at least one key"),
])
def test_refused_changes_say_why(change, message):
    with pytest.raises(ValueError, match=message):
        key_settings.validate(ACTIVE, change)


def test_attack_and_skill_may_share_a_key_but_nothing_else():
    assert key_settings.validate(ACTIVE, {"skill": "ctrl"})["skill"] == "ctrl"
    with pytest.raises(ValueError, match="Attack skill and Jump"):
        key_settings.validate(ACTIVE, {"skill": "alt"})


def test_write_keeps_comments_and_other_settings_and_makes_a_backup(tmp_path):
    path = tmp_path / "config.toml"
    original = ('[capture]\nfps = 3\n\n[input]\n# Potion keys\nhp_potion = "insert"  # HP\n'
                'mp_potion = "delete"\npet_food = "f"\nattack = "ctrl"\nskill = "ctrl"\n'
                'jump = "alt"\nemergency_key = "f8"\n\n[probe]\npotion_effect_seconds = 2.0\n')
    path.write_text(original, encoding="utf-8")
    keys = key_settings.validate(ACTIVE, {"hp_potion": "home", "start_stop": "f5"})
    backup = key_settings.write(path, keys)
    text = path.read_text("utf-8")
    assert backup.read_text("utf-8") == original
    assert 'hp_potion = "home"  # HP' in text and "# Potion keys" in text
    assert "pet_feed_seconds = 600\n\n[probe]\npotion_effect_seconds = 2.0" in text
    assert text.endswith('[hotkeys]\nstart_stop = "f5"\nwidget = "f7"\ndrawings = "f9"\n')
    config = Config.load(path)
    assert config.input.hp_potion == "home" and config.hotkeys.start_stop == "f5"
    assert key_settings.current(config) == keys


def test_saved_keys_refuse_every_start_until_restart(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(Path("config.toml").read_text("utf-8"), encoding="utf-8")
    config = Config.load(path)
    app = SimpleNamespace(config=config, config_path=path, mode="capture", active_probe=None,
                          farming=None, stop_lock=__import__("threading").RLock())
    for name in ("_key_settings_snapshot", "_save_keys", "request"):
        setattr(app, name, getattr(Application, name).__get__(app))
    assert app._key_settings_snapshot()["restart_required"] is False
    result = app.request("input_keys_set", {"keys": {"hp_potion": "home"}})
    assert result["restart_required"] is True and Path(result["backup"]).exists()
    for name in ("arm", "dry_run", "probe", "autopotter_live", "nav_start"):
        with pytest.raises(ValueError, match="Restart the engine to use the new keys"):
            app.request(name, {})
    assert Config.load(path).input.hp_potion == "home"
    app.mode = "armed"
    with pytest.raises(ValueError, match="Stop the bot"):
        app.request("input_keys_set", {"keys": {"mp_potion": "end"}})
