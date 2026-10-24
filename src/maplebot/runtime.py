import json
import queue
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2

from .autopotter import PotionMonitor
from .capture import Calibration, Capture, Image
from .config import Config
from .decision import Action, Agent, Decision
from .geometry import Rect
from .keyboard import KEYS, DisabledInput, InputBackend, KeyboardController, Win32Input
from .perception import NameTag, TemplateDetector, annotate, nametag_parts
from .recorder import SessionRecorder
from .windows import Window, Windows


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
        self.capture_only = capture_only
        self.data = Path(config.capture.data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.windows = Windows()
        self.detector = TemplateDetector(self.data / "templates", config.perception)
        self.agent = Agent(config.agent, config.perception.confidence)
        self.potter = PotionMonitor(self.data / "autopotter.json")
        self.mode = "capture"
        self.last_action = "none"
        self.pending_at = 0.0
        self.pending_action: str | None = None
        self.calibrating = False
        self.probed: set[str] = set()
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
        self.player_uncertain = False
        self.sequence = 0
        self.lock = threading.Lock()
        self.commands: queue.Queue[tuple[str, dict, Future]] = queue.Queue()
        self.closed = threading.Event()
        self.frame_ready = threading.Event()
        self.stop_requested = threading.Event()
        self.worker = threading.Thread(target=self._run, name="capture", daemon=True)
        self.latest: bytes | None = None
        self.raw: bytes | None = None
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
        )

    def start(self) -> None:
        self.worker.start()

    def close(self) -> None:
        self.controller.stop("Application closing")
        self.closed.set()
        self.worker.join(timeout=3)
        self.controller.close()
        self.recorder.close()

    def request(self, name: str, payload: dict) -> Any:
        if name in {
            "stop",
            "attach",
            "manual",
            "reset_crop",
            "freeze",
            "crop",
            "template",
            "autopotter_calibrate",
            "autopotter_stop",
            "reload_templates",
        }:
            # Release now, without waiting for a capture/detector operation to finish.
            with self.controller.lock:
                self.stop_requested.set()
                self.controller.stop("Debugger stop/calibration")
        future: Future = Future()
        self.commands.put((name, payload, future))
        try:
            return future.result(timeout=10)
        except TimeoutError:
            future.cancel()
            with self.controller.lock:
                self.stop_requested.set()
                self.controller.stop("Debugger command timed out")
            raise RuntimeError("Debugger command timed out; input stopped") from None

    def snapshot(self) -> dict:
        with self.lock:
            potter = {
                "readings": {},
                "reason": "Calibrate full HP/MP bars; preview sends no input",
                **self.status.get("autopotter", {}),
                **self.potter.snapshot(),
            }
            if not self.potter.enabled:
                potter.update(suggestion=None, reason="Potion preview stopped")
            return {
                **self.status,
                "capture_only": self.capture_only,
                "autopotter": potter,
                "history": list(self.history),
            }

    def note(self, reason: str) -> None:
        with self.lock:
            self.history.appendleft({"time": round(time.time(), 3), "reason": reason})

    def _input_safe(self) -> bool:
        if self.capture_only:
            return False
        if not self.hwnd or not self.calibration or not self.calibration.capture_verified:
            return False
        window = self.windows.get(self.hwnd)
        region = self.calibration.crop.translated(window.client.x, window.client.y)
        return (
            self.config.capture.window_title.casefold() in window.title.casefold()
            and self.calibration.valid_for(window)
            and window.focused
            and self.windows.unobscured(window.hwnd, region)
        )

    def _stop(self, reason: str) -> None:
        self.controller.stop(reason)
        self.potter.stop()
        self.agent.stop(reason)
        self.mode, self.stop_reason, self.pending_action = "capture", reason, None
        self.last_action = "release all"
        self.note(reason)
        if self.recorder.active:
            self.recorder.trigger(reason, time.perf_counter(), close=not self.recorder.manual)

    def _command(self, name: str, payload: dict) -> Any:
        if self.capture_only and name in {"arm", "probe", "confirm_controls"}:
            raise ValueError("Capture-only session: gameplay controls are unavailable")
        if name == "autopotter_calibrate":
            self._stop("HUD calibration; potion preview stopped")
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
            return self.potter.snapshot()
        if name == "autopotter_settings":
            self.potter.configure(
                **{key: float(payload[key]) for key in ("hp_threshold", "mp_threshold", "cooldown")}
            )
            return self.potter.snapshot()
        if name == "autopotter_start":
            if self.calibrating or self.image is None:
                raise ValueError("Return to a live screenshot before starting potion preview")
            if not self.calibration or not self.calibration.capture_verified:
                raise ValueError("Verify capture before starting potion preview")
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                raise ValueError("Release the emergency stop key before starting preview")
            self._stop("Potion preview: gameplay input disabled")
            self.stop_requested.clear()
            self.potter.start()
            return self.potter.snapshot()
        if name == "autopotter_stop":
            self.potter.stop()
            return self.potter.snapshot()
        if name in {"attach", "manual", "reset_crop", "freeze", "crop", "template"}:
            self._stop("Calibration: gameplay input disabled")
        if name == "stop":
            self._stop("Operator stopped the agent")
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
            self._stop("Reloading templates; input disabled")
            self.detector.reload()
            return {"variants": len(self.detector.templates), "catalog": self.detector.catalog_info}
        if name == "dry_run":
            self.controller.stop("Dry run: no keyboard input")
            self.stop_requested.clear()
            self.agent.start()
            self.mode = "dry_run"
            if self.config.recording.auto:
                self.recorder.start("dry-run")
            return {"mode": self.mode}
        if name in {"arm", "probe"}:
            self._stop("Preparing bounded input; focus the Game view within 3 seconds")
            if self.calibrating:
                raise ValueError("Return to live view before issuing gameplay input")
            if not self.hwnd or not self.calibration or not self.calibration.capture_verified:
                raise ValueError("Crop and verify the Game view before input")
            window = self.windows.get(self.hwnd)
            if self.config.capture.window_title.casefold() not in window.title.casefold():
                raise ValueError("Input is restricted to the configured MapleUnity window title")
            if name == "arm" and not self.calibration.controls_verified:
                raise ValueError("Probe and confirm left, right, attack, jump before combat")
            action = payload.get("action")
            if name == "probe" and action not in {"left", "right", "attack", "jump"}:
                raise ValueError("Invalid control probe")
            self.pending_action = action
            with self.controller.lock:
                self.stop_requested.clear()
            self.mode = "pending_arm" if name == "arm" else "probe_wait"
            self.pending_at = time.perf_counter() + 3
            return {"mode": self.mode, "instruction": "Click Unity Game view now; F8 cancels"}
        if name == "confirm_controls":
            if not self.calibration or self.probed != {"left", "right", "attack", "jump"}:
                raise ValueError("Complete all four bounded probes in this session first")
            self.calibration.controls_verified = True
            self.calibration.save(self.data / "calibration.json")
            self.note("Operator confirmed observed controls; combat may now be armed")
            return {"ok": True}
        if name == "frozen_png":
            return png(self.frozen[payload["id"]][0])
        if name == "windows":
            return [asdict(window) for window in self.windows.list()]
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
            if self.image is None or self.region is None:
                raise ValueError("No current screenshot")
            key = uuid.uuid4().hex
            self.calibrating = True
            self.frozen[key] = (self.image.copy(), self.window, self.region)
            while len(self.frozen) > 4:
                del self.frozen[next(iter(self.frozen))]
            return {"id": key, "width": self.image.shape[1], "height": self.image.shape[0]}
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

    def _process(self, image: Image, now: float) -> tuple[Image, dict]:
        observation = self.detector.detect(image, now)
        if self.capture_only and self.mode in {"live", "pending_arm", "probe_wait"}:
            self._stop("Capture-only session: keyboard output locked")
        if self.stop_requested.is_set() and self.mode != "capture":
            self._stop("Operator stop or calibration requested")
        if self.controller.reason == "Emergency stop hotkey" and (
            self.mode != "capture" or self.potter.enabled
        ):
            self._stop("Emergency stop hotkey")
        if self.mode in {"live", "pending_arm", "probe_wait"}:
            if time.perf_counter() - now > 0.5:
                self._stop("Observation processing exceeded 500 ms; no input sent")
        if self.mode in {"pending_arm", "probe_wait"}:
            if self.windows.pressed(KEYS[self.config.input.emergency_key]):
                self._stop("Emergency hotkey canceled pending input")
            elif now >= self.pending_at:
                if (
                    observation.player is None
                    or observation.player.confidence < self.config.perception.confidence
                ):
                    raise RuntimeError("Player detection uncertain; input probe/arming canceled")
                pending = self.mode
                with self.controller.lock:
                    if self.stop_requested.is_set():
                        self._stop("Operator stopped pending input")
                        return self._process(image, now)
                    self.controller.enable()
                if pending == "probe_wait":
                    assert self.pending_action is not None
                    action = self.pending_action
                    duration = min(0.12, self.config.input.max_action_seconds)
                    self.last_action = self.controller.execute(Action(action, duration))
                    if self.last_action.endswith("completed"):
                        self.probed.add(action)
                    self.controller.stop("Control probe finished")
                    self.mode = "capture"
                    self.stop_reason = "Probe sent; confirm its visible effect yourself"
                else:
                    self.mode = "live"
                    self.agent.start()
                    if self.config.recording.auto:
                        self.recorder.start("combat")
        if self.mode == "live" and (
            not self.controller.enabled or self.controller.stopped.is_set()
        ):
            self._stop(self.controller.reason)
        if self.mode in {"live", "dry_run"}:
            uncertain = (
                observation.player is None
                or observation.player.confidence < self.config.perception.confidence
            )
            if uncertain and not self.player_uncertain and self.recorder.active:
                self.recorder.trigger("Player detection uncertain", time.perf_counter())
            self.player_uncertain = uncertain
            decision = self.agent.step(observation, time.perf_counter())
            if decision.state == "IDLE":
                self._stop(decision.reason)
            elif self.mode == "live":
                self.last_action = self.controller.execute(decision.action)
            else:
                self.last_action = f"dry run: intended {decision.action.kind}"
            if self.status.get("reason") != decision.reason or decision.action.kind != "release":
                self.note(f"{decision.state}: {decision.reason} · {self.last_action}")
        else:
            reason = self.stop_reason
            if self.mode in {"pending_arm", "probe_wait"}:
                reason = f"Focus Unity Game view; input in {max(0, self.pending_at - now):.1f}s"
            decision = Decision(self.agent.state, Action(), reason)
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
        self.potter.annotate(annotated, potter)
        if potter["suggestion"]:
            self.note(potter["reason"])
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
        }

    def _run(self) -> None:
        capture: Capture | None = None
        previous = time.perf_counter()
        try:
            capture = Capture(self.windows)
            while not self.closed.is_set():
                began = time.perf_counter()
                self._drain_commands()
                capture_ok = False
                try:
                    capture_began = time.perf_counter()
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
                    annotated, result = self._process(image, capture_began)
                    raw, decorated = png(image), png(annotated)
                    end = time.perf_counter()
                    status = {
                        **result,
                        "mode": self.mode,
                        "captured_at": captured_at,
                        "width": image.shape[1],
                        "height": image.shape[0],
                        "sequence": self.sequence,
                        "focused": bool(window and window.focused),
                        "window": asdict(window) if window else None,
                        "region": asdict(region),
                        "calibration": asdict(self.calibration) if self.calibration else None,
                        "fps": round(1 / max(0.0001, end - previous), 1),
                        "latency_ms": round(1000 * (end - began), 2),
                        "recording": self.recorder.active,
                        "recorder": self.recorder.snapshot(),
                    }
                    previous = end
                    with self.lock:
                        self.latest, self.raw, self.status = decorated, raw, status
                    self.frame_ready.set()
                    self.recorder.observe(f"{self.sequence:08d}", raw, status, end)
                    self.sequence += 1
                except Exception as error:
                    self._stop(str(error))
                    if self.calibration and not capture_ok:
                        self.calibration.capture_verified = False
                        self.calibration.controls_verified = False
                        self.probed.clear()
                    self.image = None
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
            self.controller.stop("Capture worker exited")
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
