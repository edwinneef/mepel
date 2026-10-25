import hashlib
import json
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
from .autopotter import BarReading, PotionMonitor
from .capture import Calibration, Capture, CaptureMovedError, Image
from .config import Config
from .contracts import FRESH_FRAME_COMMANDS, CommandContext, readiness
from .decision import Action, Agent, Decision, PolicyInput
from .frame_encoder import FrameEncoder, FramePacket
from .geometry import Rect
from .keyboard import KEYS, DisabledInput, InputBackend, KeyboardController, Win32Input
from .perception import NameTag, TemplateDetector, annotate, nametag_parts
from .preview_stream import PreviewSource, PreviewStream
from .probe_store import ProbeStore
from .profiles import AreaStore
from .recorder import SessionRecorder
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
        self.command_epoch = 0
        self.view_generation = 0
        self.source_generation = 0
        self.published_frame: dict[str, Any] | None = None
        self.capture_only = capture_only
        self.data = Path(config.capture.data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.areas = AreaStore(self.data / "areas")
        self.area_editing = False
        self.windows = Windows()
        self.detector = TemplateDetector(self.data / "templates", config.perception)
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
        self.encoder = FrameEncoder(self._encoded)
        self.player_uncertain = False
        self.sequence = 0
        self.policy_outcome: dict[str, Any] = {"status": "not_sent"}
        self.session_capture_started: float | None = None
        self.lock = threading.Lock()
        self.stop_lock = threading.RLock()
        self.worker_lock = threading.RLock()
        self.stop_record: StopRecord | None = None
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
        )

    def start(self) -> None:
        self.connect_saved_window()
        self.preview.start()
        self.start_capture_worker()

    def _preview_source(self) -> PreviewSource:
        with self.lock:
            return PreviewSource(
                f"{self.session_id}:source:{self.source_generation}", self.hwnd, self.manual,
                replace(self.calibration) if self.calibration else None,
            )

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
        worker = self.worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=3)
        self.controller.close()
        self.encoder.close()
        self.recorder.close()
        self.alarm.close()

    def request(
        self, name: str, payload: dict, *, context: CommandContext | None = None
    ) -> Any:
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
                return {"view": self.areas.capture_view(latest[0])}
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
        if name in {"autopotter_settings", "autopotter_stop", "autopotter_start"}:
            self.stop_requested.set()
            self.safe_stop("OPERATOR_STOP", "Autopotter mode/settings change; input stopped")
        if context is not None:
            # Calibration/settings commands above deliberately supersede older work.
            # Start commands do not: a Stop that races a queued Start must win.
            if name in {
                "attach", "connect_saved_window", "manual", "reset_crop", "freeze", "crop",
                "template", "autopotter_calibrate", "reload_templates", "autopotter_settings",
                "autopotter_stop", "autopotter_start",
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
                "schema_version": 1,
                "session_id": self.session_id,
                "command_epoch": self.command_epoch,
                "mode": self.mode,
                "calibrating": self.calibrating,
                "area_editing": self.area_editing,
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
                "stop": asdict(self.stop_record) if self.stop_record else None,
                "capture_only": self.capture_only,
                "bindings": asdict(self.config.input),
                "required_probes": sorted(REQUIRED_PROBES),
                "optional_probes": sorted(OPTIONAL_PROBES),
                "probes": self._probe_snapshot(),
                "active_probe": asdict(self.active_probe) if self.active_probe else None,
                "autopotter": potter,
                "alarm": self.alarm.snapshot(),
                "history": list(self.history),
            }
            result["readiness"] = readiness(result)
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
            self.latest, self.raw = None, None

    def _capture_moved(self, attempt: int) -> None:
        message = f"Window moving; retrying capture ({attempt}/{_CAPTURE_MOVE_ATTEMPTS})"
        self.controller.stop(message, notify=False)
        with self.stop_lock:
            self.command_epoch += 1
            self._cancel_active_probe(message)
            self.live_potion_ticket = None
            self.potion_hud_missing_since = None
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
            self.probed.add(active.action)
            self._save_probes()
            self._finish_probe(active, "confirmed", "Fresh matching potion-bar gain confirmed")
            self.safe_stop("PROBE_COMPLETE", "Potion probe confirmed")

    def note(self, reason: str) -> None:
        with self.lock:
            self.history.appendleft({"time": round(time.time(), 3), "reason": reason})

    def _input_safe(self) -> bool:
        return self._input_block_reason() is None

    def _input_block_reason(self) -> str | None:
        if self.area_editing:
            return "Area editing: gameplay input is stopped"
        if self.capture_only:
            return "Capture-only session: gameplay controls are unavailable"
        if not self.hwnd or not self.calibration:
            return "Select and crop the game window before input"
        if not self.calibration.capture_verified:
            return "Confirm capture before issuing gameplay input"
        window = self.windows.get(self.hwnd)
        if self.config.capture.window_title.casefold() not in window.title.casefold():
            return "Input is restricted to the configured game window title"
        if not self.calibration.valid_for(window):
            return "Game window size or DPI changed; recalibrate and confirm capture"
        if not window.focused:
            return "Click the actual game window before the countdown ends"
        region = self.calibration.crop.translated(window.client.x, window.client.y)
        if not self.windows.unobscured(window.hwnd, region):
            return "Game view is covered by another window; move the covering window away"
        return None

    def _controller_stop(self, code: str, message: str) -> None:
        if code == "EMERGENCY_STOP" and self.alarm.snapshot()["active"]:
            self.acknowledge_stop()
            return
        self.safe_stop(code, message)

    def safe_stop(
        self,
        code: str,
        message: str,
        *,
        invalidate_probes: bool | None = None,
    ) -> StopRecord:
        reason = STOP_REASONS.get(code)
        if reason is None:
            raise ValueError(f"Unknown stop code: {code}")
        self.live_potion_ticket = None
        self.potion_hud_missing_since = None
        self._cancel_active_probe(message)
        # This must happen before any recorder, encoder, status, or audio work.
        self.controller.stop(message, code=code, notify=False)
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

    def _stop(self, code: str, message: str) -> StopRecord:
        return self.safe_stop(code, message)

    def _clear_stop_banner(self) -> None:
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
                self.command_epoch, max_age=0.5 if name in FRESH_FRAME_COMMANDS else 10
            )
            payload = {key: value for key, value in payload.items() if key != "_context"}
        if name in {"attach", "manual", "reset_crop", "crop"}:
            self._invalidate_view()
        if self.capture_only and name in {"arm", "probe", "confirm_controls"}:
            raise ValueError("Capture-only session: gameplay controls are unavailable")
        if name == "probe":
            return self.request_probe(payload)
        if name == "confirm_controls":
            raise ValueError("Use the per-probe confirmation controls")
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
            self.detector.reload()
            self.note(f"Added {kind} template from screenshot pixels")
            return {"path": str(path), "variants": len(self.detector.templates)}
        if name == "reload_templates":
            self._stop("CALIBRATION", "Reloading templates; input disabled")
            self.detector.reload()
            return {"variants": len(self.detector.templates), "catalog": self.detector.catalog_info}
        if name == "dry_run":
            self._stop("DRY_RUN_STOP", "Dry run: no keyboard input")
            with self.stop_lock:
                if self.area_editing:
                    raise ValueError("Finish area editing before starting preview decisions")
                if context is not None:
                    context.validate(self.command_epoch - 1)
                self.stop_requested.clear()
                self.agent.start()
                self.mode = "dry_run"
                self._clear_stop_banner()
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
            with self.stop_lock:
                if self.alarm.snapshot()["active"]:
                    raise ValueError("Acknowledge the active alarm before arming combat")
                if self.area_editing:
                    raise ValueError("Finish area editing before arming combat")
                if context is not None:
                    context.validate(self.command_epoch - 1)
                self.stop_requested.clear()
                self._clear_stop_banner()
                self.mode = "pending_arm"
                self.pending_at = time.perf_counter() + 3
            return {"mode": self.mode, "instruction": "Click the game window now; F8 cancels"}
        if name == "frozen_png":
            return png(self.frozen[payload["id"]][0])
        if name == "windows":
            return [asdict(window) for window in self.windows.list()]
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
        if name == "save":
            return {"path": self._save()}
        if name == "record":
            if self.recorder.full:
                path = self.recorder.path
                self.recorder.full = False
                if self.recorder.manual:
                    self.recorder.stop()
                return {"path": str(path), "recording": False}
            path = self.recorder.start("manual", manual=True)
            self.recorder.full = True
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
        self, image: Image, now: float, policy_now: float | None = None
    ) -> tuple[Image, dict]:
        policy_now = now if policy_now is None else policy_now
        perception_began = time.perf_counter()
        observation = self.detector.detect(image, now)
        perception_ms = (time.perf_counter() - perception_began) * 1000
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
        if self.capture_only and self.mode in {"live", "pending_arm", "probe_wait"}:
            self._stop("CAPTURE_ONLY_GUARD", "Capture-only session: keyboard output locked")
        if self.stop_requested.is_set() and self.mode != "capture":
            self._stop("CALIBRATION", "Operator stop or calibration requested")
        if self.controller.reason == "Emergency stop hotkey" and (
            self.mode != "capture" or self.potter.enabled
        ):
            self._stop("EMERGENCY_STOP", "Emergency stop hotkey")
        if self.mode in {"live", "pending_arm", "probe_wait", "probe_confirm", "probe_effect"}:
            if time.perf_counter() - now > 0.5:
                self._stop(
                    "PLAYER_UNCERTAIN", "Observation processing exceeded 500 ms; no input sent"
                )
        if self.mode in {"pending_arm", "probe_wait"}:
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                self._stop("EMERGENCY_STOP", "Emergency hotkey canceled pending input")
            elif now >= self.pending_at:
                if (
                    observation.player is None
                    or observation.player.confidence < self.config.perception.confidence
                ):
                    raise RuntimeError("Player detection uncertain; input probe/arming canceled")
                pending = self.mode
                with self.controller.lock:
                    if self.stop_requested.is_set():
                        self._stop("OPERATOR_STOP", "Operator stopped pending input")
                        return self._process(image, now)
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
                        return self._process(image, now)
                    self._clear_stop_banner()
                if pending == "probe_wait":
                    active = self.active_probe
                    if active is None or active.phase != "countdown":
                        self._stop("PROBE_COMPLETE", "Probe was canceled before key submission")
                        return self._process(image, now)
                    action = active.action
                    duration = min(0.12, self.config.input.max_action_seconds)
                    submitted = self.controller.submit(Action(action, duration), disable_after=True)
                    self.last_action = f"probe {submitted} queued"
                    if isinstance(submitted, int):
                        self.active_probe = replace(active, phase="queued", ticket=submitted)
                        self.mode = "probe_queued"
                    else:
                        self._finish_probe(active, "failed", "Control probe could not be queued")
                        self._stop("INPUT_BACKEND_FAILURE", "Control probe could not be queued")
                        self.mode = "capture"
                else:
                    self.mode = "live"
                    self.agent.start()
                    if self.config.recording.auto:
                        self.recorder.start("combat")
        if self.mode == "live" and (
            not self.controller.enabled or self.controller.stopped.is_set()
        ):
            self._stop("INPUT_BACKEND_FAILURE", self.controller.reason)
        if self.mode in {"live", "dry_run"}:
            policy_began = time.perf_counter()
            uncertain = (
                observation.player is None
                or observation.player.confidence < self.config.perception.confidence
            )
            if uncertain and not self.player_uncertain and self.recorder.active:
                self.recorder.trigger("Player detection uncertain", time.perf_counter())
            self.player_uncertain = uncertain
            policy_input = PolicyInput(
                observation, policy_now, self.policy_outcome, self.mp_percent
            )
            policy_before = self.agent.snapshot()
            decision = self.agent.step_input(policy_input)
            if decision.state == "IDLE":
                self._stop("PLAYER_UNCERTAIN" if uncertain else "POLICY_STOP", decision.reason)
                self.policy_outcome = {"status": "not_sent"}
            elif self.mode == "live":
                submitted = self.controller.submit(decision.action)
                self.last_action = (
                    f"{decision.action.kind} queued ({submitted})"
                    if isinstance(submitted, int)
                    else submitted
                )
                self.policy_outcome = (
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
            reason = self.stop_reason
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
        potter = self.potter.observe(
            image,
            now,
            safe=bool(
                self.calibration
                and self.calibration.capture_verified
                and not self.calibrating
                and not self.stop_requested.is_set()
                and time.perf_counter() - now <= 0.5
                and self.window
                and self.region
                and self.windows.unobscured(self.window.hwnd, self.region)
            ),
        )
        mp = potter["readings"].get("mp", {})
        self.mp_percent = mp.get("percent") if mp.get("confidence", 0) >= 0.9 else None
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
            "catalog": self.detector.catalog_info,
            "failures": observation.failures,
            "camera_shift": observation.camera_shift,
            "camera_confidence": observation.camera_confidence,
            "policy_input": policy_input.to_dict(),
            "policy_before": policy_before,
            "decision": asdict(decision),
            "action_outcome": policy_input.last_outcome,
            "stage_timing": {
                "perception_ms": round(perception_ms, 3),
                "policy_ms": round(policy_ms, 3),
                "annotation_ms": round(annotation_ms, 3),
            },
        }

    def _run(self) -> None:
        capture: Capture | None = None
        move_failures = 0
        previous = time.perf_counter()
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
                    self.image, self.window, self.region = image, window, region
                    capture_ok = True
                    move_failures = 0
                    if self.session_capture_started is None:
                        self.session_capture_started = capture_began
                    policy_now = capture_began - self.session_capture_started
                    annotated, result = self._process(image, capture_began, policy_now)
                    end = time.perf_counter()
                    status = {
                        **result,
                        "mode": self.mode,
                        "captured_at": captured_at,
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
                        "capture_ms": round(1000 * (capture_began - began), 3),
                        **result["stage_timing"],
                    }
                    previous = end
                    publish_began = time.perf_counter()
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
