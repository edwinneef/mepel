# Phase 1: Deterministic Input and Safe Stop - Pattern Map

**Mapped:** 2026-10-24  
**Files analyzed:** 19 proposed source/config/test/tool files  
**Analogs found:** 19 / 19 (direct or role-match; alarm WAV has no code analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Tracked Analog | Match Quality |
|---|---|---|---|---|
| `config.toml` | config | file I/O | `src/maplebot/config.py:117-146` | exact |
| `src/maplebot/config.py` | config/validation | transform | `TimingConfig` and `RecordingConfig`, lines 63-104 | exact |
| `src/maplebot/input_timing.py` | utility/planner | transform | `TimingPlanner.plan`, lines 35-140 | exact |
| `src/maplebot/keyboard.py` | controller/service | event-driven + file/OS I/O | `KeyboardController`, lines 88-269 | exact |
| `src/maplebot/decision.py` | model/policy boundary | transform | `Agent.step` and dataclasses, lines 1-140 | role-match |
| `src/maplebot/runtime.py` | controller/orchestrator | event-driven + request-response | `Application.request`, `_stop`, `_process`, `_run`, lines 114-185, 422-605 | exact |
| `src/maplebot/replay.py` | service | batch/file I/O | `run_replay`, lines 18-150 | exact |
| `src/maplebot/recorder.py` | service | streaming/file I/O | `SessionRecorder.observe/trigger`, lines 21-148 | exact |
| `src/maplebot/debugger.py` | HTTP route/service | request-response | `serve` handler, lines 11-76 | exact |
| `src/maplebot/static/index.html` | UI component | request-response | existing inline fetch/bind/poll UI, lines 26-78 | exact |
| `src/maplebot/alarm.py` | runtime utility | event-driven/OS I/O | no direct analog; keep audio outside policy | none |
| `src/maplebot/static/alarm.wav` | package resource | file I/O | `static/index.html` package resource | none |
| `pyproject.toml` | packaging config | file I/O | package-data declaration, lines 18-22 | exact |
| `tests/test_keyboard.py` | regression test | event-driven fake backend | existing fake backend/controller tests | exact |
| `tests/test_input_timing.py` | regression test | deterministic transform | existing seeded schedule tests | exact |
| `tests/test_runtime.py` | integration test | event-driven/request-response | `Application` fixture and command tests | exact |
| `tests/test_replay.py` | regression test | batch/file I/O | temp frames/output tests, lines 11-69 | exact |
| `tests/test_recorder.py` | integration test | streaming/file I/O | bounded queue/clip tests, lines 11-137 | exact |
| `tests/test_autopotter.py` | domain test | transform/file I/O | fake HUD image and calibrated monitor, lines 9-112 | role-match |
| `tools/input_smoke.py` | Windows smoke fixture | event-driven/OS I/O | own Tk window only, lines 16-104 | exact |

## Pattern Assignments

### Configuration and timing

**Files:** `config.toml`, `src/maplebot/config.py`  
**Analog:** `InputConfig` (`config.py:40-48`), `TimingConfig.__post_init__` (`config.py:50-81`), `Config.load` (`config.py:117-146`).

Keep all new bindings and bounded lease/probe values in frozen dataclasses. `Config.load` constructs each section from TOML (`config.py:121-134`), then performs cross-field checks (`config.py:135-145`). Follow the existing error style: `ValueError("section.field must be between ...")`; use `math.isfinite` for duration-like values. Do not introduce a second binding source or UI editor.

```python
@dataclass(frozen=True)
class InputConfig:
    left: str = "left"
    right: str = "right"
    attack: str = "z"
    jump: str = "space"
    max_action_seconds: float = 0.25
    emergency_key: str = "f8"
```

`config.toml` currently supplies section values (`config.toml:1-38`); extend `[input]` beside the existing four gameplay fields. Preserve the normal global action cap and validate lease and potion probe bounds at load time.

### Input actions, extended keys, serial execution, watchdog, and chords

**Files:** `input_timing.py`, `keyboard.py`  
**Analogs:** `ACTIONS`/`TimingPlanner.plan` (`input_timing.py:10-140`) and `KeyboardController` (`keyboard.py:17-26, 88-269`).

`TimingPlanner` validates action names and finite bounded holds before sorting (`input_timing.py:48-72`), builds immutable `KeyEvent` values (`input_timing.py:20-32`), and applies seeded variation (`input_timing.py:88-140`). Add an explicit ordered-chord constructor before variation; do not submit chord keys independently or rely on timestamp sort stability. Preserve `InputSchedule` as the controller boundary.

`KeyboardController` validates configured keys in its constructor (`keyboard.py:99-101`), gates enablement with `safe()` and emergency state (`keyboard.py:118-125`), serializes execution with `execution_lock` (`keyboard.py:107-110`), and releases held keys from `stop` (`keyboard.py:127-136`). Extend validation to every new binding, keep one serial executor, and let the watchdog remain the expiry/safety authority (`keyboard.py:247-269`). A fake backend should implement the existing `InputBackend.send(key, down)` protocol (`keyboard.py:29-37`).

The Win32 analog uses scan-code input and applies flags on both transitions (`keyboard.py:48-85`); replace the current left/right-only extended-key check (`keyboard.py:74-77`) with a named complete set. Preserve backend exceptions as stop-worthy failures and ensure release is idempotent.

### Policy input, capture timestamp, and policy-only replay

**Files:** `decision.py`, `runtime.py`, `replay.py`, `recorder.py`  
**Analogs:** pure decision model (`decision.py:1-140`), capture-to-process boundary (`runtime.py:539-574`), offline replay (`replay.py:1-150`), recorder JSONL (`recorder.py:21-104`).

`Agent.step(observation, now)` receives time explicitly and returns dataclass-like decision data; keep keyboard/audio/runtime imports out of `decision.py`. In `runtime.py`, capture starts timing at `capture_began` and passes it into `_process` (`runtime.py:539-550`), while status and recorder observation are updated afterward (`runtime.py:553-574`). Preserve that handoff, add serializable `PolicyInput`, and move PNG encoding to a bounded replacement queue/encoder worker so capture-stage timing excludes PNG work.

`run_replay` rejects missing/invalid frame input and keeps output separate (`replay.py:27-31`), writes JSONL decision records, and has no input backend (`replay.py:1`). Extend it with strict policy-only replay and a stable JSONL diff; pre-Phase-1 records should fail explicitly when `PolicyInput` is absent. Follow `tests/test_replay.py:11-69`: `tmp_path`, generated PNGs, JSONL parsing, and explicit `input_sent is False` assertions.

`SessionRecorder` already owns bounded asynchronous writing and trigger/clip flushing (`recorder.py:21-104, 119-148`). Add policy fields to the existing decision/event records; use `trigger` as the one stop clip integration point rather than creating another writer.

### Probes, runtime commands, stop lifecycle, and restart

**Files:** `runtime.py`, `debugger.py`, `static/index.html`  
**Analogs:** command queue and timeout (`runtime.py:114-140`), current probe gate (`runtime.py:273-299, 435-459`), current stop (`runtime.py:177-185`), HTTP routing (`debugger.py:11-76`), current probe controls (`index.html:37-45, 47-78`).

The current request path performs immediate controller stop for stop-like commands, then waits on a `Future` with a 10-second timeout (`runtime.py:114-140`). Retain the direct lock-protected path for F8, alarm acknowledge, and worker-independent stop/restart; ordinary commands may remain queued. Replace duplicated `_stop`/worker-finally paths with one lock-guarded structured `safe_stop`, calling `controller.stop` first, then recorder/history/status/alarm exactly once.

Generalize the existing three-second `pending_at` flow and bounded probe tap (`runtime.py:273-292, 435-459`). Required Phase-1 probes become left/right/attack/jump/skill; Up/Down and potion probes remain offered but optional; pet food is bound only. Preserve in-memory probe state and clear it only for input-affecting causes.

`debugger.py` is a plain `ThreadingHTTPServer`: loopback Host validation, token-protected POSTs, bounded body length, JSON response, and visible error conversion are established at `debugger.py:28-72`. Add direct acknowledge/restart routes using the same response/error style. The static page is no-build HTML with inline CSS/JS, `fetch('/api/...')`, one `api` helper, `bind` wrappers, and polling (`index.html:47-78`). Add read-only bindings/timings, sticky structured stop banner, acknowledge, and restart controls without adding a frontend dependency.

### Alarm and package resource

**Files:** `src/maplebot/alarm.py`, `src/maplebot/static/alarm.wav`, `pyproject.toml`  
**Analog:** no existing alarm implementation. Runtime I/O is the nearest architectural boundary; policy must remain pure.

Create one runtime-owned alarm helper with WAV loop, `PlaySound(None, 0)` acknowledgement, and repeated `MessageBeep` fallback. It must not be called from `decision.py`, capture processing, or per-key threads. Package data currently includes only HTML (`pyproject.toml:18-22`); extend the same declaration to `static/*.wav`. Keep the resource next to `static/index.html` and test missing/failed playback with a fake audio boundary rather than requiring sound hardware.

### Fake backends and smoke testing

**Files:** all listed tests and `tools/input_smoke.py`  
**Analogs:** controller fake backend fixtures in `tests/test_keyboard.py`, seeded event assertions in `tests/test_input_timing.py`, application fixture/commands in `tests/test_runtime.py`, recorder queue tests in `tests/test_recorder.py`, and HUD image generation in `tests/test_autopotter.py:9-23`.

Use deterministic fake backends that record `(key, down)` events and raise injected exceptions. Assert submit returns before a held action completes, lease expiry releases each held key once, and all stop severity paths create one structured record. Seed 1,000 chord schedules and assert down-event ordering. Use `tmp_path` for recordings/replay and `time.monotonic` deadlines as in `tests/test_recorder.py:19-23`; avoid sleeps except bounded polling.

The Windows smoke tool is deliberately scoped to its own topmost Tk window (`tools/input_smoke.py:16-37`), records key events (`tools/input_smoke.py:23-25`), and reports `unity_verified: false` (`tools/input_smoke.py:75-95`). Extend it only for arrow/chord boundary coverage; it is not game-client evidence.

## Shared Patterns

### Safety and release

Source: `src/maplebot/keyboard.py:118-136, 247-269`; `src/maplebot/runtime.py:127-140, 177-185`. Every path that disables input calls controller stop/release under its lock. New watchdog, backend, focus, calibration, worker-finally, debugger timeout, and operator paths should delegate to one idempotent application stop coordinator.

### Deterministic, bounded data

Source: `src/maplebot/config.py:63-81, 93-104`; `src/maplebot/input_timing.py:48-72`; `src/maplebot/recorder.py:119-148`. Validate finite bounds at construction, use immutable records for cross-thread data, and use bounded queues with replacement/drop-old behavior. No unbounded action, frame, or alarm queue.

### Local debugger contract

Source: `src/maplebot/debugger.py:18-26, 28-72`; `src/maplebot/static/index.html:49-52, 70-78`. Keep loopback/token/JSON protections, plain static HTML, one request helper, and user-visible errors. Status remains a snapshot assembled under the application lock (`runtime.py:142-157`).

### Offline evidence boundary

Source: `src/maplebot/replay.py:1, 27-31`; `tests/test_replay.py:26-36`; `tools/input_smoke.py:75-80`. Replay and fake-backend tests establish deterministic decisions and local OS-boundary behavior only; they must never claim that a live game received an action.

## No Direct Analog

| File | Reason | Planning guidance |
|---|---|---|
| `src/maplebot/alarm.py` | No existing audio wrapper | Add a small runtime-only standard-library wrapper with injectable/fake playback boundary. |
| `src/maplebot/static/alarm.wav` | New binary package resource | Bundle beside static HTML; verify package-data inclusion and missing-file fallback. |

## Metadata

**Analog search scope:** tracked `src/maplebot`, `tests`, `tools`, `config.toml`, and `pyproject.toml`; all named analogs verified with `git ls-files`.  
**Files scanned:** 19 proposed files plus supporting source/test definitions.  
**Pattern extraction date:** 2026-10-24
