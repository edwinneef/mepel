"""Versioned debugger contracts, independent of capture and keyboard output."""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
COMMANDS = frozenset({
    "windows", "attach", "manual", "connect_saved_window", "freeze", "resume_view",
    "crop", "reset_crop", "confirm_capture", "template", "reload_templates", "save",
    "record", "clip", "dry_run", "arm", "stop", "pause", "probe", "confirm_probe",
    "reject_probe", "acknowledge", "restart_capture", "restart_bot", "shutdown_bot",
    "autopotter_calibrate", "autopotter_settings", "autopotter_start", "autopotter_live",
    "autopotter_stop",
    "area_list", "area_load", "area_begin", "area_capture", "area_save", "area_end",
    "position_start", "position_stop", "walk_calibration_begin", "walk_calibration_finish",
    "walk_calibration_cancel", "teach_new_area", "teach_begin", "teach_finish", "teach_save",
    "teach_cancel", "teach_resume", "teach_pause", "teach_checkpoint",
    "nav_refresh", "nav_preview", "nav_start",
})
FRESH_FRAME_COMMANDS = frozenset({"dry_run", "arm", "probe", "autopotter_live", "nav_start"})
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
    common = reason
    if not reason:
        missing = [
            name for name in status.get("required_probes", [])
            if not status.get("probes", {}).get(name, {}).get("confirmed")
        ]
        if missing:
            reason = "Verify controls: " + ", ".join(missing)
        elif not status.get("player") or status["player"].get("tracked"):
            reason = "Waiting for a confirmed player"
        elif status["player"].get("confidence", 0) < status.get("player_threshold", 0.9):
            reason = "Waiting for a confident player"
    return {
        "preview": preview,
        "combat": {"ready": not reason, "reason": reason or "Ready for combat countdown"},
        "potions": {"ready": not common, "reason": common or "Check potion HUD and probes"},
    }
