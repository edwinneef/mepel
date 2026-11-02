"""Change game keys and bot hotkeys in config.toml.

The engine never swaps keys while it runs: the keyboard controller, the emergency-stop check and
saved control confirmations all hold the keys they started with. A saved change applies at the
next engine restart, and starts are refused until then. Control confirmations are tied to their
key, so a changed potion key must be confirmed again after the restart.
"""

import re
import shutil
import time
from pathlib import Path

from .keyboard import KEYS

GAME_KEYS = ("hp_potion", "mp_potion", "pet_food", "attack", "skill", "jump")
STOP_KEY = "emergency_key"
HOTKEYS = ("start_stop", "drawings")
LABELS = {"hp_potion": "HP potion", "mp_potion": "MP potion", "pet_food": "Pet food",
          "attack": "Attack", "skill": "Attack skill", "jump": "Jump", STOP_KEY: "Stop",
          "start_stop": "Start or stop",
          "drawings": "Show or hide drawings"}
# The bot may press both with one key; the game binds them separately.
SHARED_OK = frozenset({"attack", "skill"})
MOVEMENT = frozenset({"left", "right", "up", "down"})
FUNCTION_KEY = re.compile(r"f([1-9]|1[0-2])")
FEED_RANGE = (60, 3600)


def supported_keys() -> list[str]:
    return sorted(key for key in KEYS if key not in MOVEMENT)


def current(config) -> dict:
    keys = {name: getattr(config.input, name) for name in (*GAME_KEYS, STOP_KEY)}
    keys.update({name: getattr(config.hotkeys, name) for name in HOTKEYS})
    keys["pet_feed_seconds"] = config.input.pet_feed_seconds
    return keys


def validate(active: dict, change: dict) -> dict:
    """Return the complete new key set, or raise ValueError with one plain sentence."""
    if not isinstance(change, dict) or not change:
        raise ValueError("Choose at least one key to change")
    result = dict(active)
    for name, value in change.items():
        if name == "pet_feed_seconds":
            low, high = FEED_RANGE
            if type(value) is not int or not low <= value <= high:
                raise ValueError("Pet feeding must be every 1 to 60 minutes")
            result[name] = value
            continue
        if name not in LABELS:
            raise ValueError(f"Unknown key setting: {name}")
        key = value.strip().lower() if isinstance(value, str) else ""
        if key in MOVEMENT:
            raise ValueError("Arrow keys move the character and cannot be used here")
        if key not in KEYS:
            raise ValueError(f"{LABELS[name]}: that key cannot be pressed by the bot")
        if (name == STOP_KEY or name in HOTKEYS) and not FUNCTION_KEY.fullmatch(key):
            raise ValueError(f"{LABELS[name]} must be one of F1 to F12")
        result[name] = key
    names = [name for name in (*GAME_KEYS, STOP_KEY, *HOTKEYS)]
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            if result[first] == result[second] and {first, second} != SHARED_OK:
                raise ValueError(f"{result[first].upper()} is used for both "
                                 f"{LABELS[first]} and {LABELS[second]}")
    return result


def _set(lines: list[str], section: str, name: str, value: str) -> list[str]:
    """Set name = value inside [section], keeping comments and every other line."""
    header = re.compile(r"\s*\[([^\]]+)\]\s*(#.*)?$")
    entry = re.compile(rf"(\s*){re.escape(name)}\s*=\s*[^#\n]*?(\s*#.*)?$")
    start = end = None
    for index, line in enumerate(lines):
        match = header.match(line)
        if match and start is None and match.group(1).strip() == section:
            start = index
        elif match and start is not None:
            end = index
            break
    if start is None:
        return [*lines, *([""] if lines and lines[-1].strip() else []), f"[{section}]",
                f"{name} = {value}"]
    end = len(lines) if end is None else end
    for index in range(start + 1, end):
        if match := entry.match(lines[index]):
            lines = list(lines)
            lines[index] = f"{match.group(1)}{name} = {value}{match.group(2) or ''}"
            return lines
    insert = end
    while insert - 1 > start and not lines[insert - 1].strip():
        insert -= 1
    return [*lines[:insert], f"{name} = {value}", *lines[insert:]]


def write(path: Path, keys: dict) -> Path:
    """Write the key set to config.toml after a timestamped backup; returns the backup path."""
    text = path.read_text("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    for name in (*GAME_KEYS, STOP_KEY):
        lines = _set(lines, "input", name, f'"{keys[name]}"')
    lines = _set(lines, "input", "pet_feed_seconds", str(keys["pet_feed_seconds"]))
    for name in HOTKEYS:
        lines = _set(lines, "hotkeys", name, f'"{keys[name]}"')
    backup = path.with_name(f"{path.name}.{time.time_ns()}.bak")
    shutil.copy2(path, backup)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")
    temporary.replace(path)
    return backup
