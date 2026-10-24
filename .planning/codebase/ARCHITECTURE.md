---
last_mapped_commit: 9370ad5f14eb90e5ce4aeae8e7b52bb5b14ac14d
last_mapped_at: 2026-10-24
---
<!-- refreshed: 2026-10-24 -->

# Architecture

**Analysis Date:** 2026-10-24

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Entry: `maplebot` CLI (`src/maplebot/__main__.py`)                  │
│  doctor | debug [--capture-only] | replay | catalog                  │
└──────────────┬───────────────────────────────┬───────────────────────┘
               │ debug                         │ replay / catalog / doctor
               ▼                               ▼ (offline, no input)
┌─────────────────────────────────┐   ┌──────────────────────────────┐
│ Debugger HTTP server            │   │ `replay.py` (offline runner) │
│ `src/maplebot/debugger.py`      │   │ `catalog.py` (sprite import) │
│ + `static/index.html` UI        │   └──────────────────────────────┘
└──────────────┬──────────────────┘
               │ POST /api/<name> -> Application.request()
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Application (`src/maplebot/runtime.py`)                             │
│  single "capture" worker thread: drain commands -> capture ->        │
│  perceive -> decide -> act -> publish status/frames                  │
└───┬──────────────┬──────────────────┬──────────────────┬─────────────┘
    ▼              ▼                  ▼                  ▼
┌────────────┐ ┌───────────────┐ ┌──────────────┐ ┌──────────────────┐
│ Capture    │ │ Perception    │ │ Decision     │ │ Input            │
│ capture.py │ │ perception.py │ │ decision.py  │ │ keyboard.py      │
│ windows.py │ │ autopotter.py │ │ (state FSM)  │ │ input_timing.py  │
└────────────┘ └───────────────┘ └──────────────┘ └──────────────────┘
                                                          │
                              ┌───────────────────────────┘
                              ▼ SendInput (Win32) or DisabledInput
                     MapleUnity window (external, never modified)

Side channel: `recorder.py` (SessionRecorder) writes frames/decisions
to `data/recordings/` on a background thread.
Config: `config.toml` -> `config.py` dataclasses, passed everywhere.
```

## Pattern Overview

**Overall:** Single-process, threaded, screenshot-driven agent with a command-queue "actor" core and a localhost HTTP control surface.

**Key Characteristics:**
- One owner thread (`Application.worker`, named `capture`) performs all capture, perception, decision and status publication. Debugger requests never touch the pipeline directly; they enqueue `(name, payload, Future)` tuples into `Application.commands` and wait up to 10 s on the future (`src/maplebot/runtime.py`, `request` and `_drain_commands`).
- Input is isolated behind an `InputBackend` protocol (`src/maplebot/keyboard.py`). Two implementations exist: `Win32Input` (SendInput) and `DisabledInput` (used for `--capture-only`, where no OS backend is constructed).
- Pure, deterministic decision logic (`Agent.step(Observation, now) -> Decision`) is separated from I/O so the same code path runs live and in offline replay (`src/maplebot/replay.py`).
- Perception is behind a `Detector` protocol (`src/maplebot/perception.py`, class `Detector`), with `TemplateDetector` as the only implementation. README notes it can be swapped later.
- Configuration is a frozen-by-convention dataclass tree loaded once from TOML (`src/maplebot/config.py`, `Config.load`) and injected into components; no component reads the file itself.
- Safety is layered: a capture-only mode that removes the input backend entirely, a verified-calibration gate (`Application._input_safe`), focus/obscuration checks, an emergency key (`input.emergency_key`, default F8) polled via `Windows.pressed`, and a watchdog that releases keys when the controller's `_watch` thread sees a stale hold.

## Layers

**Entry / CLI:**
- Purpose: Parse subcommands, load config, wire components, block until worker exits.
- Location: `src/maplebot/__main__.py`, `src/maplebot/__init__.py`
- Contains: `main()` argparse dispatch. Imports of heavy modules (`runtime`, `debugger`, `replay`, `catalog`) are deferred into the branches.
- Depends on: `config`, lazily `runtime`/`debugger`/`replay`/`catalog`/`windows`.
- Used by: `python -m maplebot`, the `maplebot` console script (`pyproject.toml` `[project.scripts]`), `run.ps1`.

**Control surface (HTTP debugger):**
- Purpose: Localhost UI for calibration, probes, dry run and arm; exposes status and PNG frames.
- Location: `src/maplebot/debugger.py`, `src/maplebot/static/index.html`
- Contains: `serve(app, port)` builds a `ThreadingHTTPServer` bound to `127.0.0.1`. Random per-process token (`secrets.token_urlsafe(32)`) is injected into the served HTML by replacing `__TOKEN__`, and required as `X-Debug-Token` on every POST. Routes: `GET /`, `GET /api/status`, `GET /frame.png`, `POST /api/<command>` (body capped at 16384 bytes).
- Depends on: `runtime.Application` (imported only for typing and the `app` argument).
- Used by: Browser at `http://127.0.0.1:8765`.

**Orchestration (Application):**
- Purpose: Own all mutable session state and sequence every operation.
- Location: `src/maplebot/runtime.py` (618 lines; largest orchestrator)
- Contains: `Application.__init__` (constructs collaborators), `request` (cross-thread command entry), `_command` (command dispatch, a large if-chain by name), `_process` (one frame through perception/decision), `_run` (worker loop), `_stop` (latched stop with recorder trigger), `_input_safe` (input gate), `snapshot` (status for UI). Module-level helper `png(frame)`.
- Depends on: every domain module below.
- Used by: `debugger.py`, `__main__.py`.

**Capture:**
- Purpose: Grab pixels from a verified window client area or a manual desktop rectangle.
- Location: `src/maplebot/capture.py` (`Calibration`, `Capture`), `src/maplebot/windows.py` (`Window`, `Windows`), `src/maplebot/geometry.py` (`Rect`).
- Contains: `Calibration` (crop, window title/size/DPI validity, `capture_verified` and `controls_verified` flags, persisted as JSON with timestamped backup on replace). `Capture.grab` uses `mss`. `Windows` wraps Win32 window enumeration, focus, obscuration and key-state queries through `ctypes`.
- Depends on: `mss`, `numpy`, `ctypes`.
- Used by: `runtime.py`.

**Perception:**
- Purpose: Turn a frame into `Observation` (player and monster `Detection`s with confidence and boxes).
- Location: `src/maplebot/perception.py` (781 lines; `TemplateDetector`, `CameraTracker`, `NameTag`, `Template`, `SpriteSignature`, `annotate`), `src/maplebot/catalog.py` (offline import of public monster sprites), `src/maplebot/autopotter.py` (`PotionMonitor`, HP/MP bar readings).
- Contains: Template loading from `data/templates/` (including `catalog/` subtree and `manifest.json`), color-index candidate search, masked sprite verification, name-tag fusion, global phase correlation for camera translation, short-term tracking when the player is occluded (`perception.track_seconds`, `perception.track_max_seconds`).
- Depends on: `cv2`, `numpy`, `config.PerceptionConfig`, `capture.Image`.
- Used by: `runtime.py`, `replay.py`.

**Decision:**
- Purpose: Finite state machine choosing one `Action` per observation.
- Location: `src/maplebot/decision.py`
- Contains: `State` (StrEnum: `IDLE, SEARCH, APPROACH, ATTACK, VERIFY`), `Action` (frozen dataclass), `Decision` (frozen dataclass with reason/state), `Agent` (`start`, `stop(reason)`, `step(observation, now)`). Platform tolerance, attack range, and approach-without-progress limit (five steps) come from `config.AgentConfig`.
- Depends on: `config.AgentConfig`, `perception.Detection`/`Observation`.
- Used by: `runtime.py`, `replay.py`. Pure logic; no I/O.

**Input (actuation):**
- Purpose: Translate `Action`s into timed key down/up events through a single worker-safe controller.
- Location: `src/maplebot/keyboard.py` (`KEYS`, `InputBackend`, `DisabledInput`, `Win32Input`, `KeyboardController`), `src/maplebot/input_timing.py` (`TimingPlanner`, `KeyHold`, `KeyEvent`, `InputSchedule`).
- Contains: `KeyboardController` holds a `lock`, an `enable()` gate, `execute(action)`, `execute_sequence(holds)`, `release_all()`, a `_watch` thread that releases keys on stop/emergency, and an `atexit` hook. `TimingPlanner` adds randomized hold/reaction/rest/stagger within `[timing]` bounds from `config.toml`; seeded only when `timing.seed` is set.
- Depends on: `ctypes`, `config.InputConfig`/`TimingConfig`, `decision.Action`.
- Used by: `runtime.py`. In capture-only sessions `replay=True` is passed and the backend is `DisabledInput`.

**Recording:**
- Purpose: Persist evidence (frames, decisions, incidents) without blocking the capture loop.
- Location: `src/maplebot/recorder.py` (`SessionRecorder`)
- Contains: In-memory ring buffer; `observe()` is called every frame; `trigger(reason, now, close=...)` flushes context around stops and uncertain detection; a `queue.Queue` drained by a writer thread (`_write`); `_prune` enforces `max_age_days`, `max_total_mb`. Output layout: `data/recordings/session-*/` with `decisions.jsonl` and `events.jsonl`.
- Depends on: `config.RecordingConfig`.
- Used by: `runtime.py`.

**Offline replay and tooling:**
- Purpose: Run the same perception + decision + potion code on saved PNG frames; benchmarks and smoke checks.
- Location: `src/maplebot/replay.py` (`run_replay`), `tools/*.py` (standalone scripts, not imported by the package).
- Contains: `run_replay` iterates frames, labels, and writes to `artifacts/replay` by default.
- Depends on: `perception`, `decision`, `autopotter`, `config`.

## Data Flow

### Primary Live Frame Path (worker loop)

1. `Application._run` drains pending debugger commands (`_drain_commands`) before each frame (`src/maplebot/runtime.py`).
2. `Capture.window(hwnd, calibration)` or `Capture.grab(manual)` returns the image, the `Window`, and the `Rect` region. If neither a window nor a manual region is set, the loop idles on `closed.wait(0.05)`.
3. `Application._process(image, now)` runs perception (`TemplateDetector.detect`), potion monitoring (`PotionMonitor`), then `Agent.step`. Input is only dispatched when `_input_safe()` passes and the mode is armed.
4. `KeyboardController.execute` schedules key events via `TimingPlanner`, guarded by the controller lock and the emergency-key watcher.
5. Results are published atomically under `self.lock` into `self.status`, `self.latest` (annotated PNG) and `self.raw` (plain PNG). `status` is serialized by `GET /api/status`; the frame by `GET /frame.png`.
6. `SessionRecorder.observe(...)` appends the raw frame and status to its ring buffer.
7. The loop sleeps `1 / capture.fps` minus elapsed time (`config.toml` `[capture] fps`, default 12).

### Debugger Command Path

1. Browser POSTs `/api/<name>` with `X-Debug-Token`.
2. `debugger.py` calls `app.request(name, payload)`.
3. For risky commands (`stop`, `attach`, `manual`, `reset_crop`, `freeze`, `crop`, `template`, `autopotter_calibrate`, `autopotter_stop`, `reload_templates`) `request` first sets `stop_requested` and calls `controller.stop(...)` under `controller.lock`, before enqueueing. This releases keys without waiting for the worker.
4. The worker executes `_command(name, payload)` and resolves the `Future`. Timeout (10 s) cancels the future, stops input, and raises a `RuntimeError`.

### Stop / Safety Path

1. `_stop(reason)` stops the controller, the potion monitor, the agent, sets `mode="capture"`, appends to `history`, and calls `recorder.trigger(...)` when a session is active.
2. Any exception in the worker loop calls `_stop`, clears `capture_verified` and `controls_verified` when capture failed, and publishes an `IDLE` status with the error reason.
3. The emergency key (default F8, `config.input.emergency_key`) is polled through `Windows.pressed` by the controller's watcher.

### Offline Replay Path

1. `__main__ replay <frames>` -> `replay.run_replay(frames, templates, output, config, labels, annotated, autopotter)`.
2. Each saved frame goes through `TemplateDetector.detect` -> `Agent.step` -> optional `annotate`. No `Application`, no `Windows`, no `KeyboardController` is constructed, so no input is possible.

**State Management:**
- All live session state lives on the `Application` instance (`mode`, `hwnd`, `calibration`, `manual`, `region`, `frozen`, `history` as a `deque(maxlen=40)`, `probed`, `sequence`). Mutation happens on the worker thread; cross-thread readers take `self.lock`.
- Persistent state is on disk: calibration JSON, templates and `manifest.json` under `data/`, `data/autopotter.json` (HUD calibration), recordings under `data/recordings/`.
- Calibration permissions (`capture_verified`, `controls_verified`) are in-memory only and reset on restart by design (README "Calibration permissions reset on every application restart").

## Key Abstractions

**`Application`:**
- Purpose: Single owner of session state and the sole pipeline driver.
- Examples: `src/maplebot/runtime.py`
- Pattern: Actor-style command queue with `concurrent.futures.Future` replies.

**`Calibration` / `Capture` / `Windows`:**
- Purpose: Bind the bot to one verified window client area with DPI and geometry validation.
- Examples: `src/maplebot/capture.py`, `src/maplebot/windows.py`
- Pattern: `Calibration.valid_for(window)` is the single predicate used by both capture and `_input_safe`.

**`Detector` (Protocol) / `TemplateDetector`:**
- Purpose: Replaceable perception backend returning `Observation`.
- Examples: `src/maplebot/perception.py` (`Detector` at ~line 39; `TemplateDetector` at ~line 142)
- Pattern: `typing.Protocol` with one implementation.

**`InputBackend` (Protocol) / `Win32Input` / `DisabledInput`:**
- Purpose: Swap real input for a no-op in capture-only mode and in tests.
- Examples: `src/maplebot/keyboard.py` (`InputBackend` ~line 29)
- Pattern: Dependency injection via `Application(..., input_backend=...)`; tests in `tests/test_keyboard.py` and `tests/test_runtime.py` inject fakes.

**`Agent` (state machine):**
- Purpose: Deterministic per-frame policy.
- Examples: `src/maplebot/decision.py` (`State`, `Agent.step`)
- Pattern: Pure function of observation and time plus internal state; `Decision` carries the human-readable reason written to `decisions.jsonl`.

**Frozen config tree:**
- Purpose: One typed source for every tunable.
- Examples: `src/maplebot/config.py` (`CaptureConfig`, `DebuggerConfig`, `PerceptionConfig`, `AgentConfig`, `InputConfig`, `TimingConfig`, `RecordingConfig`, `Config`)
- Pattern: Dataclasses populated from `tomllib`; `Config.load(path)` is the only loader.

## Entry Points

**`maplebot` CLI:**
- Location: `src/maplebot/__main__.py` (`main`), registered as `maplebot = "maplebot.__main__:main"` in `pyproject.toml`
- Triggers: `python -m maplebot ...`, `.venv\Scripts\maplebot`, `run.ps1`
- Responsibilities: Subcommand dispatch. `debug` is the only one that starts threads and blocks.

**`run.ps1`:**
- Location: `run.ps1`
- Triggers: User double-click or shell. Runs `.venv\Scripts\python.exe -m maplebot debug --capture-only`; `-EnableGameplayInput` drops `--capture-only`.

**`install.ps1`:**
- Location: `install.ps1`
- Triggers: Manual setup. Creates `.venv` with Python 3.12 and runs `pip install -e ".[dev]"`.

**Debugger web UI:**
- Location: `src/maplebot/static/index.html` (served via `importlib.resources.files("maplebot")`)
- Triggers: Browser at `http://127.0.0.1:<debugger.port>` (default 8765)

**Offline tools:**
- Location: `tools/capture_smoke.py`, `tools/debugger_smoke.py`, `tools/input_smoke.py`, `tools/synthetic_benchmark.py`, `tools/benchmark_catalog.py`
- Triggers: Manual `python tools/<name>.py`. Not part of the installed package.

## Architectural Constraints

- **Threading:** Two long-lived thread families. (1) The `capture` worker (`Application.worker`, daemon) owns capture, perception, decision and status. (2) `ThreadingHTTPServer` request threads (daemon) for the debugger, which never run pipeline code and only block on futures. `KeyboardController._watch` is a third daemon thread. `SessionRecorder` runs a writer thread fed by a queue. Shared state is protected by `Application.lock` and `KeyboardController.lock`.
- **Global state:** `keyboard.py` registers an `atexit` handler and holds module-level `KEYS` mapping. `runtime.Application` holds per-instance state only; there are no module-level singletons in the session path.
- **Circular imports:** `debugger.py` imports `runtime.Application`; `runtime.py` does not import `debugger`, so there is no cycle. `decision.py` imports `perception.py` (for `Detection`/`Observation`); `perception.py` does not import `decision`.
- **Platform coupling:** `windows.py` and `keyboard.py` use Win32 APIs via `ctypes`. Everything else is portable Python, but the application as shipped runs only on Windows 11 (`pyproject.toml` requires Python >= 3.12; README targets Windows 11).
- **Single-session assumption:** One `Application` per process; `debugger.serve` binds one port. Starting two processes would contend for the same `data/` directory and the same game window.
- **Dependency rule (observed):** `config` <- everything; `geometry` <- `capture`, `perception`, `windows`, `autopotter`; `perception` and `decision` are the pure-ish core and must not import `runtime`, `keyboard` or `debugger`. Keep input and window code out of `perception.py` and `decision.py`.

## Anti-Patterns

### Calling pipeline or input code from debugger handlers

**What happens:** `debugger.py` handlers call `app.request(...)`. They never touch `controller`, `detector` or `calibration` directly.
**Why it's wrong:** Bypasses the worker-thread ownership and the command ordering that keeps capture, calibration and input consistent.
**Do this instead:** Add a branch in `Application._command` (`src/maplebot/runtime.py`) and, if it can affect input, add its name to the stop-first set inside `Application.request`.

### Hand-editing the `_command` if-chain without the stop set

**What happens:** New mutating commands are added to `_command` but not to the set in `Application.request` that releases input first.
**Why it's wrong:** A long perception call could keep the agent acting while the user is calibrating.
**Do this instead:** Register the command name in both places; `tests/test_runtime.py` is the place to assert the behavior.

### Importing `keyboard` or `windows` in pure modules

**What happens:** Adding Win32 calls into `perception.py` or `decision.py`.
**Why it's wrong:** Breaks offline replay on non-Windows CI and the deterministic test coverage in `tests/test_decision.py` and `tests/test_perception.py`.
**Do this instead:** Pass the data in as `Observation` or `Image`, and keep OS calls in `windows.py` / `capture.py` / `keyboard.py`.

## Error Handling

**Strategy:** Fail closed. Exceptions in the worker become a latched stop plus an `IDLE` status with the message; they are not re-raised to the browser except as HTTP 400 JSON from `debugger.py`.

**Patterns:**
- `Application._run` wraps each frame in `try/except Exception`, calls `_stop(str(error))`, and invalidates verification when capture failed.
- Debugger commands return `{"error": ...}` with status 400 (`debugger.py` `do_POST`). Forbidden or missing-token requests return 403.
- `Application.request` converts a 10-second timeout into a stop plus `RuntimeError("Debugger command timed out; input stopped")`.
- `Calibration.load` / `Config.load` raise on invalid input; `Config` validates ranges in `config.py` (for example, `math` is imported there for finite checks).

## Cross-Cutting Concerns

**Logging:** No logging framework. Evidence is written as JSON Lines: `decisions.jsonl` and `events.jsonl` per session under `data/recordings/session-*/` (`src/maplebot/recorder.py`). The debugger's `log_message` is silenced (`debugger.py`).

**Validation:** Config ranges in `src/maplebot/config.py`. Template validation via `TemplateDetector.validate(sprite)` (`src/maplebot/perception.py` ~line 288) before a sprite is accepted. Command payload size capped at 16384 bytes in `debugger.py`.

**Authentication:** Not applicable for remote use. The debugger is loopback-only (`127.0.0.1`) and protected by a per-process random token against cross-site requests from other local pages (`X-Debug-Token`).

**Input realism:** Software timing jitter is configured in `[timing]` (`src/maplebot/input_timing.py`). `config.toml` explicitly scopes this to software-input realism only.

---

*Architecture analysis: 2026-10-24*
