import hashlib
import json
import math
import queue
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import cv2

from .alarm import AlarmManager
from .attack_ranges import RangeStore, range_options, range_profile
from .autopotter import BarReading, PotionMonitor
from .capture import Calibration, Capture, CaptureMovedError, Image
from .combat_evidence import CombatEvidence
from .combat_readiness import summarize
from .config import Config
from .contracts import (
    FRESH_FRAME_COMMANDS,
    FRESH_FRAME_SECONDS,
    CommandContext,
    catalog_warning,
    readiness,
)
from .decision import Action, Agent, Decision, PolicyInput
from .display_loop import DisplayLoop, DisplaySource
from .farming import CHECKPOINT_STOP, Farming
from .frame_encoder import FrameEncoder, FramePacket
from .geometry import Rect
from .keyboard import (
    KEYS,
    DisabledInput,
    InputBackend,
    InputObservation,
    KeyboardController,
    Win32Input,
)
from .live_position import STALE_SECONDS, LivePosition
from .navigation_runtime import NavigationRuntime
from .perception import NameTag, TemplateDetector, annotate, nametag_parts
from .pose_collection import PoseCollection
from .potion_evidence import PotionEvidence, PotionFrame
from .preview_stream import PreviewSource, PreviewStream
from .probe_store import ProbeStore
from .profiles import AreaStore
from .reacquisition import Reacquisition
from .recorder import SessionRecorder
from .rotation import Rotation, routable, visible_by_surface
from .scheduler import SUSTAIN, Arbiter
from .windows import Window, Windows


class StopSeverity(StrEnum):
    ALARM = "ALARM"
    SILENT = "SILENT"


@dataclass(frozen=True)
class StopReason:
    severity: StopSeverity
    invalidate_probes: bool = False


@dataclass(frozen=True)
class StopRecord:
    id: str
    code: str
    severity: StopSeverity
    message: str
    time: float
    clip_path: str | None
    acknowledged: bool
    encoding_complete: bool


REQUIRED_PROBES = frozenset({"left", "right", "attack", "jump", "skill"})
OPTIONAL_PROBES = frozenset({"up", "down", "hp_potion", "mp_potion"})
PROBE_ACTIONS = REQUIRED_PROBES | OPTIONAL_PROBES
PENDING_SLOW_GRACE_SECONDS = 2.0
# Readouts keep showing the last platform through brief recognition gaps; input never uses it.
DISPLAY_HOLD_SECONDS = 1.0
ELEVATED_GAME_REASON = (
    "MapleStory runs as administrator, so Windows silently drops this bot's keys. "
    "Start the bot from an administrator terminal, or start the game without elevation"
)
POSITION_COMMANDS = frozenset({
    "position_start", "position_stop", "position_supplement",
    "walk_calibration_begin", "walk_calibration_finish",
    "walk_calibration_cancel",
})

# Give ordinary dragging a bounded grace period, independent of capture FPS.
_CAPTURE_MOVE_ATTEMPTS = 5
_CAPTURE_MOVE_RETRY_SECONDS = 0.5


@dataclass(frozen=True)
class ProbeState:
    id: int
    generation: int
    action: str
    phase: str
    instruction: str
    ticket: int | None = None
    resource: str | None = None
    baseline_percent: float | None = None
    pressed_sequence: int | None = None
    pressed_at: float | None = None
    deadline: float | None = None


STOP_REASONS = {
    "CAPTURE_WORKER_EXIT": StopReason(StopSeverity.ALARM, True),
    "CAPTURE_WORKER_FAILURE": StopReason(StopSeverity.ALARM, True),
    "INPUT_WATCHDOG_FAILURE": StopReason(StopSeverity.ALARM, True),
    "INPUT_BACKEND_FAILURE": StopReason(StopSeverity.ALARM, True),
    "FOCUS_LOSS": StopReason(StopSeverity.ALARM, True),
    "CALIBRATION_INVALID": StopReason(StopSeverity.ALARM, True),
    "PLAYER_UNCERTAIN": StopReason(StopSeverity.ALARM),
    "DEBUGGER_TIMEOUT": StopReason(StopSeverity.ALARM),
    "EMERGENCY_STOP": StopReason(StopSeverity.SILENT),
    "OPERATOR_STOP": StopReason(StopSeverity.SILENT),
    "CAPTURE_ONLY_GUARD": StopReason(StopSeverity.SILENT),
    "PROBE_COMPLETE": StopReason(StopSeverity.SILENT),
    "CALIBRATION": StopReason(StopSeverity.SILENT, True),
    "POLICY_STOP": StopReason(StopSeverity.SILENT),
    "FARMING_STOP": StopReason(StopSeverity.ALARM),
    "NAVIGATION_FAILURE": StopReason(StopSeverity.ALARM),
    "DRY_RUN_STOP": StopReason(StopSeverity.SILENT),
}


def png(frame: Image) -> bytes:
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Could not encode screenshot")
    return encoded.tobytes()


class Application:
    """One worker owns capture, calibration, perception and ordered commands."""

    def __init__(
        self,
        config: Config,
        *,
        input_backend: InputBackend | None = None,
        capture_only: bool = False,
    ) -> None:
        self.config = config
        self.session_id = uuid.uuid4().hex
        self.combat_evidence = CombatEvidence(self.session_id)
        self.command_epoch = 0
        self.view_generation = 0
        self.source_generation = 0
        self.published_frame: dict[str, Any] | None = None
        self.live_detections: dict[str, Any] | None = None
        self.display_anchor: tuple[dict[str, Any], Image] | None = None
        self.capture_only = capture_only
        self.data = Path(config.capture.data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.configured_agent = config.agent
        self.range_store = RangeStore(self.data / "combat-range.json")
        selected_range = self.range_store.load(config.agent.range_profile)
        config = replace(config, agent=replace(config.agent, range_profile=selected_range))
        self.config = config
        self.areas = AreaStore(self.data / "areas")
        self.area_editing = False
        self.position: LivePosition | None = None
        self.windows = Windows()
        self.detector = TemplateDetector(self.data / "templates", config.perception)
        self.pose_collection = PoseCollection(
            self.data / "pose-candidates", limit=config.pose_collection.limit,
            interval=config.pose_collection.interval,
        )
        self.agent = Agent(config.agent, config.perception.confidence)
        self.potter = PotionMonitor(self.data / "autopotter.json")
        self.mode = "capture"
        self.last_action = "none"
        self.pending_at = 0.0
        self.calibrating = False
        self.probed: set[str] = set()
        self.probe_store = ProbeStore(self.data / "confirmed-probes.json")
        self.probe_generation = 0
        self.next_probe_id = 1
        self.active_probe: ProbeState | None = None
        self.live_potion_ticket: int | None = None
        self.arbiter = Arbiter(min(0.06, config.input.max_action_seconds))
        # Potions that live combat may press: calibrated bar, threshold set, probe confirmed.
        self.sustain: tuple[str, ...] = ()
        self.potion_hud_missing_since: float | None = None
        self.probe_results: dict[str, dict[str, object]] = {}
        self.stop_reason = (
            "Capture-only session: keyboard output locked; recognition and dry run available"
            if capture_only
            else "Stopped; start dry run or arm combat"
        )
        self.hwnd: int | None = None
        self.manual: Rect | None = None
        self.calibration: Calibration | None = None
        self.image: Image | None = None
        self.window: Window | None = None
        self.region: Rect | None = None
        self.frozen: dict[str, tuple[Image, Window | None, Rect]] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=40)
        self.recorder = SessionRecorder(
            self.data / "recordings", config.recording, config.capture.fps
        )
        self.potion_evidence = PotionEvidence(
            self.session_id, self.recorder.save_potion,
            seconds=config.probe.potion_effect_seconds,
            minimum_gain=config.probe.potion_min_gain_percent, enabled=config.recording.auto,
        )
        self.encoder = FrameEncoder(self._encoded)
        self.player_uncertain = False
        self.reacquisition = Reacquisition()
        self.sequence = 0
        self.policy_outcome: dict[str, Any] = {"status": "not_sent"}
        self.session_capture_started: float | None = None
        self.lock = threading.Lock()
        self.stop_lock = threading.RLock()
        self.worker_lock = threading.RLock()
        self.stop_record: StopRecord | None = None
        self.input_refusal: dict | None = None
        self.refused_window: dict | None = None
        self.processing_frame: dict | None = None
        self.code_revision = {name: hashlib.sha256(
            Path(__file__).with_name(name).read_bytes()).hexdigest()
                              for name in ("runtime.py", "perception.py", "enemy_tracking.py",
                                           "farming.py", "keyboard.py", "windows.py")}
        self.alarm = AlarmManager()
        self.commands: queue.Queue[tuple[str, dict, Future]] = queue.Queue()
        self.closed = threading.Event()
        self.frame_ready = threading.Event()
        self.stop_requested = threading.Event()
        self.mp_percent: float | None = None
        self.worker: threading.Thread | None = None
        self.latest: bytes | None = None
        self.raw: bytes | None = None
        self.preview = PreviewStream(self._preview_source, config.capture.fps)
        self.display = DisplayLoop(self._display_source, config.capture.display_fps)
        self.status: dict[str, Any] = {
            "mode": "capture",
            "state": "IDLE",
            "reason": "Select a window or manual region",
            "features": True,
            "catalog": self.detector.catalog_info,
        }
        if capture_only:
            backend: InputBackend = DisabledInput()
        elif input_backend is not None:
            backend = input_backend
        else:
            backend = Win32Input()
        self.controller = KeyboardController(
            backend,
            config.input,
            self._input_safe,
            lambda: self.windows.pressed(KEYS[config.input.emergency_key]),
            replay=capture_only,
            timing=config.timing,
            on_stop=self._controller_stop,
            observation=self._input_observation,
        )
        self.navigation = NavigationRuntime(self)
        self.farming: Farming | None = None
        self.rotation = Rotation(config.agent.clear_seconds)
        self.rotating = False
        self.monster_search = True
        self.shown_platform: tuple[str, str, float] | None = None

    def start(self) -> None:
        self.connect_saved_window()
        self.preview.start()
        self.display.start()
        self.start_capture_worker()

    def _preview_source(self) -> PreviewSource:
        with self.lock:
            return PreviewSource(
                f"{self.session_id}:source:{self.source_generation}", self.hwnd, self.manual,
                replace(self.calibration) if self.calibration else None,
            )

    def _display_source(self) -> DisplaySource:
        position = self.position
        terrain = None
        if position is not None and not getattr(position, "automatic", None):
            terrain = (position.profile["id"], position.profile["revision"], position.reference,
                       position.view.x, position.view.y, position.view.scale)
        with self.lock:
            return DisplaySource(
                f"{self.session_id}:source:{self.source_generation}", self.view_generation,
                self.hwnd, self.manual, replace(self.calibration) if self.calibration else None,
                self.display_anchor, terrain,
            )

    def drawings(self) -> dict | None:
        """Display-only packets; never read by decisions, input or safety gates."""
        return self.display.drawings()

    def preview_frame(self, frame_id: str) -> bytes | None:
        return self.preview.frame(frame_id, self._preview_source().id)

    def connect_saved_window(self) -> bool:
        path = self.data / "calibration.json"
        if not path.exists():
            return False
        try:
            saved = Calibration.load(path)
            matches = [
                window for window in self.windows.list()
                if saved.valid_for(window)
                and self.config.capture.window_title.casefold() in window.title.casefold()
            ]
            if len(matches) != 1:
                return False
            self._command("attach", {"hwnd": matches[0].hwnd})
            return True
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            self.note(f"Saved game connection unavailable: {error}")
            return False

    def close(self) -> None:
        self.safe_stop("OPERATOR_STOP", "Application closing")
        self.closed.set()
        self.preview.close()
        self.display.close()
        worker = self.worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=3)
        self.controller.close()
        if self.position is not None:
            self.position.close()
        self.encoder.close()
        self.potion_evidence.close()
        self.recorder.close()
        self.pose_collection.close()
        self.alarm.close()

    def request(
        self, name: str, payload: dict, *, context: CommandContext | None = None
    ) -> Any:
        if overlay := getattr(self, "overlay", None):
            overlay.guard(name)
        if context is not None:
            with self.stop_lock:
                context.validate(self.command_epoch)
        if self.area_editing and name in FRESH_FRAME_COMMANDS:
            raise ValueError("Finish area editing before starting input or preview decisions")
        if name == "area_list":
            return self.areas.list()
        if name == "area_load":
            return self.areas.load(payload.get("area_id"))
        if name in {"area_begin", "area_capture", "area_save", "area_end"}:
            with self.stop_lock:
                if context is not None:
                    context.validate(self.command_epoch)
                if name != "area_begin" and not self.area_editing:
                    raise ValueError("Begin area editing first")
                self.area_editing = True
                self.stop_requested.set()
                self.safe_stop("OPERATOR_STOP", "Area editing; all input stopped")
                if name == "area_begin":
                    return {"editing": True}
                if name == "area_end":
                    self.area_editing = False
                    return {"editing": False}
                if name == "area_save":
                    return self.areas.save(payload.get("profile"))
                latest = self.preview.frozen(self._preview_source().id)
                if latest is None:
                    raise ValueError("Wait for a fresh preview before capturing an area view")
                view = self.areas.capture_view(latest[0])
                alignment = self.areas.align_view(latest[0], payload.get("align", []))
                if alignment["aligned"]:
                    view.update(origin=alignment["origin"], scale=alignment["scale"])
                return {"view": view, "alignment": alignment}
        if name == "windows":
            return [asdict(window) for window in self.windows.list()]
        if name == "frozen_png":
            # The image belongs to an immutable frozen selection. Keeping this reference
            # alive is enough even if the worker expires the dictionary entry afterward.
            return png(self.frozen[payload["id"]][0])
        if name in {"stop", "pause"}:
            self.stop_requested.set()
            self.safe_stop("OPERATOR_STOP", "Paused; input released" if name == "pause"
                           else "Operator stopped the agent")
            return {"ok": True}
        if name == "acknowledge":
            return self.acknowledge_stop(payload.get("incident_id"), require_id=True)
        if name == "restart_capture":
            return self.restart_capture()
        if name == "probe":
            return self.request_probe(payload)
        if name == "confirm_probe":
            return self.confirm_probe(payload)
        if name == "reject_probe":
            return self.reject_probe(payload)
        canceled_navigation = name in POSITION_COMMANDS and self.mode in {
            "navigation", "navigation_wait",
        }
        if canceled_navigation:
            self.stop_requested.set()
            self.safe_stop("OPERATOR_STOP", "Position change canceled navigation")
        if name in {
            "stop",
            "attach",
            "connect_saved_window",
            "manual",
            "reset_crop",
            "freeze",
            "crop",
            "template",
            "autopotter_calibrate",
            "reload_templates",
        }:
            # Release now, without waiting for a capture/detector operation to finish.
            self.stop_requested.set()
            self.safe_stop("CALIBRATION", "Debugger stop/calibration")
        if name in {"autopotter_settings", "autopotter_stop", "autopotter_start", "range_profile"}:
            self.stop_requested.set()
            self.safe_stop("OPERATOR_STOP", "Weapon range change; input stopped"
                           if name == "range_profile" else
                           "Autopotter mode/settings change; input stopped")
        if context is not None:
            # Calibration/settings commands above deliberately supersede older work.
            # Start commands do not: a Stop that races a queued Start must win.
            if canceled_navigation or name in {
                "attach", "connect_saved_window", "manual", "reset_crop", "freeze", "crop",
                "template", "autopotter_calibrate", "reload_templates", "autopotter_settings",
                "autopotter_stop", "autopotter_start", "range_profile",
            }:
                context = replace(context, epoch=self.command_epoch)
            payload = {**payload, "_context": context}
        future: Future = Future()
        self.commands.put((name, payload, future))
        try:
            return future.result(timeout=10)
        except TimeoutError:
            future.cancel()
            self.stop_requested.set()
            self.safe_stop("DEBUGGER_TIMEOUT", "Debugger command timed out")
            raise RuntimeError("Debugger command timed out; input stopped") from None

    def snapshot(self) -> dict:
        with self.stop_lock, self.lock:
            potter = {
                "readings": {},
                "reason": "Calibrate full HP/MP bars; preview sends no input",
                **self.status.get("autopotter", {}),
                **self.potter.snapshot(),
            }
            if not self.potter.enabled:
                potter.update(suggestion=None, reason="Potion preview stopped")
            frame = self.published_frame if self.raw is not None else None
            result = {
                **self.status,
                "pose_collection": {
                    **self.pose_collection.snapshot(),
                    "identities": [tag.name for tag in getattr(self.detector, "nametags", [])],
                },
                "schema_version": 1,
                "session_id": self.session_id,
                "code_revision": self.code_revision,
                "farming_checkpoint_available": True,
                "input_state": self.controller.state_snapshot(),
                "input_refusal": self.input_refusal,
                "command_epoch": self.command_epoch,
                "mode": self.mode,
                "calibrating": self.calibrating,
                "area_editing": self.area_editing,
                "sustain": list(self.sustain),
                "navigation": self.navigation.snapshot(),
                "rotation": {**self.rotation.snapshot(), "enabled": self.rotating},
                "farming": self.farming.snapshot() if self.farming else None,
                "monster_search": self.monster_search,
                "player_threshold": self.config.perception.confidence,
                "calibration": asdict(self.calibration) if self.calibration else {},
                "frame": {
                    "source_id": f"{self.session_id}:source:{self.source_generation}",
                    "id": frame["id"] if frame else None,
                    "sequence": frame["sequence"] if frame else None,
                    "captured_at": frame["captured_at"] if frame else None,
                    "age_ms": max(0, round((time.time() - frame["captured_at"]) * 1000, 1))
                    if frame else None,
                    "width": frame["width"] if frame else 0,
                    "height": frame["height"] if frame else 0,
                    "available": frame is not None,
                },
                "preview_frame": self.preview.snapshot(
                    f"{self.session_id}:source:{self.source_generation}"
                ),
                "live_detections": {
                    **self.live_detections,
                    "frame": {
                        **self.live_detections["frame"],
                        "age_ms": max(0, round((time.time()
                            - self.live_detections["frame"]["captured_at"]) * 1000, 1)),
                    },
                    "position": self._position_snapshot(self.live_detections["position"]),
                } if self.live_detections is not None else None,
                "stop": asdict(self.stop_record) if self.stop_record else None,
                "capture_only": self.capture_only,
                "input_setup_blocker": self._input_setup_block_reason(),
                "bindings": asdict(self.config.input),
                "combat_evidence": self.combat_evidence.snapshot(),
                "attack_setup": {
                    "minimum_px": self.config.agent.attack_min_range,
                    "maximum_px": self.config.agent.attack_range,
                    "measured": False,
                    "reason": "Engine-loaded operating band; exact hit limits remain unmeasured",
                    "profile": self.config.agent.range_profile,
                    "profiles": range_options(),
                },
                "potion_full_percent": self.config.probe.potion_full_percent,
                "required_probes": sorted(REQUIRED_PROBES),
                "optional_probes": sorted(OPTIONAL_PROBES),
                "probes": self._probe_snapshot(),
                "active_probe": asdict(self.active_probe) if self.active_probe else None,
                "autopotter": potter,
                "potion_evidence": self.potion_evidence.snapshot(),
                "alarm": self.alarm.snapshot(),
                "history": list(self.history),
            }
            position = result.get("position")
            if position is None and self.position is not None:
                position = {"area_id": self.position.profile["id"],
                            "area_name": self.position.profile["name"], "kind": "unknown",
                            "reason": "Waiting for capture",
                            "captured_at": 0, "input_sent": False}
            result["position"] = self._position_snapshot(position)
            result["readiness"] = readiness(result)
            preview = result["preview_frame"]
            camera_ok = bool(preview.get("available") and preview.get("age_ms", 1001) <= 1000)
            lag_ms = result["frame"]["age_ms"] if frame else None
            recognition_ok = bool(lag_ms is not None and lag_ms <= FRESH_FRAME_SECONDS * 1000)
            position_ok = bool(recognition_ok and result["position"]
                               and result["position"].get("kind") == "platform")
            result["health"] = {
                "camera": camera_ok, "recognition": recognition_ok, "position": position_ok,
                "reason": "Game picture unavailable" if not camera_ok else
                (f"Recognition is {lag_ms / 1000:.1f} s behind the game picture"
                 if lag_ms is not None else "Waiting for recognition") if not recognition_ok else
                result["position"].get("reason", "Position unavailable")
                if result["position"] and not position_ok else "Game picture and recognition ready",
                "warning": catalog_warning(result.get("catalog") or {}),
            }
            return result

    def frame(self, frame_id: str, *, raw: bool = False) -> bytes | None:
        with self.lock:
            if not self.published_frame or frame_id != self.published_frame["id"]:
                return None
            return self.raw if raw else self.latest

    def _invalidate_view(self, *, source_changed: bool = True) -> None:
        with self.lock:
            self.view_generation += 1
            if source_changed:
                self.source_generation += 1
            self.published_frame = None
            self.live_detections = None
            self.display_anchor = None
            self.latest, self.raw = None, None

    def _capture_moved(self, attempt: int) -> None:
        message = f"Window moving; retrying capture ({attempt}/{_CAPTURE_MOVE_ATTEMPTS})"
        self.controller.stop(message, notify=False)
        with self.stop_lock:
            self.command_epoch += 1
            self._cancel_active_probe(message)
            self.live_potion_ticket = None
            self.potion_hud_missing_since = None
            self.arbiter.reset()
            self.sustain = ()
            if self.potter.live:
                self.potter.stop()
            if self.mode in {"live", "pending_arm", "potion_wait", "potion_live"} or (
                self.mode.startswith("probe")
            ):
                self.stop_requested.set()
                self.agent.stop(message)
                self.mode = "capture"
            self._invalidate_view(source_changed=False)
            self.image = None
            with self.lock:
                self.status = {
                    **self.status, "state": str(self.agent.state), "mode": self.mode,
                    "reason": message, "player": None, "target": None,
                    "focused": False, "last_action": "release all",
                }
        if attempt == 1:
            self.note(message)
        if attempt >= _CAPTURE_MOVE_ATTEMPTS:
            self.safe_stop(
                "CAPTURE_WORKER_FAILURE",
                f"Window kept moving during {_CAPTURE_MOVE_ATTEMPTS} capture attempts",
                invalidate_probes=False,
            )

    def _probe_profile(self) -> tuple[dict, dict]:
        if not self.calibration:
            return {}, {}
        context = {
            key: value for key, value in asdict(self.calibration).items()
            if key not in {"capture_verified", "controls_verified"}
        }
        context["configured_title"] = self.config.capture.window_title
        signatures = {action: {"key": getattr(self.config.input, action)}
                      for action in PROBE_ACTIONS}
        for resource in ("hp", "mp"):
            action = f"{resource}_potion"
            bar = self.potter.bars.get(resource)
            if bar is None:
                signatures.pop(action)
            else:
                signatures[action]["hud"] = {
                    "box": asdict(bar.box),
                    "interior": asdict(bar.interior),
                    "reference": hashlib.sha256(bar.image.tobytes()).hexdigest(),
                }
        return context, signatures

    def _save_probes(self) -> None:
        context, signatures = self._probe_profile()
        if context:
            self.probe_store.save(context, signatures, self.probed)

    def _restore_probes(self, *, clear_results: bool = True) -> None:
        context, signatures = self._probe_profile()
        self.probed = self.probe_store.restore(context, signatures) if context else set()
        if clear_results:
            self.probe_results.clear()

    def _probe_snapshot(self) -> dict[str, dict[str, object]]:
        states: dict[str, dict[str, object]] = {}
        for action in sorted(PROBE_ACTIONS):
            states[action] = {
                "required": action in REQUIRED_PROBES,
                "confirmed": action in self.probed,
                "status": "confirmed" if action in self.probed else "not_requested",
            }
        for action, result in self.probe_results.items():
            if result["status"] != "confirmed" or action in self.probed:
                states[action] = {**states[action], **result}
        if self.active_probe:
            states[self.active_probe.action] = {
                **states[self.active_probe.action],
                "status": self.active_probe.phase,
                "id": self.active_probe.id,
                "generation": self.active_probe.generation,
                "instruction": self.active_probe.instruction,
            }
        return states

    def _cancel_active_probe(self, reason: str) -> None:
        active = self.active_probe
        self.probe_generation += 1
        self.active_probe = None
        if active:
            self.probe_results[active.action] = {
                "status": "cancelled",
                "reason": reason,
                "id": active.id,
                "generation": active.generation,
            }

    def _finish_probe(self, active: ProbeState, status: str, reason: str) -> None:
        if self.active_probe != active:
            return
        self.probe_results[active.action] = {
            "status": status,
            "reason": reason,
            "id": active.id,
            "generation": active.generation,
        }
        self.active_probe = None
        self.mode = "capture"
        self.stop_reason = reason

    def _resource_reading(self, resource: str, image: Image) -> BarReading:
        bar = self.potter.bars.get(resource)
        if bar is None:
            return BarReading(None, 0, f"Calibrate the {resource.upper()} bar before probing")
        return bar.read(image, resource)

    def request_probe(self, payload: dict) -> dict[str, object]:
        if self.capture_only:
            raise ValueError("Capture-only session: gameplay controls are unavailable")
        if self.alarm.snapshot()["active"]:
            raise ValueError("Acknowledge the active alarm before starting a control probe")
        action = str(payload.get("action", ""))
        if action not in PROBE_ACTIONS:
            raise ValueError("Invalid control probe")
        if self.active_probe is not None:
            raise ValueError("A probe is already active; confirm, reject, or stop it first")
        if self.calibrating:
            raise ValueError("Return to live view before issuing gameplay input")
        if not self.hwnd or not self.calibration or not self.calibration.capture_verified:
            raise ValueError("Crop and verify the Game view before input")
        window = self.windows.get(self.hwnd)
        if self.config.capture.window_title.casefold() not in window.title.casefold():
            raise ValueError("Input is restricted to the configured game window title")
        if self.windows.outranks_us(window.hwnd):
            raise ValueError(ELEVATED_GAME_REASON)
        resource = {"hp_potion": "hp", "mp_potion": "mp"}.get(action)
        baseline_percent: float | None = None
        if resource:
            if self.image is None:
                raise ValueError(f"Capture a fresh {resource.upper()} bar frame before probing")
            reading = self._resource_reading(resource, self.image)
            if reading.percent is None or reading.confidence < 0.9:
                raise ValueError(
                    f"{resource.upper()} bar is unreadable; recalibrate or return to live view"
                )
            if reading.percent >= self.config.probe.potion_full_percent:
                raise ValueError(
                    f"{resource.upper()} is full; lower it below "
                    f"{self.config.probe.potion_full_percent:g}% first"
                )
            baseline_percent = reading.percent
        self.probed.discard(action)
        self._save_probes()
        self._clear_stop_banner()
        self.safe_stop(
            "CALIBRATION",
            "Preparing bounded input; focus the Game view within 3 seconds",
            invalidate_probes=False,
        )
        self.stop_requested.clear()
        probe_id = self.next_probe_id
        self.next_probe_id += 1
        instruction = (
            "stand away from portals and ropes"
            if action == "up"
            else "Click the game window now; F8 cancels"
        )
        self.active_probe = ProbeState(
            probe_id,
            self.controller.generation,
            action,
            "countdown",
            instruction,
            resource=resource,
            baseline_percent=baseline_percent,
        )
        self.mode = "probe_wait"
        self.pending_at = time.perf_counter() + 3
        self.combat_evidence.start(f"probe:{action}")
        return {
            "mode": self.mode,
            "id": probe_id,
            "generation": self.active_probe.generation,
            "instruction": instruction,
        }

    def confirm_probe(self, payload: dict) -> dict[str, object]:
        active = self.active_probe
        probe_id = payload.get("id")
        generation = payload.get("generation")
        if active is None:
            return {"confirmed": False, "reason": "No active probe to confirm"}
        if probe_id != active.id or generation != active.generation:
            return {"confirmed": False, "reason": "Probe confirmation is stale"}
        if active.phase != "awaiting_confirmation":
            return {"confirmed": False, "reason": "Probe is not awaiting manual confirmation"}
        self.probed.add(active.action)
        self._save_probes()
        self.combat_evidence.record("observed_effect", f"Operator confirmed {active.action}",
                                    probe_id=active.id, generation=active.generation)
        self._finish_probe(active, "confirmed", "Operator confirmed the observed probe effect")
        self.safe_stop("PROBE_COMPLETE", "Control probe confirmed")
        return {"confirmed": True, "action": active.action}

    def reject_probe(self, payload: dict) -> dict[str, object]:
        active = self.active_probe
        if active is None:
            return {"rejected": False, "reason": "No active probe to reject"}
        if payload.get("id") != active.id or payload.get("generation") != active.generation:
            return {"rejected": False, "reason": "Probe rejection is stale"}
        self._finish_probe(active, "rejected", "Operator rejected the observed probe effect")
        self.safe_stop("PROBE_COMPLETE", "Control probe rejected")
        return {"rejected": True, "action": active.action}

    def _handle_probe_outcome(self, outcome: Any) -> None:
        active = self.active_probe
        if (
            active is None
            or outcome.ticket != active.ticket
            or outcome.generation != active.generation
        ):
            return
        if not outcome.result.endswith("completed"):
            self._finish_probe(active, "failed", "Probe key action did not complete")
            self.safe_stop("PROBE_COMPLETE", "Control probe failed")
            return
        if active.resource is None:
            self.active_probe = replace(active, phase="awaiting_confirmation")
            self.mode = "probe_confirm"
            self.stop_reason = "Observe the one key press, then confirm or reject it"
            return
        self.active_probe = replace(
            active,
            phase="awaiting_effect",
            pressed_sequence=self.sequence,
            pressed_at=outcome.finished_at,
            deadline=outcome.finished_at + self.config.probe.potion_effect_seconds,
        )
        self.mode = "probe_effect"
        self.stop_reason = f"Waiting for a fresh {active.resource.upper()} bar gain"

    def _advance_potion_probe(self, image: Image, now: float) -> None:
        active = self.active_probe
        if active is None or active.phase != "awaiting_effect":
            return
        assert active.resource is not None
        assert active.pressed_sequence is not None
        assert active.pressed_at is not None
        assert active.deadline is not None
        if now >= active.deadline:
            self._finish_probe(
                active, "failed", "No sufficient potion-bar gain before the probe deadline"
            )
            self.safe_stop("PROBE_COMPLETE", "Potion probe timed out")
            return
        if self.sequence <= active.pressed_sequence or now <= active.pressed_at:
            return
        reading = self._resource_reading(active.resource, image)
        if reading.percent is None or reading.confidence < 0.9:
            self._finish_probe(
                active, "failed", f"{active.resource.upper()} bar is unreadable after probe"
            )
            self.safe_stop("PROBE_COMPLETE", "Potion probe could not read a fresh bar")
            return
        assert active.baseline_percent is not None
        if reading.percent - active.baseline_percent >= self.config.probe.potion_min_gain_percent:
            self.combat_evidence.record(
                "observed_bar_gain", f"{active.resource.upper()} probe gain",
                before=active.baseline_percent, after=reading.percent,
                probe_id=active.id, generation=active.generation,
            )
            self.probed.add(active.action)
            self._save_probes()
            self._finish_probe(active, "confirmed", "Fresh matching potion-bar gain confirmed")
            self.safe_stop("PROBE_COMPLETE", "Potion probe confirmed")

    def note(self, reason: str) -> None:
        with self.lock:
            self.history.appendleft({"time": round(time.time(), 3), "reason": reason})

    def _input_observation(self) -> InputObservation | None:
        # Called under the input lock: read immutable frame metadata, never take app.lock.
        frame = self.processing_frame
        if frame is None:
            if self.mode in {"live", "navigation"}:
                return InputObservation(-1., -1., self.source_generation, self.view_generation, -1)
            return None
        source = frame.get("source_generation", self.source_generation)
        view = frame.get("view_generation", self.view_generation)
        captured = frame.get("capture_clock")
        if ((source, view) != (self.source_generation, self.view_generation)
                or not isinstance(captured, (int, float)) or not math.isfinite(captured)
                or not isinstance(frame.get("sequence"), int)):
            return InputObservation(-1., -1., self.source_generation, self.view_generation, -1)
        return InputObservation(captured, captured + .5, source, view, frame["sequence"])

    def _input_safe(self) -> bool:
        reason = self._input_block_reason()
        if reason:
            self.input_refusal = {"reason": reason, "observed_clock": time.perf_counter(),
                                  "processing": self.processing_frame,
                                  "window": self.refused_window}
        if reason and self.mode == "navigation":
            # Keep the actual controller callback's refusal even if a fresh frame arrives
            # before its stop callback. Rechecking then can erase the cause of the stop.
            self.navigation.last_input_refusal = reason
        return reason is None

    def _input_block_reason(self) -> str | None:
        if overlay := getattr(self, "overlay", None):
            if reason := overlay.block_reason():
                return reason
        if farm := self.farming:
            if reason := farm.checkpoint_reason(time.perf_counter()):
                return reason
        if self.mode == "navigation":
            if reason := self.navigation.feedback_block_reason():
                return reason
        if reason := self._input_setup_block_reason():
            return reason
        window = self.windows.get(self.hwnd)
        if not window.focused:
            self.refused_window = asdict(window)
            return "Click the actual game window before the countdown ends"
        region = self.calibration.crop.translated(window.client.x, window.client.y)
        if not self.windows.unobscured(window.hwnd, region):
            return "Game view is covered by another window; move the covering window away"
        return None

    def _input_setup_block_reason(self) -> str | None:
        """Stable setup gates; focus and overlay leases belong to dispatch."""
        if self.area_editing:
            return "Area editing: gameplay input is stopped"
        if self.capture_only:
            return "Capture-only session: gameplay controls are unavailable"
        if not self.hwnd or not self.calibration:
            return "Select and crop the game window before input"
        if not self.calibration.capture_verified:
            return "Confirm capture before issuing gameplay input"
        try:
            window = self.windows.get(self.hwnd)
        except (OSError, RuntimeError):
            return "Game window unavailable; reconnect the game"
        if self.config.capture.window_title.casefold() not in window.title.casefold():
            return "Input is restricted to the configured game window title"
        if not self.calibration.valid_for(window):
            return "Game window size or DPI changed; recalibrate and confirm capture"
        if self.windows.outranks_us(window.hwnd):
            return ELEVATED_GAME_REASON
        return None

    def _controller_stop(self, code: str, message: str) -> None:
        if code == "EMERGENCY_STOP" and self.alarm.snapshot()["active"]:
            self.acknowledge_stop()
            return
        if code == "FOCUS_LOSS":
            # The watchdog only sees a failed gate; name which one failed.
            try:
                detail = ((self.input_refusal or {}).get("reason")
                          or (self.navigation.last_input_refusal
                              if self.mode == "navigation" else None)
                          or self._input_block_reason())
            except Exception as error:
                detail = str(error)
            if detail:
                if detail == CHECKPOINT_STOP:
                    code, message = "FARMING_STOP", detail
                elif (self.mode == "navigation"
                      and detail == "Player recognition recovery timed out"):
                    code, message = "PLAYER_UNCERTAIN", detail
                else:
                    message = f"{message}: {detail}"
        self.safe_stop(code, message)

    def safe_stop(
        self,
        code: str,
        message: str,
        *,
        invalidate_probes: bool | None = None,
        preserve_completed_probe: bool = False,
    ) -> StopRecord:
        if code == "POLICY_STOP" and self.farming is not None:
            code = "FARMING_STOP"
        reason = STOP_REASONS.get(code)
        if reason is None:
            raise ValueError(f"Unknown stop code: {code}")
        self.live_potion_ticket = None
        self.potion_hud_missing_since = None
        self.arbiter.reset()
        self.sustain = ()
        self.farming = None
        if not (preserve_completed_probe and self.active_probe
                and self.active_probe.phase == "awaiting_confirmation"):
            self._cancel_active_probe(message)
        # This must happen before any recorder, encoder, status, or audio work.
        self.controller.stop(message, code=code, notify=False)
        self.combat_evidence.stop(message)
        if hasattr(self, "navigation"):
            self.navigation.cancel(message)
        self.rotating = False
        with self.stop_lock:
            self.command_epoch += 1
            if self.stop_record is not None:
                self.potter.stop()
                self.agent.stop(message)
                self.mode, self.stop_reason = "capture", message
                self.last_action = "release all"
                if (
                    self.stop_record.severity is StopSeverity.SILENT
                    and reason.severity is StopSeverity.ALARM
                ):
                    self.stop_record = replace(
                        self.stop_record,
                        code=code,
                        severity=StopSeverity.ALARM,
                        message=message,
                        acknowledged=False,
                    )
                    serialized = asdict(self.stop_record)
                    with self.lock:
                        self.status = {**self.status, "reason": message, "stop": serialized}
                        if self.history and self.history[0].get("id") == self.stop_record.id:
                            self.history[0] = {"reason": message, **serialized}
                    self.alarm.start(self.stop_record.id)
                elif self.stop_record.severity is StopSeverity.SILENT:
                    self.stop_record = replace(self.stop_record, code=code, message=message)
                    serialized = asdict(self.stop_record)
                    with self.lock:
                        self.status = {**self.status, "reason": message, "stop": serialized}
                        if self.history and self.history[0].get("id") == self.stop_record.id:
                            self.history[0] = {"reason": message, **serialized}
                return self.stop_record
            cutoff = max(self.sequence - 1, self.encoder.snapshot()["accepted_sequence"])
            try:
                encoding = self.encoder.flush_through(cutoff, timeout=0.5)
            except Exception as error:
                encoding = {"complete": False, "reason": str(error)}
            try:
                clip = self.recorder.trigger(
                    message, time.perf_counter(), close=not self.recorder.manual
                )
                clip_path = str(clip)
            except Exception:
                clip_path = None
            self.potter.stop()
            self.agent.stop(message)
            self.mode, self.stop_reason = "capture", message
            self.last_action = "release all"
            if (invalidate_probes if invalidate_probes is not None else reason.invalidate_probes):
                if self.calibration:
                    self.calibration.controls_verified = False
            record = StopRecord(
                uuid.uuid4().hex,
                code,
                reason.severity,
                message,
                round(time.time(), 3),
                clip_path,
                reason.severity is StopSeverity.SILENT,
                bool(encoding.get("complete")),
            )
            self.stop_record = record
            serialized = asdict(record)
            with self.lock:
                self.history.appendleft({"reason": message, **serialized})
                self.status = {
                    **self.status,
                    "state": "IDLE",
                    "mode": "capture",
                    "reason": message,
                    "stop": serialized,
                }
            if reason.severity is StopSeverity.ALARM:
                self.alarm.start(record.id)
            return record

    def _reacquire(self, player, now: float) -> str | None:
        """Bounded recovery for a live or dry-run frame without fresh player identity.

        Returns why the policy must not run this frame (keys stay released), or None.
        """
        fresh = (player is not None and not player.tracked
                 and player.confidence >= self.config.perception.confidence)
        step = self.reacquisition.step(
            (getattr(player, "identity", None) or player.template.removesuffix(":tag-only"))
            if fresh else None, now)
        live = self.mode == "live"
        if step.state in {"pass", "ok"}:
            return None
        if step.state == "stop":
            self._stop("PLAYER_UNCERTAIN", step.reason)
            return step.reason
        if step.state == "pause" and live and not self.controller.suspend():
            reason = "Cannot suspend combat input for recognition recovery"
            self._stop("INPUT_BACKEND_FAILURE", reason)
            return reason
        if step.state == "resume":
            if not live or self.controller.resume():
                self.reacquisition.resumed()
                self.note(step.reason)
                return None
            step.reason = "Player reacquired; waiting for released keys before resuming"
        self.last_action = "release (recognition recovery)"
        self.policy_outcome = {"status": "not_sent"}
        return step.reason

    def _stop(self, code: str, message: str) -> StopRecord:
        return self.safe_stop(code, message)

    def _clear_stop_banner(self) -> None:
        self.input_refusal, self.refused_window = None, None
        with self.stop_lock:
            self.stop_record = None
            with self.lock:
                self.status.pop("stop", None)

    def acknowledge_stop(
        self, incident_id: str | None = None, *, require_id: bool = False
    ) -> dict[str, object]:
        with self.stop_lock:
            alarm = self.alarm.snapshot()
            current_id = (
                alarm["incident_id"] if alarm["active"]
                else self.stop_record.id if self.stop_record else None
            )
            if require_id and (not isinstance(incident_id, str) or incident_id != current_id):
                return {
                    "acknowledged": False,
                    "reason": "Alarm changed or ID missing; acknowledge the displayed alarm",
                    "incident_id": current_id,
                }
            acknowledged = self.alarm.acknowledge()
            if self.stop_record is None:
                return {"acknowledged": acknowledged, "reason": "No active stop incident"}
            self.stop_record = replace(self.stop_record, acknowledged=True)
            serialized = asdict(self.stop_record)
            with self.lock:
                self.status = {**self.status, "stop": serialized}
                if self.history and self.history[0].get("id") == self.stop_record.id:
                    self.history[0] = {"reason": self.stop_record.message, **serialized}
            return {"acknowledged": True, "stop": serialized}

    def start_capture_worker(self) -> bool:
        with self.worker_lock:
            if self.closed.is_set() or (self.worker and self.worker.is_alive()):
                return False
            self.worker = threading.Thread(target=self._run, name="capture", daemon=True)
            self.worker.start()
            return True

    def restart_capture(self) -> dict[str, object]:
        with self.stop_lock:
            if self.alarm.snapshot()["active"]:
                raise RuntimeError("Acknowledge the active alarm before restarting capture")
            self.controller.stop("Capture restart", notify=False)
            self.probed.clear()
            if self.calibration:
                self.calibration.capture_verified = False
                self.calibration.controls_verified = False
            self._cancel_active_probe("Capture worker restarted")
            self.stop_requested.set()
        with self.worker_lock:
            if self.worker and self.worker.is_alive():
                return {"restarted": False, "reason": "Capture worker is still running"}
            self._drain_pending_commands()
            self._invalidate_view()
            started = self.start_capture_worker()
        return {"restarted": started, "mode": "capture", "input_enabled": self.controller.enabled}

    def _drain_pending_commands(self) -> None:
        while True:
            try:
                _, _, future = self.commands.get_nowait()
            except queue.Empty:
                return
            future.cancel()

    def _command(self, name: str, payload: dict) -> Any:
        if self.area_editing and name in FRESH_FRAME_COMMANDS:
            raise ValueError("Finish area editing before starting input or preview decisions")
        context = payload.get("_context")
        if context is not None:
            context.validate(
                self.command_epoch,
                max_age=FRESH_FRAME_SECONDS if name in FRESH_FRAME_COMMANDS else 10,
            )
            payload = {key: value for key, value in payload.items() if key != "_context"}
            # Versioned UI starts use the same selection preconditions as status.
            # Focus/occlusion and input leases are still checked at dispatch time.
            activity = {
                "dry_run": "preview", "arm": "combat", "autopotter_live": "potions",
            }.get(name)
            if name == "probe":
                activity = f"probe:{payload.get('action', '')}"
            if activity:
                gate = self.snapshot()["readiness"].get(activity)
                if gate is None or not gate["ready"]:
                    raise ValueError(gate["reason"] if gate else "Invalid control probe")
        if name == "pose_collection":
            if not isinstance(payload.get("enabled", False), bool):
                raise ValueError("enabled must be a boolean")
            if not payload.get("enabled", False):
                return self.pose_collection.configure()
            identity = str(payload.get("identity", ""))
            if identity not in {tag.name for tag in self.detector.nametags}:
                raise ValueError("Select a taught name before collecting poses")
            return self.pose_collection.configure(identity, str(payload.get("outfit", "")))
        if name == "range_profile":
            profile_name = payload.get("profile")
            range_profile(profile_name)
            self._stop("OPERATOR_STOP", "Weapon range change; input stopped")
            agent_config = replace(self.configured_agent, range_profile=profile_name)
            self.range_store.save(profile_name)
            self.config = replace(self.config, agent=agent_config)
            self.agent = Agent(agent_config, self.config.perception.confidence)
            self.note("Weapon range saved; bot remains Off")
            return {"profile": profile_name, "minimum_px": agent_config.attack_min_range,
                    "maximum_px": agent_config.attack_range}
        if name in {"attach", "manual", "reset_crop", "crop"}:
            self._invalidate_view()
        if self.capture_only and name in {"arm", "probe", "confirm_controls"}:
            raise ValueError("Capture-only session: gameplay controls are unavailable")
        if name == "probe":
            return self.request_probe(payload)
        if name == "confirm_controls":
            raise ValueError("Use the per-probe confirmation controls")
        if name == "nav_reload_code":
            from .navigation_reload import reload_navigation
            return reload_navigation(self)
        if name == "nav_go":
            return self.navigation.go(
                context, str(payload.get("target", "")), payload.get("opt_in") is True
            )
        if name == "nav_edge":
            return self.navigation.edge(context, payload.get("opt_in") is True)
        if name == "nav_walk":
            return self.navigation.walk(context, payload.get("dx", -80),
                                        payload.get("opt_in") is True)
        if name in {"nav_refresh", "nav_preview", "nav_start"}:
            if name == "nav_start":
                return self.navigation.start(context, payload.get("opt_in") is True)
            self._stop("OPERATOR_STOP", "Navigation route preview; gameplay stopped")
            if name == "nav_refresh":
                return self.navigation.refresh()
            return self.navigation.preview(str(payload.get("origin", "")),
                                           str(payload.get("target", "")))
        if name == "autopotter_calibrate":
            self._stop("CALIBRATION", "HUD calibration; potion preview stopped")
            if not self.calibration or not self.calibration.capture_verified or not self.hwnd:
                raise ValueError("Verify capture before calibrating HP/MP bars")
            image, window, region = self.frozen[payload["id"]]
            if (
                not window
                or window.hwnd != self.hwnd
                or region != self.region
                or not self.calibration.valid_for(self.windows.get(self.hwnd))
            ):
                raise ValueError("Frozen screenshot no longer matches the current capture")
            self.potter.calibrate(str(payload["resource"]), image, self._roi(payload, image))
            self._restore_probes()
            return self.potter.snapshot()
        if name == "autopotter_settings":
            self._stop("OPERATOR_STOP", "Potion settings changed; input stopped")
            self.potter.configure(
                **{key: float(payload[key]) for key in ("hp_threshold", "mp_threshold", "cooldown")}
            )
            return self.potter.snapshot()
        if name == "autopotter_live":
            if self.capture_only:
                raise ValueError("Capture-only session: gameplay controls are unavailable")
            if self.alarm.snapshot()["active"]:
                raise ValueError("Acknowledge the active alarm before starting live potions")
            if self.calibrating or self.image is None:
                raise ValueError("Return to a live screenshot before starting live potions")
            if not self.calibration or not self.calibration.capture_verified:
                raise ValueError("Verify capture before starting live potions")
            if self.active_probe is not None:
                raise ValueError("Finish the active control probe before starting live potions")
            resources = [r for r in ("hp", "mp") if self.potter.settings[f"{r}_threshold"] > 0]
            if not resources:
                raise ValueError("Set at least one potion threshold above zero")
            for resource in resources:
                reading = self._resource_reading(resource, self.image)
                if reading.percent is None or reading.confidence < 0.9:
                    raise ValueError(f"Calibrate a readable {resource.upper()} bar first")
                if f"{resource}_potion" not in self.probed:
                    raise ValueError(f"Verify the {resource.upper()} potion control first")
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                raise ValueError("Release the emergency stop key before starting live potions")
            self._clear_stop_banner()
            self._stop("OPERATOR_STOP", "Preparing live potions; focus the game within 3 seconds")
            with self.stop_lock:
                if context is not None:
                    context.validate(self.command_epoch - 1)
                self.stop_requested.clear()
                self.mode = "potion_wait"
                self.pending_at = time.perf_counter() + 3
                self.combat_evidence.start("potions")
            return {"mode": self.mode}
        if name == "autopotter_start":
            if self.calibrating or self.image is None:
                raise ValueError("Return to a live screenshot before starting potion preview")
            if not self.calibration or not self.calibration.capture_verified:
                raise ValueError("Verify capture before starting potion preview")
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                raise ValueError("Release the emergency stop key before starting preview")
            self._stop("OPERATOR_STOP", "Potion preview: gameplay input disabled")
            self.stop_requested.clear()
            self.potter.start()
            return self.potter.snapshot()
        if name == "autopotter_stop":
            self._stop("OPERATOR_STOP", "Autopotter stopped")
            return self.potter.snapshot()
        if name in {"attach", "manual", "reset_crop", "freeze", "crop", "template"}:
            self._stop("CALIBRATION", "Calibration: gameplay input disabled")
        if name == "stop":
            self._stop("OPERATOR_STOP", "Operator stopped the agent")
            return {"ok": True}
        if name == "resume_view":
            self.calibrating = False
            return {"ok": True}
        if name == "template":
            if not self.calibration or not self.calibration.capture_verified:
                raise ValueError("Verify capture before teaching sprite templates")
            image, window, region = self.frozen[payload["id"]]
            if not window or self.hwnd != window.hwnd or not self.region or region != self.region:
                raise ValueError("Frozen screenshot no longer matches the current Game crop")
            roi = self._roi(payload, image)
            kind = payload["kind"]
            if kind not in ("player", "monster", "nametag"):
                raise ValueError("Template kind must be player, monster or nametag")
            sprite = image[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width].copy()
            self.detector.validate(sprite)
            meta = self._nametag_meta(image, roi, sprite) if kind == "nametag" else None
            key = uuid.uuid4().hex
            directory = self.data / "templates" / kind
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{key}.png"
            path.write_bytes(png(sprite))
            if meta is not None:
                path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
            sources = self.data / "templates" / "sources"
            sources.mkdir(parents=True, exist_ok=True)
            (sources / f"{key}.png").write_bytes(png(image))
            (sources / f"{key}.json").write_text(
                json.dumps({"kind": kind, "box": asdict(roi), "window": asdict(window)}),
                encoding="utf-8",
            )
            self.detector.add(path, kind)
            self.note(f"Added {kind} template from screenshot pixels")
            return {"path": str(path), "variants": len(self.detector.templates)}
        if name == "reload_templates":
            self._stop("CALIBRATION", "Reloading templates; input disabled")
            self.detector.reload()
            return {"variants": len(self.detector.templates), "catalog": self.detector.catalog_info}
        if name == "dry_run":
            self._stop("DRY_RUN_STOP", "Dry run: no keyboard input")
            farming = Farming(payload["farming"]) if "farming" in payload else None
            if farming and not all(r in self.potter.bars for r in ("hp", "mp")):
                raise ValueError("Farming needs calibrated HP and MP bars")
            if farming and not farming.pet_recovery and not farming.no_consumables:
                if not all(f"{r}_potion" in self.probed for r in ("hp", "mp")):
                    raise ValueError("No-pet farming needs verified HP and MP potion keys")
                if any(self.potter.settings[f"{r}_threshold"] < farming.settings[f"{r}_threshold"]
                       for r in ("hp", "mp")):
                    raise ValueError("Potion thresholds must cover farming recovery thresholds")
            self._prepare_rotation((not farming.single_platform) if farming else
                                   payload.get("rotate") is True)
            with self.stop_lock:
                if self.area_editing:
                    raise ValueError("Finish area editing before starting preview decisions")
                if context is not None:
                    context.validate(self.command_epoch - 1)
                self.stop_requested.clear()
                self.agent.start()
                self.mode = "dry_run"
                self._clear_stop_banner()
                self.combat_evidence.start("preview")
            if self.config.recording.auto:
                self.recorder.start("dry-run")
            return {"mode": self.mode}
        if name == "arm":
            with self.stop_lock:
                if self.area_editing:
                    raise ValueError("Finish area editing before arming combat")
                if self.alarm.snapshot()["active"]:
                    raise ValueError("Acknowledge the active alarm before arming combat")
            self.safe_stop(
                "CALIBRATION",
                "Preparing bounded input; focus the Game view within 3 seconds",
                invalidate_probes=False,
            )
            if self.calibrating:
                raise ValueError("Return to live view before issuing gameplay input")
            if not self.hwnd or not self.calibration or not self.calibration.capture_verified:
                raise ValueError("Crop and verify the Game view before input")
            window = self.windows.get(self.hwnd)
            if self.config.capture.window_title.casefold() not in window.title.casefold():
                raise ValueError("Input is restricted to the configured game window title")
            missing = sorted(REQUIRED_PROBES - self.probed)
            if missing:
                raise ValueError("Confirm required probes first: " + ", ".join(missing))
            farming = Farming(payload["farming"]) if "farming" in payload else None
            if farming and not all(r in self.potter.bars for r in ("hp", "mp")):
                raise ValueError("Farming needs calibrated HP and MP bars")
            if farming and not farming.pet_recovery and not farming.no_consumables:
                if not all(f"{r}_potion" in self.probed for r in ("hp", "mp")):
                    raise ValueError("No-pet farming needs verified HP and MP potion keys")
                if any(self.potter.settings[f"{r}_threshold"] < farming.settings[f"{r}_threshold"]
                       for r in ("hp", "mp")):
                    raise ValueError("Potion thresholds must cover farming recovery thresholds")
            self._prepare_rotation((not farming.single_platform) if farming else
                                   payload.get("rotate") is True)
            with self.stop_lock:
                if self.alarm.snapshot()["active"]:
                    raise ValueError("Acknowledge the active alarm before arming combat")
                if self.area_editing:
                    raise ValueError("Finish area editing before arming combat")
                if context is not None:
                    context.validate(self.command_epoch - 1)
                self.stop_requested.clear()
                self._clear_stop_banner()
                self.farming = farming
                self.mode = "pending_arm"
                self.pending_at = time.perf_counter() + 3
                self.combat_evidence.start("combat")
            return {"mode": self.mode, "instruction": "Click the game window now; F8 cancels"}
        if name == "frozen_png":
            return png(self.frozen[payload["id"]][0])
        if name == "windows":
            return [asdict(window) for window in self.windows.list()]
        if name == "focus_game":
            if self.mode != "capture" or self.active_probe is not None:
                raise ValueError("Stop gameplay before requesting focus")
            if not self.hwnd:
                raise ValueError("Connect the game window before requesting focus")
            window = self.windows.get(self.hwnd)
            if self.config.capture.window_title.casefold() not in window.title.casefold():
                raise ValueError("Attached window does not match the configured game")
            fallback = payload.get("click_fallback", False)
            if type(fallback) is not bool:
                raise ValueError("click_fallback must be boolean")
            focused = (self.windows.focus(self.hwnd, click_fallback=True) if fallback
                       else self.windows.focus(self.hwnd))
            return {"focused": focused, "input_sent": False,
                    "focus_click_allowed": fallback}
        if name == "connect_saved_window":
            connected = self.connect_saved_window()
            return {
                "connected": connected,
                "reason": "Saved game connected; waiting for player or HUD recognition" if connected
                else "No unique matching saved game window; open the game or use Advanced setup",
            }
        if name == "attach":
            window = self.windows.get(int(payload["hwnd"]))
            self.hwnd, self.manual, self.calibration = window.hwnd, None, None
            path = self.data / "calibration.json"
            if path.exists():
                saved = Calibration.load(path)
                if saved.valid_for(window):
                    self.calibration = saved
            self.image = None
            self.calibrating = False
            self.probed.clear()
            self._restore_probes()
            self.frozen.clear()
            self.note(f"Attached to {window.title}; calibration/input unverified")
            return {"ok": True}
        if name == "manual":
            self.manual = Rect(**{key: int(payload[key]) for key in ("x", "y", "width", "height")})
            self.hwnd, self.calibration, self.image = None, None, None
            self.calibrating = False
            self.probed.clear()
            self.frozen.clear()
            self.note("Manual desktop region; gameplay input unavailable")
            return {"ok": True}
        if name == "reset_crop":
            self.calibration = None
            self.image = None
            self.frozen.clear()
            self.calibrating = False
            self.probed.clear()
            return {"ok": True}
        if name == "freeze":
            latest = self.preview.frozen(self._preview_source().id)
            if self.preview.worker is not None and latest is None:
                raise ValueError("No current preview screenshot")
            image, window, region = latest or (self.image, self.window, self.region)
            if image is None or region is None:
                raise ValueError("No current screenshot")
            key = uuid.uuid4().hex
            self.calibrating = True
            self.frozen[key] = (image.copy(), window, region)
            while len(self.frozen) > 4:
                del self.frozen[next(iter(self.frozen))]
            return {"id": key, "width": image.shape[1], "height": image.shape[0]}
        if name == "crop":
            image, window, region = self.frozen[payload["id"]]
            if window is None or self.hwnd != window.hwnd:
                raise ValueError("Select a target window before cropping")
            current = self.windows.get(self.hwnd)
            if current.client != window.client or current.dpi != window.dpi:
                raise ValueError("Window changed since frozen frame; freeze a new screenshot")
            roi = self._roi(payload, image)
            roi = roi.translated(region.x - window.client.x, region.y - window.client.y)
            self.calibration = Calibration(
                window.title, window.client.width, window.client.height, window.dpi, roi
            )
            self.calibration.save(self.data / "calibration.json")
            self.image = None
            self.calibrating = False
            self.probed.clear()
            self.note("Game-view crop saved; inspect the live pixels before confirming")
            return {"ok": True}
        if name == "confirm_capture":
            if self.calibrating or self.image is None or not self.calibration or not self.hwnd:
                raise ValueError("Crop the Game view and inspect a live screenshot first")
            if not self.calibration.valid_for(self.windows.get(self.hwnd)):
                raise ValueError("Window changed; recalibrate")
            self.calibration.capture_verified = True
            self._restore_probes()
            self.calibration.save(self.data / "calibration.json")
            path = self._save()
            self.note("Capture confirmed by operator; evidence screenshot saved")
            return {"path": path}
        if name in POSITION_COMMANDS:
            if self.mode in {"navigation", "navigation_wait"}:
                self._stop("OPERATOR_STOP", "Position change canceled navigation")
            return self._position_command(name, payload)
        if name == "save":
            return {"path": self._save()}
        if name == "record":
            if self.recorder.full:
                return {"path": str(self.recorder.stop_full()), "recording": False}
            seconds = payload.get("seconds")
            if seconds is not None and (
                isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not 0 < seconds <= 600
            ):
                raise ValueError("Recording length must be between 0 and 600 seconds")
            path = self.recorder.start_full(seconds)
            return {"path": str(path), "recording": True}
        if name == "clip":
            return {"path": str(self.recorder.trigger("Operator saved clip", time.perf_counter()))}
        raise ValueError(f"Unknown command: {name}")

    def _nametag_meta(self, image: Image, roi: Rect, sprite: Image) -> dict:
        """Record other copies of the name in this frame (HUD, party list) as fixed decoys."""
        text, text_top, (left, top) = nametag_parts(sprite)
        tag = NameTag("teaching", text, text_top)
        floor = max(0.5, self.config.perception.nametag_confidence - 0.15)
        matches = self.detector.nametag_matches(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), tag, floor)
        decoys = [
            [match.box.x, match.box.y]
            for match in matches
            if abs(match.box.x - roi.x - left) > 4 or abs(match.box.y - roi.y - top) > 4
        ]
        return {
            "player_size": list(tag.player_size),
            "decoys": decoys,
            "frame": [image.shape[1], image.shape[0]],
        }

    def _prepare_rotation(self, enabled: bool) -> None:
        """Opt-in platform rotation needs a tracked map with two round-trip platforms."""
        self.rotating = False
        self.rotation.reset("Rotation off" if not enabled else "Waiting for a clear platform")
        if not enabled:
            return
        self.navigation.refresh()
        if len(routable(self.navigation.graph)) < 2:
            raise ValueError("Rotation needs two platforms with recorded round-trip routes")
        self.rotating = True

    def _rotate(self, decision: Decision, observation, now: float) -> str | None:
        """After the clear time with no same-platform target, hand combat to navigation."""
        if not self.rotating:
            return None
        nav, f = self.navigation, self.navigation.feedback
        known = bool(nav.graph and f and observation.player is not None)
        visible = visible_by_surface(
            nav.graph, f.feet, observation.player, observation.monsters,
            self.config.perception.confidence,
        ) if known and f.feet else {}
        platforms = routable(nav.graph) if known else []
        if (known and decision.state == "SEARCH" and f.surface not in platforms
                and f.surface not in nav.graph.excluded
                and any(p["id"] == f.surface for p in nav.graph.profile["platforms"])):
            # A clear platform without a proven way back is still left over proven moves.
            platforms = [*platforms, f.surface]
        edges = {}
        if decision.state == "SEARCH" and f.surface in platforms:
            for key in platforms:
                try:
                    edges[key] = len(nav.graph.plan(f.surface, key, trusted_only=True).edges)
                except ValueError:
                    pass  # Beyond the route budget from here; never chosen.
            platforms = [key for key in platforms if key in edges or key == f.surface]
        target = self.rotation.step(
            now, searching=decision.state == "SEARCH", surface=f.surface if known else None,
            platforms=platforms, visible=visible, edges=edges,
        )
        if target is None:
            return None
        name = nav.graph.nodes[target].get("name", target)
        if self.mode == "dry_run":
            return f"dry run: platform clear; would move to {name}"
        for ticket, lane in tuple(self.arbiter.in_flight.items()):
            if lane == "combat":
                self.controller.cancel_ticket(ticket)
        blocker = nav.handoff(target, now)
        if blocker:
            self._stop("POLICY_STOP", blocker)
            return blocker
        self.combat_evidence.record("decision", f"rotate to {target}", action="navigation")
        return f"Platform clear; moving to {name}"

    def resume_combat(self, surface: str, now: float) -> None:
        """Navigation settled on the rotation destination; fight there."""
        self.rotation.arrived(surface, now)
        self.mode = "live"
        self.agent.start()
        self.policy_outcome = {"status": "not_sent"}
        self.note(f"Arrived on {surface}; combat resumed")

    def _start_sustain(self) -> None:
        """Let live combat press the potions whose bar, threshold and probe are all ready."""
        self.arbiter.reset()
        if self.farming is not None:
            self.farming.start(time.perf_counter())
            if self.farming.pet_recovery or self.farming.no_consumables:
                self.sustain = ()
                self.potter.stop()
                return
        self.sustain = tuple(
            resource for resource in ("hp", "mp")
            if resource in self.potter.bars and f"{resource}_potion" in self.probed
            and self.potter.settings[f"{resource}_threshold"] > 0
        )
        if self.sustain:
            self.potter.start(live=True)
            self.note("Live combat sustain: " + ", ".join(r.upper() for r in self.sustain))

    def _arbitrate(
        self, combat: Action, suggestion: str | None, *, renew_movement: bool = False,
    ) -> int | str:
        """Queue the arbiter's choice; return the combat ticket or why combat was not sent."""
        farm = self.farming
        if farm and farm.started is not None:
            if farm.feed_ticket is not None:
                if farm.feed_ticket in self.arbiter.in_flight:
                    return "deferred: pet food in flight"
                farm.feed_ticket = None
            if farm.next_feed is not None and time.perf_counter() >= farm.next_feed:
                self.controller.release_movement()
                if self.arbiter.in_flight:
                    return "deferred: waiting to feed pet"
                submitted = self.controller.submit(Action(
                    "pet_food", min(.1, self.config.input.max_action_seconds),
                ))
                if not isinstance(submitted, int):
                    self._stop("INPUT_BACKEND_FAILURE", f"Pet food not queued: {submitted}")
                    return submitted
                self.arbiter.submitted(submitted, "pet_food")
                farm.feed_ticket = submitted
                farm.next_feed = time.perf_counter() + farm.settings["feed_seconds"]
                self.combat_evidence.record("queued", "pet_food", ticket=submitted)
                return "deferred: pet food queued; effect unconfirmed"
        if combat.kind in {"attack", "skill"}:
            for ticket in self.controller.cancel_movement_plans():
                self.arbiter.finished(ticket)
        choice = self.arbiter.choose(
            sustain=suggestion if suggestion in self.sustain else None, combat=combat
        )
        if choice.lane == "combat" and renew_movement:
            return self.controller.refresh_movement(combat.kind, combat.seconds)
        self.controller.release_movement()
        if choice.lane in SUSTAIN:
            assert choice.action is not None and choice.lane is not None
            queued_at = time.perf_counter()
            submitted = self.controller.submit(choice.action, priority=choice.priority)
            if not isinstance(submitted, int):
                self._stop("INPUT_BACKEND_FAILURE", f"Potion key not queued: {submitted}")
                return submitted
            self.arbiter.submitted(submitted, choice.lane)
            self.live_potion_ticket = submitted
            self.potion_evidence.queued(
                submitted, choice.lane, queued_at, (self.view_generation, self.source_generation)
            )
            self.combat_evidence.record("queued", choice.action.kind, ticket=submitted)
            return f"deferred: {choice.action.kind} queued ({submitted})"
        if choice.action is None:
            return f"deferred: {choice.reason}"
        if choice.action.kind == "release":
            # A policy observation frame is not a request to cut a bounded attack/potion.
            # Target-loss cancellation is handled explicitly before arbitration.
            return "release"
        submitted = self.controller.submit(choice.action)
        if isinstance(submitted, int):
            self.arbiter.submitted(submitted, "combat")
        return submitted

    def _position_command(self, name: str, payload: dict) -> dict:
        """Read-only position tracking. These commands never enable or send input."""
        if name == "position_stop":
            if self.position is not None:
                self.position.close()
            self.position, self.detector.taught_map = None, False
            with self.lock:
                self.status.pop("position", None)
            return {"tracking": False}
        if name == "position_supplement":
            if self.position is None:
                raise ValueError("Track a saved area first")
            enabled = payload.get("enabled")
            if enabled is not False and (not self.capture_only or self.mode != "capture"
                                        or self.active_probe or self.area_editing
                                        or self.calibrating):
                raise ValueError("Supplement requires idle capture-only observation")
            return self.position.set_supplement(enabled)
        if self.area_editing:
            raise ValueError("Finish area editing before tracking the live position")
        if name == "position_start":
            if self.position is not None:
                if (self.position.profile["id"] == payload.get("area_id")
                        and payload.get("map_id") in (None, self.position.map_id)):
                    return {"tracking": True, "area_id": self.position.profile["id"],
                            "calibrated": self.position.tracker is not None}
            position = LivePosition(self.areas, payload.get("area_id"),
                                    capture_only=self.capture_only, map_id=payload.get("map_id"),
                                    player_threshold=self.config.perception.confidence)
            if self.position is not None:
                self.position.close()
            self.position = position
            with self.lock:
                self.status["position"] = {
                    "area_id": position.profile["id"], "area_name": position.profile["name"],
                    "kind": "unknown", "reason": "Waiting for a fresh position reading",
                    "captured_at": time.time(), "input_sent": False,
                }
            if not (self.navigation.agent and self.navigation.agent.active):
                try:
                    self.navigation.refresh()  # List destinations as soon as a map is tracked.
                except ValueError:
                    pass
            return {"tracking": True, "area_id": position.profile["id"],
                    "calibrated": position.tracker is not None}
        if self.position is None:
            raise ValueError("Track a saved area's position first")
        if name == "walk_calibration_begin":
            if self.mode not in {"capture", "dry_run"}:
                raise ValueError("Stop combat and potions before walk calibration")
            result = self.position.begin_calibration()
            self.note("Walk calibration started; walk the floor yourself, no input is sent")
            return result
        if name == "walk_calibration_cancel":
            return self.position.cancel_calibration()
        result = self.position.finish_calibration()
        residual = result["calibration"]["residual_px"]
        self.note(
            f"Walk calibration saved: {result['calibration']['pairs']} pairs, residual p95 "
            f"x {residual['x']['p95']:.1f} / y {residual['y']['p95']:.1f} px"
        )
        return result

    def _position_snapshot(self, position: dict | None) -> dict | None:
        """Clear a position older than 500 ms; a stale fix must never look current."""
        if position is None or self.position is None:
            return None
        if position.get("provisional") and self.position.supplement_tracker is None:
            return {**position, "kind": "unknown", "surface_id": None, "feet": None,
                    "projection": None, "marker": None, "provisional": False,
                    "supplement": self.position.supplement_status(),
                    "reason": "Localization supplement disabled"}
        age = time.time() - position["captured_at"]
        if age <= STALE_SECONDS:
            current = {**position, "stale": False}
        else:
            current = {**position, "kind": "unknown", "surface_id": None, "feet": None,
                       "marker": None, "projection": None, "stale": True,
                       "reason": f"Position stale: no processed frame for {age * 1000:.0f} ms"}
        if position.get("kind") == "platform" and position.get("surface_id"):
            self.shown_platform = (position.get("area_id"), position["surface_id"],
                                   position["captured_at"])
        elif str(position.get("reason", "")).startswith(
                ("Moving vertically", "Minimap marker and name tag disagree")):
            self.shown_platform = None  # Really moving: never hold the old platform.
        held = getattr(self, "shown_platform", None)
        if (current["kind"] == "platform" or not held or held[0] != position.get("area_id")
                or time.time() - held[2] > DISPLAY_HOLD_SECONDS):
            return current
        return {**current, "kind": "platform", "surface_id": held[1], "feet": None,
                "marker": None, "projection": None, "stale": True, "held": True,
                "reason": "Showing your last platform through a brief recognition gap"}

    @staticmethod
    def _roi(payload: dict, image: Image) -> Rect:
        rect = Rect(**{key: int(payload[key]) for key in ("x", "y", "width", "height")})
        if not Rect(0, 0, image.shape[1], image.shape[0]).contains(rect):
            raise ValueError("Selection is outside the screenshot")
        return rect

    def _save(self) -> str:
        if self.image is None:
            raise ValueError("No current screenshot")
        directory = self.data / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"frame-{time.time_ns()}.png"
        path.write_bytes(png(self.image))
        with self.lock:
            if self.latest:
                path.with_suffix(".annotated.png").write_bytes(self.latest)
        return str(path)

    def _publish_detections(self, status: dict, image: Image | None = None) -> None:
        """Publish read-only drawings before PNG work; encoded status stays image-paired."""
        with self.lock:
            if status["view_generation"] != self.view_generation:
                return
            self.live_detections = {
                "frame": {
                    "source_id": f"{self.session_id}:source:{self.source_generation}",
                    "id": f"{self.session_id}:{status['sequence']}",
                    "sequence": status["sequence"], "captured_at": status["captured_at"],
                    "width": status["width"], "height": status["height"], "available": True,
                },
                **{key: status.get(key) for key in (
                    "player", "monsters", "target", "position", "enemy_tracks",
                    "player_tracking")},
            }
            self.display_anchor = (self.live_detections, image) if image is not None else None

    def _encoded(self, packet: FramePacket, raw: bytes, annotated: bytes, elapsed: float) -> None:
        generation = packet.status.get("view_generation", self.view_generation)
        with self.lock:
            if generation != self.view_generation:
                return
        status = {
            **packet.status,
            "encoder": {**self.encoder.snapshot(), "png_encode_ms": round(elapsed, 3)},
        }
        self.recorder.observe(packet.stem, raw, status, packet.now)
        self.potion_evidence.observe(PotionFrame(
            packet.stem, raw, status, status.get("capture_clock", 0),
            (generation, status.get("source_generation", self.source_generation)),
        ))
        status["recording"] = self.recorder.active
        status["recorder"] = self.recorder.snapshot()
        with self.lock:
            if generation != self.view_generation:
                return
            self.latest, self.raw, self.status = annotated, raw, status
            self.published_frame = {
                "id": f"{self.session_id}:{packet.sequence}",
                "sequence": packet.sequence,
                "captured_at": packet.status.get("captured_at", time.time()),
                "width": packet.raw.shape[1],
                "height": packet.raw.shape[0],
            }
        self.frame_ready.set()

    def _process(
        self, image: Image, now: float, policy_now: float | None = None,
        *, captured_at: float | None = None,
    ) -> tuple[Image, dict]:
        policy_now = now if policy_now is None else policy_now
        self.processing_frame = {
            "sequence": self.sequence, "capture_clock": now, "stage": "map",
            "source_generation": self.source_generation, "view_generation": self.view_generation,
        }
        map_began = time.perf_counter()
        captured_at = time.time() if captured_at is None else captured_at
        fix = self.position.read_map(image) if self.position is not None else None
        map_ms = (time.perf_counter() - map_began) * 1000
        self.detector.taught_map = bool(fix and fix.canvas)
        self.detector.enemy_source = (self.session_id, self.source_generation)
        self.detector.strip = (self.navigation.search_strip(image.shape[1])
                               if self.mode in {"navigation", "navigation_wait"} else None)
        # Navigation/probes prioritize position freshness; idle view keeps enemy outlines.
        movement_probe = (self.mode.startswith("probe") and self.active_probe is not None
                          and self.active_probe.action in {"left", "right", "up", "down", "jump"})
        self.monster_search = not (
            movement_probe or self.mode in {"navigation", "navigation_wait"})
        perception_began = time.perf_counter()
        self.processing_frame = {**self.processing_frame, "stage": "perception"}
        observation = self.detector.detect(image, now, monsters=self.monster_search)
        self.pose_collection.observe(
            image, self.detector, observation, now, captured_at,
            (self.session_id, self.source_generation),
            eligible=bool(self.monster_search and self.calibration and
                          self.calibration.capture_verified and not self.calibrating),
        )
        perception_ms = (time.perf_counter() - perception_began) * 1000
        evidence = summarize({
            "frame": {"id": f"{self.session_id}:{self.sequence}", "available": True,
                      "captured_at": captured_at},
            "player": asdict(observation.player) if observation.player else None,
            "monsters": [asdict(item) for item in observation.monsters],
        }, self.config, time.time())
        scan_feedback = getattr(self.detector, "enemy_scan_feedback", None)
        if scan_feedback is not None:
            scan_feedback(evidence["frame_id"], fresh=evidence["fresh_player"],
                          eligible=bool(evidence["same_platform_targets"]))
        self.combat_evidence.observe({
            "frame_id": evidence["frame_id"], "captured_at": captured_at,
            "same_platform_targets": evidence["same_platform_targets"],
            "note": "Observation at collection, not proof of the keypress frame or a hit",
        })
        position = None
        position_began = time.perf_counter()
        self.processing_frame = {**self.processing_frame, "stage": "position"}
        if self.position is not None and fix is not None:
            try:
                position = self.position.update(image, fix, observation, now,
                                                captured_at=captured_at,
                                                input_timing=self.controller.timing_snapshot(),
                                                movement_keys=(self.config.input.left,
                                                               self.config.input.right),
                                                observation_context=(self.source_generation,
                                                                     self.view_generation),
                                                allow_supplement=self.capture_only
                                                and self.mode == "capture" and not self.area_editing
                                                and not self.calibrating
                                                and self.active_probe is None,
                                                passive_calibration=self.mode in {
                                                    "capture", "dry_run"}
                                                and not self.area_editing
                                                and not self.calibrating
                                                and self.active_probe is None)
                learned = position["calibration"]["learned"]
                if learned:
                    residual = learned["calibration"]["residual_px"]
                    self.note(
                        f"Walk calibration learned passively: {learned['calibration']['pairs']} "
                        f"pairs, residual p95 x {residual['x']['p95']:.1f} / "
                        f"y {residual['y']['p95']:.1f} px")
            except (ValueError, cv2.error) as error:
                position = {"kind": "unknown", "reason": f"Position unavailable: {error}",
                            "captured_at": captured_at, "input_sent": False}
        self.navigation.observe(fix, observation, position, now)
        position_ms = (time.perf_counter() - position_began) * 1000
        self.processing_frame = {**self.processing_frame, "stage": "policy"}
        if (
            self.calibration
            and not self.calibration.capture_verified
            and not self.calibrating
            and self.mode in {"capture", "dry_run"}
            and self.hwnd
            and time.perf_counter() - now <= 0.5
        ):
            window = self.windows.get(self.hwnd)
            crop = self.calibration.crop
            if (
                self.config.capture.window_title.casefold() in window.title.casefold()
                and self.calibration.valid_for(window)
                and image.shape[:2] == (crop.height, crop.width)
                and self.windows.unobscured(
                    window.hwnd, crop.translated(window.client.x, window.client.y)
                )
            ):
                player = observation.player
                player_recognized = bool(
                    player and not player.tracked
                    and player.confidence >= self.config.perception.confidence
                )
                hud_recognized = any(
                    reading.percent is not None and reading.confidence >= 0.9
                    for reading in (
                        self._resource_reading(resource, image) for resource in ("hp", "mp")
                    )
                )
                if player_recognized or hud_recognized:
                    self.calibration.capture_verified = True
                    self._restore_probes(clear_results=False)
                    self.note("Game view verified by confident player or HUD recognition")
        for outcome in self.controller.poll_outcomes():
            self.potion_evidence.outcome(outcome)
            self.combat_evidence.record("input_outcome", outcome.result, **asdict(outcome))
            self.arbiter.finished(outcome.ticket)
            self.last_action = outcome.result
            self.policy_outcome = {"status": "completed", **asdict(outcome)}
            self._handle_probe_outcome(outcome)
            if outcome.ticket == self.live_potion_ticket:
                self.live_potion_ticket = None
                if outcome.result.endswith("completed"):
                    self.potter.input_sent = True
                    self.note(f"Live potion key completed: {outcome.action}; effect unconfirmed")
                else:
                    self._stop("INPUT_BACKEND_FAILURE", "Live potion key did not complete")
        if self.mode in {"potion_wait", "potion_live"}:
            if self.capture_only:
                self._stop("CAPTURE_ONLY_GUARD", "Capture-only session: keyboard output locked")
            elif self.windows.pressed(KEYS[self.config.input.emergency_key]):
                self._stop("EMERGENCY_STOP", "Emergency hotkey canceled live potions")
            elif self.mode == "potion_live" or now >= self.pending_at:
                blocker = self._input_block_reason()
                if blocker or self.calibrating or self.stop_requested.is_set():
                    self._stop("FOCUS_LOSS", blocker or "Live potions stopped for calibration")
                elif time.perf_counter() - now > 0.5:
                    self._stop("PLAYER_UNCERTAIN", "Stale HUD frame; live potions stopped")
                elif self.mode == "potion_wait":
                    self._clear_stop_banner()
                    self.potter.start(live=True)
                    self.mode = "potion_live"
                    self.stop_reason = "Live potions enabled; combat remains stopped"
        if self.capture_only and self.mode in {
            "live", "pending_arm", "probe_wait", "navigation", "navigation_wait",
        }:
            self._stop("CAPTURE_ONLY_GUARD", "Capture-only session: keyboard output locked")
        if self.stop_requested.is_set() and self.mode != "capture":
            self._stop("CALIBRATION", "Operator stop or calibration requested")
        if self.controller.reason == "Emergency stop hotkey" and (
            self.mode != "capture" or self.potter.enabled
        ):
            self._stop("EMERGENCY_STOP", "Emergency stop hotkey")
        slow = time.perf_counter() - now > 0.5
        # Waiting for the operator or a potion effect sends nothing, so a slow frame is harmless.
        if slow and self.mode in {"live", "navigation", "navigation_wait"}:
            self._stop("PLAYER_UNCERTAIN", "Observation processing exceeded 500 ms; no input sent")
        if self.mode in {"pending_arm", "probe_wait"}:
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                self._stop("EMERGENCY_STOP", "Emergency hotkey canceled pending input")
            elif slow and now >= self.pending_at + PENDING_SLOW_GRACE_SECONDS:
                if self.active_probe is not None:
                    self._finish_probe(
                        self.active_probe, "cancelled", "Recognition stayed slower than 500 ms"
                    )
                self._stop(
                    "PLAYER_UNCERTAIN",
                    "Recognition stayed slower than 500 ms per frame; pending input canceled",
                )
            elif slow:
                pass  # Never press on a stale frame; wait for the next timely one.
            elif now >= self.pending_at:
                if (
                    observation.player is None
                    or observation.player.confidence < self.config.perception.confidence
                ):
                    raise RuntimeError("Player detection uncertain; input probe/arming canceled")
                pending = self.mode
                # Status takes stop_lock before controller.lock. Keep that order
                # while enabling input and clearing the previous stop banner.
                with self.stop_lock, self.controller.lock:
                    if self.stop_requested.is_set():
                        self._stop("OPERATOR_STOP", "Operator stopped pending input")
                        return self._process(image, now, captured_at=captured_at)
                    try:
                        self.controller.enable()
                    except RuntimeError:
                        if pending != "probe_wait":
                            raise
                        reason = self._input_block_reason() or (
                            "Input safety changed or the emergency key was held; probe canceled"
                        )
                        if self.active_probe is not None:
                            self._finish_probe(self.active_probe, "cancelled", reason)
                        self._stop("PROBE_COMPLETE", reason)
                        return self._process(image, now, captured_at=captured_at)
                    self._clear_stop_banner()
                if pending == "probe_wait":
                    active = self.active_probe
                    if active is None or active.phase != "countdown":
                        self._stop("PROBE_COMPLETE", "Probe was canceled before key submission")
                        return self._process(image, now, captured_at=captured_at)
                    action = active.action
                    duration = min(0.12, self.config.input.max_action_seconds)
                    submitted = self.controller.submit(Action(action, duration), disable_after=True)
                    self.last_action = f"probe {submitted} queued"
                    if isinstance(submitted, int):
                        self.combat_evidence.record("queued", action, ticket=submitted)
                        self.active_probe = replace(active, phase="queued", ticket=submitted)
                        self.mode = "probe_queued"
                    else:
                        self._finish_probe(active, "failed", "Control probe could not be queued")
                        self._stop("INPUT_BACKEND_FAILURE", "Control probe could not be queued")
                        self.mode = "capture"
                else:
                    self.mode = "live"
                    self.agent.start()
                    self.reacquisition.reset()
                    self._start_sustain()
                    if self.config.recording.auto:
                        self.recorder.start("combat")
        if self.mode == "live" and (
            not self.controller.enabled or self.controller.stopped.is_set()
        ):
            self._stop("INPUT_BACKEND_FAILURE", self.controller.reason)
        potion_evidence_safe = bool(
            self.calibration
            and self.calibration.capture_verified
            and not self.calibrating
            and not self.stop_requested.is_set()
            and time.perf_counter() - now <= 0.5
            and self.window
            and self.region
            and self.windows.unobscured(self.window.hwnd, self.region)
        )
        potter = self.potter.observe(
            image, now, safe=potion_evidence_safe,
        )
        mp = potter["readings"].get("mp", {})
        self.mp_percent = mp.get("percent") if mp.get("confidence", 0) >= 0.9 else None
        if self.mode == "navigation" and self.sustain:
            readings = potter["readings"]
            if (readings.get("hp", {}).get("percent") == 0 or any(
                    readings.get(r, {}).get("percent") is None
                    or readings[r]["confidence"] < .9 for r in self.sustain)):
                self._stop("PLAYER_UNCERTAIN", "Navigation sustain HUD unreadable or HP empty")
        if self.farming and self.mode in {"live", "navigation"}:
            if reason := self.farming.check(now, potter["readings"], potion_evidence_safe):
                self._stop("POLICY_STOP", reason)
        if self.farming and self.mode == "navigation":
            self.farming.progress(now, active=True)
        self.navigation.tick(potter["suggestion"], now)
        if self.mode == "live" and self.sustain:
            readings = potter["readings"]
            if readings.get("hp", {}).get("percent") == 0:
                self._stop("PLAYER_UNCERTAIN", "HP empty; combat stopped")
            elif any(
                readings.get(r, {}).get("percent") is None or readings[r]["confidence"] < 0.9
                for r in self.sustain
            ):
                if self.potion_hud_missing_since is None:
                    self.potion_hud_missing_since = now
                if now - self.potion_hud_missing_since >= 5.0:
                    self._stop("PLAYER_UNCERTAIN", "HUD unreadable for 5 seconds; combat stopped")
            else:
                self.potion_hud_missing_since = None
        if self.mode in {"live", "dry_run"}:
            policy_began = time.perf_counter()
            uncertain = (
                observation.player is None
                or observation.player.confidence < self.config.perception.confidence
            )
            if uncertain and not self.player_uncertain and self.recorder.active:
                self.recorder.trigger("Player detection uncertain", time.perf_counter())
            self.player_uncertain = uncertain
            if self.policy_outcome.get("status") == "pending":
                movement = self.controller.running_movement(self.policy_outcome.get("ticket"))
                if movement is not None:
                    self.policy_outcome = {**self.policy_outcome, "status": "held",
                                           "action": movement, "result": f"{movement} held"}
            policy_input = PolicyInput(
                observation, policy_now, self.policy_outcome, self.mp_percent
            )
            policy_before = self.agent.snapshot()
            paused = self._reacquire(observation.player, now)
            if paused is not None:
                decision = Decision(self.agent.state, Action(), paused, self.agent.target)
            else:
                decision = self.agent.step_input(policy_input)
                moving = None if decision.state == "IDLE" else self._rotate(
                    decision, observation, now)
                if decision.state == "IDLE":
                    self._stop("PLAYER_UNCERTAIN" if uncertain else "POLICY_STOP", decision.reason)
                    self.policy_outcome = {"status": "not_sent"}
                elif moving:
                    decision = replace(decision, reason=moving)
                    self.last_action = moving
                    self.policy_outcome = {"status": "not_sent"}
                elif self.mode == "live":
                    if decision.state == "SEARCH" or self.agent.missing_frames:
                        for ticket, lane in tuple(self.arbiter.in_flight.items()):
                            if lane == "combat":
                                self.controller.cancel_ticket(ticket)
                    renew_movement = False
                    if (decision.state == "APPROACH" and decision.action.kind in {"left", "right"}
                            and decision.target is not None and observation.player is not None):
                        gap = abs(decision.target.box.center[0] - observation.player.box.center[0])
                        # Use short steps near attack range; bridge frame gaps only well outside it.
                        margin = max(self.config.agent.attack_range,
                                     observation.player.box.width * 2)
                        renew_movement = gap - self.config.agent.attack_range > margin
                        if renew_movement:
                            decision = replace(decision, action=Action(
                                decision.action.kind, self.config.input.max_action_seconds,
                            ))
                    submitted = self._arbitrate(
                        decision.action, potter["suggestion"], renew_movement=renew_movement,
                    )
                    held = submitted == f"held: {decision.action.kind}"
                    if self.farming:
                        active = (decision.action.kind != "release"
                                  and (isinstance(submitted, int) or held))
                        if reason := self.farming.progress(now, active=active):
                            self._stop("POLICY_STOP", reason)
                    if (self.mode == "live" and decision.action.kind != "release"
                            and not isinstance(submitted, int) and not held):
                        self.agent.defer_action(policy_before)
                        decision = Decision(self.agent.state, decision.action,
                                            f"{decision.action.kind.capitalize()} {submitted}",
                                            decision.target)
                    self.last_action = (
                        f"{decision.action.kind} queued ({submitted})"
                        if isinstance(submitted, int)
                        else submitted
                    )
                    if decision.action.kind != "release":
                        self.combat_evidence.record("decision", self.last_action,
                                                    action=decision.action.kind,
                                                    ticket=submitted if isinstance(submitted, int)
                                                    else None,
                                                    acquisition=self.agent.acquisitions)
                    self.policy_outcome = (
                        {"status": "held", "action": decision.action.kind,
                         "result": f"{decision.action.kind} held"} if held else
                        {"status": "pending", "ticket": submitted}
                        if isinstance(submitted, int)
                        else {"status": "not_sent", "result": submitted}
                    )
                else:
                    self.last_action = f"dry run: intended {decision.action.kind}"
                    self.policy_outcome = {"status": "not_sent"}
            if self.status.get("reason") != decision.reason or decision.action.kind != "release":
                self.note(f"{decision.state}: {decision.reason} · {self.last_action}")
            policy_ms = (time.perf_counter() - policy_began) * 1000
        else:
            reason = self.navigation.reason if self.mode == "navigation" else self.stop_reason
            if self.mode in {"pending_arm", "probe_wait", "potion_wait"}:
                reason = f"Focus the game window; input in {max(0, self.pending_at - now):.1f}s"
            decision = Decision(self.agent.state, Action(), reason)
            policy_input = PolicyInput(
                observation, policy_now, self.policy_outcome, self.mp_percent
            )
            policy_before = self.agent.snapshot()
            policy_ms = 0.0
        annotation_began = time.perf_counter()
        annotated = annotate(image, observation, decision.target, decision.state, decision.reason)
        if self.mode == "potion_live":
            unreadable = any(
                self.potter.settings[f"{r}_threshold"] > 0
                and (
                    potter["readings"].get(r, {}).get("percent") is None
                    or potter["readings"][r]["confidence"] < 0.9
                )
                for r in ("hp", "mp")
            )
            if potter["readings"].get("hp", {}).get("percent") == 0:
                self._stop("PLAYER_UNCERTAIN", "HP empty; live potions stopped")
            elif unreadable:
                self.live_potion_ticket = None
                self.controller.stop("Waiting for HUD after transition", notify=False)
                if self.potion_hud_missing_since is None:
                    self.potion_hud_missing_since = now
                if now - self.potion_hud_missing_since >= 5.0:
                    self._stop(
                        "PLAYER_UNCERTAIN", "HUD unreadable for 5 seconds; live potions stopped"
                    )
                else:
                    potter.update(reason="Waiting for HUD after transition; potion input paused")
            else:
                self.potion_hud_missing_since = None
            if not unreadable and potter["suggestion"] and self.live_potion_ticket is None:
                with self.controller.lock:
                    if not self.stop_requested.is_set() and self.mode == "potion_live":
                        try:
                            self.controller.enable()
                            queued_at = time.perf_counter()
                            submitted = self.controller.submit(
                                Action(
                                    f"{potter['suggestion']}_potion",
                                    min(0.06, self.config.input.max_action_seconds),
                                ),
                                disable_after=True,
                            )
                            if not isinstance(submitted, int):
                                raise RuntimeError(str(submitted))
                            self.live_potion_ticket = submitted
                            self.potion_evidence.queued(
                                submitted, potter["suggestion"], queued_at,
                                (self.view_generation, self.source_generation),
                            )
                            self.combat_evidence.record("queued", f"{potter['suggestion']}_potion",
                                                        ticket=submitted)
                        except (RuntimeError, OSError) as error:
                            self._stop("INPUT_BACKEND_FAILURE", f"Live potion stopped: {error}")
            potter.update(self.potter.snapshot())
            if self.mode != "potion_live":
                potter.update(reason=self.stop_reason, suggestion=None)
        self.potter.annotate(annotated, potter)
        self._advance_potion_probe(image, now)
        if potter["suggestion"]:
            self.note(potter["reason"])
        annotation_ms = (time.perf_counter() - annotation_began) * 1000
        return annotated, {
            "state": str(decision.state),
            "reason": decision.reason,
            "player": asdict(observation.player) if observation.player else None,
            "monsters": [asdict(item) for item in observation.monsters],
            "target": asdict(decision.target) if decision.target else None,
            "direction": decision.action.kind
            if decision.action.kind in {"left", "right"}
            else None,
            "last_action": self.last_action,
            "input_timing": self.controller.timing_snapshot(),
            "features": True,
            "capture_only": self.capture_only,
            "autopotter": potter,
            "potion_evidence_safe": potion_evidence_safe,
            "catalog": self.detector.catalog_info,
            "enemy_tracks": [asdict(item) for item in getattr(observation, "enemy_tracks", [])],
            "player_tracking": getattr(observation, "player_tracking", None),
            "position": position,
            "failures": observation.failures,
            "camera_shift": observation.camera_shift,
            "camera_confidence": observation.camera_confidence,
            "policy_input": policy_input.to_dict(),
            "policy_before": policy_before,
            "navigation_step": self.navigation.last_step,
            "decision": asdict(decision),
            "action_outcome": policy_input.last_outcome,
            "stage_timing": {
                "map_ms": round(map_ms, 3),
                "perception_ms": round(perception_ms, 3),
                "position_ms": round(position_ms, 3),
                "policy_ms": round(policy_ms, 3),
                "annotation_ms": round(annotation_ms, 3),
            },
        }

    def _run(self) -> None:
        capture: Capture | None = None
        move_failures = 0
        previous = time.perf_counter()
        previous_capture = None
        try:
            capture = Capture(self.windows)
            while not self.closed.is_set():
                began = time.perf_counter()
                self._drain_commands()
                capture_ok = False
                try:
                    capture_began = time.perf_counter()
                    view_generation = self.view_generation
                    captured_at = time.time()
                    if self.hwnd:
                        image, window, region = capture.window(self.hwnd, self.calibration)
                    elif self.manual:
                        image, window, region = capture.grab(self.manual), None, self.manual
                    else:
                        self.closed.wait(0.05)
                        continue
                    capture_finished = time.perf_counter()
                    self.image, self.window, self.region = image, window, region
                    capture_ok = True
                    move_failures = 0
                    if self.session_capture_started is None:
                        self.session_capture_started = capture_began
                    policy_now = capture_began - self.session_capture_started
                    annotated, result = self._process(image, capture_began, policy_now,
                                                      captured_at=captured_at)
                    end = time.perf_counter()
                    status = {
                        **result,
                        "mode": self.mode,
                        "captured_at": captured_at,
                        "capture_clock": capture_began,
                        "source_generation": self.source_generation,
                        "width": image.shape[1],
                        "height": image.shape[0],
                        "sequence": self.sequence,
                        "view_generation": view_generation,
                        "focused": bool(window and window.focused),
                        "window": asdict(window) if window else None,
                        "region": asdict(region),
                        "calibration": asdict(self.calibration) if self.calibration else None,
                        "fps": round(1 / max(0.0001, end - previous), 1),
                        "latency_ms": round(1000 * (end - began), 2),
                        "recording": self.recorder.active,
                    }
                    status["stage_timing"] = {
                        "capture_interval_ms": round(1000 * (capture_began - previous_capture), 3)
                        if previous_capture is not None else None,
                        "capture_ms": round(1000 * (capture_finished - capture_began), 3),
                        **result["stage_timing"],
                    }
                    previous_capture = capture_began
                    previous = end
                    self._publish_detections(status, image)
                    publish_began = time.perf_counter()
                    self.processing_frame = {**(self.processing_frame or {}), "stage": "publish"}
                    packet = FramePacket(
                        self.sequence,
                        f"{self.sequence:08d}",
                        image.copy(),
                        annotated.copy(),
                        status.copy(),
                        policy_now,
                    )
                    self.encoder.publish(packet)
                    status["stage_timing"]["publish_ms"] = round(
                        (time.perf_counter() - publish_began) * 1000, 3
                    )
                    self.sequence += 1
                except CaptureMovedError:
                    move_failures = min(move_failures + 1, _CAPTURE_MOVE_ATTEMPTS)
                    self._capture_moved(move_failures)
                    self.closed.wait(_CAPTURE_MOVE_RETRY_SECONDS)
                except Exception as error:
                    move_failures = 0
                    self._stop("CAPTURE_WORKER_FAILURE", str(error))
                    if self.calibration and not capture_ok:
                        self.calibration.capture_verified = False
                        self.calibration.controls_verified = False
                        self.probed.clear()
                    self.image = None
                    self._invalidate_view()
                    reason = str(error)
                    if self.status.get("reason") != reason:
                        self.note(reason)
                    with self.lock:
                        self.status = {
                            "state": "IDLE",
                            "mode": "capture",
                            "reason": reason,
                            "focused": False,
                            "last_action": "none",
                            "features": True,
                            "catalog": self.detector.catalog_info,
                        }
                        self.latest, self.raw = None, None
                self.closed.wait(
                    max(0, 1 / self.config.capture.fps - (time.perf_counter() - began))
                )
        except Exception as error:
            with self.lock:
                self.status = {"state": "IDLE", "reason": str(error)}
        finally:
            if self.closed.is_set():
                self.controller.stop("Capture worker exited", notify=False)
            else:
                self.safe_stop("CAPTURE_WORKER_EXIT", "Capture worker exited")
            if capture:
                capture.close()

    def _drain_commands(self) -> None:
        while True:
            try:
                name, payload, future = self.commands.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(self._command(name, payload))
            except Exception as error:
                future.set_exception(error)
