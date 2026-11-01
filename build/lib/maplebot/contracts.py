"""Versioned debugger contracts, independent of capture and keyboard output."""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
COMMANDS = frozenset({
    "windows", "focus_game", "attach", "manual", "connect_saved_window", "freeze", "resume_view",
    "crop", "reset_crop", "confirm_capture", "template", "reload_templates", "save",
    "record", "clip", "dry_run", "arm", "stop", "pause", "probe", "confirm_probe",
    "reject_probe", "acknowledge", "restart_capture", "restart_bot", "shutdown_bot",
    "autopotter_calibrate", "autopotter_settings", "autopotter_start", "autopotter_live",
    "autopotter_stop", "range_profile",
    "area_list", "area_load", "area_begin", "area_capture", "area_save", "area_end",
    "position_start", "position_stop", "position_supplement",
    "walk_calibration_begin", "walk_calibration_finish",
    "walk_calibration_cancel",
    "nav_refresh", "nav_preview", "nav_start", "nav_go", "nav_edge",
})
FRESH_FRAME_COMMANDS = frozenset(
    {"dry_run", "arm", "probe", "autopotter_live", "nav_start", "nav_go", "nav_edge"}
)
URGENT_COMMANDS = frozenset({"stop", "pause"})
# The pipeline runs near 3 fps and publishes frames ~0.4 s after capture; 0.5 s rejected most input.
FRESH_FRAME_SECONDS = 1.5


@dataclass(frozen=True)
class CommandContext:
    epoch: int
    issued_at: float

    def validate(self, epoch: int, *, max_age: float = 2) -> None:
        if self.epoch != epoch or not -0.25 <= time.time() - self.issued_at <= max_age:
            raise ValueError("Command expired or superseded; refresh the view and try again")


class CommandGate:
    """Reserve command IDs before dispatch, without holding a lock during engine work."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ids: deque[str] = deque(maxlen=512)

    def accept(self, envelope: Any, snapshot: dict) -> tuple[str, dict, CommandContext | None]:
        if not isinstance(envelope, dict) or envelope.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported command schema")
        name = envelope.get("name")
        if not isinstance(name, str) or name not in COMMANDS:
            raise ValueError("Unknown command")
        if envelope.get("session_id") != snapshot["session_id"]:
            raise ValueError("Session changed; reload the debugger")
        payload = envelope.get("payload", {})
        if not isinstance(payload, dict) or any(key.startswith("_") for key in payload):
            raise ValueError("Command payload must be an object without reserved keys")
        command_id = envelope.get("command_id")
        if not isinstance(command_id, str) or not 8 <= len(command_id) <= 128:
            raise ValueError("A unique command_id is required")
        context = None
        if name not in URGENT_COMMANDS:
            issued_at = envelope.get("issued_at")
            epoch = envelope.get("command_epoch")
            if type(issued_at) not in (int, float) or type(epoch) is not int:
                raise ValueError("Command time and epoch are required")
            context = CommandContext(epoch, issued_at)
            context.validate(snapshot["command_epoch"])
            if name in FRESH_FRAME_COMMANDS:
                frame = snapshot["frame"]
                if (
                    not frame["available"] or frame["age_ms"] is None
                    or frame["age_ms"] > FRESH_FRAME_SECONDS * 1000
                    or envelope.get("expected_frame_id") not in _recent_frame_ids(frame["id"])
                ):
                    raise ValueError("A fresh matching frame is required; refresh the view")
        with self.lock:
            if command_id in self.ids:
                raise ValueError("Command already submitted; refresh before trying again")
            self.ids.append(command_id)
        return name, payload, context



def catalog_warning(catalog: dict) -> str | None:
    """Explain catalog states that silently change what recognition can see."""
    if catalog.get("spawn_error"):
        return f"{catalog['spawn_error']}; monster catalog paused"
    if catalog.get("map_filter_error"):
        return f"Map name reader failed ({catalog['map_filter_error']}); monster catalog paused"
    if catalog.get("catalog_paused"):
        return ("Map name unreadable: monster catalog paused. "
                "Keep the minimap visible and uncovered by game windows")
    return None


def _recent_frame_ids(frame_id: str) -> set[str]:
    """Accept the frame the operator saw or the one published after it."""
    prefix, _, sequence = frame_id.rpartition(":")
    if not prefix or not sequence.isdigit():
        return {frame_id}
    return {frame_id, f"{prefix}:{int(sequence) - 1}"}


def potion_blocker(status: dict, resources: list[str]) -> str:
    potter = status.get("autopotter", {})
    for resource in resources:
        reading = potter.get("readings", {}).get(resource, {})
        if (resource not in potter.get("calibrated", [])
                or reading.get("percent") is None or reading.get("confidence", 0) < 0.9):
            return f"Calibrate a readable {resource.upper()} bar first"
        if resource == "hp" and reading["percent"] == 0:
            return "HP empty; check the game before starting"
        if not status.get("probes", {}).get(f"{resource}_potion", {}).get("confirmed"):
            return f"Verify the {resource.upper()} potion control first"
    return ""


def readiness(status: dict) -> dict[str, dict[str, bool | str]]:
    """Summarize existing gates; this never authorizes input or replaces runtime checks."""
    frame = status["frame"]
    reason = ""
    if status.get("area_editing"):
        reason = "Finish area editing first"
    elif (
        not frame["available"] or frame["age_ms"] is None
        or frame["age_ms"] > FRESH_FRAME_SECONDS * 1000
    ):
        reason = (
            "Waiting for a game frame" if not frame["available"] or frame["age_ms"] is None
            else f"Recognition is {frame['age_ms'] / 1000:.1f} s behind the game picture "
            f"(limit {FRESH_FRAME_SECONDS:g} s)"
        )
    elif status.get("calibrating"):
        reason = "Return to live view first"
    elif not status.get("calibration", {}).get("capture_verified"):
        reason = "Connect and verify the game view first"
    preview = {"ready": not reason, "reason": reason or "Ready for input-free preview"}
    if not reason and status.get("capture_only"):
        reason = "Capture-only session: gameplay input is locked"
    if not reason and status.get("alarm", {}).get("active"):
        reason = "Acknowledge the active alarm first"
    if not reason and status.get("active_probe"):
        reason = "Finish or reject the active probe first"
    if not reason:
        reason = status.get("input_setup_blocker", "") or ""
    common = reason
    player_reason = ""
    if not status.get("player") or status["player"].get("tracked"):
        player_reason = "Waiting for a confirmed player"
    elif status["player"].get("confidence", 0) < status.get("player_threshold", 0.9):
        player_reason = "Waiting for a confident player"
    potter = status.get("autopotter", {})
    resources = [r for r in ("hp", "mp") if potter.get("settings", {}).get(f"{r}_threshold", 0) > 0]
    if not reason:
        missing = [
            name for name in status.get("required_probes", [])
            if not status.get("probes", {}).get(name, {}).get("confirmed")
        ]
        if missing:
            reason = "Verify controls: " + ", ".join(missing)
        else:
            reason = player_reason or potion_blocker(status, resources)
    potion_reason = common or (potion_blocker(status, resources) if resources
                               else "Set at least one potion threshold above zero")
    result = {
        "preview": preview,
        "combat": {"ready": not reason, "reason": reason or "Ready for combat countdown"},
        "potions": {"ready": not potion_reason,
                    "reason": potion_reason or "Ready for potion countdown"},
    }
    for action in status.get("required_probes", []) + status.get("optional_probes", []):
        blocker = common or player_reason
        if not blocker and action in {"hp_potion", "mp_potion"}:
            resource = action.split("_")[0]
            reading = potter.get("readings", {}).get(resource, {})
            if reading.get("percent") is None or reading.get("confidence", 0) < 0.9:
                blocker = f"Calibrate a readable {resource.upper()} bar first"
            elif reading["percent"] >= status.get("potion_full_percent", 95):
                blocker = f"{resource.upper()} is full; lower it before probing"
        result[f"probe:{action}"] = {
            "ready": not blocker, "reason": blocker or "Ready for probe countdown",
        }
    return result
