# Phase 1: Deterministic Input and Safe Stop - Research

**Researched:** 2026-10-24  
**Domain:** Python 3.12 screenshot capture, ordinary Win32 keyboard output, deterministic replay, and failure-safe runtime control  
**Confidence:** HIGH for the existing code and offline design; MEDIUM for the Windows API/audio details verified from primary documentation; no live-game behavior is claimed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Key binding
- **D-01:** New keys are bound in `config.toml` `[input]` only, as new fields on `InputConfig`, next to left/right/attack/jump. The debugger shows the current bindings read-only. There is no binding UI and no second source of truth in `data/`.

### Control probes and the arming gate
- **D-02:** Arming requires probes only for keys the policy can send in this phase: left, right, attack, jump, plus skill. Probes for Up, Down, HP potion and MP potion are offered in the debugger. Each one becomes *required* for arming in the phase that starts sending that key: Up/Down in Phase 4, potions in Phase 3. Probe permissions stay in-memory and reset on restart, as today.
- **D-03:** Up probe guard: the debugger warns "stand away from portals and ropes". Then the normal 3 s focus countdown runs, followed by one short tap capped by the hold cap. The operator confirms by watching, like the existing probes. Down uses the same flow. The probe exists to prove that Up arrives as the arrow key, not numpad 8.
- **D-04:** HP/MP potion probes confirm themselves from the HUD bar. After one press, the probe passes if the matching bar rises within a bounded window. If the bar is at or above ~95%, the probe is refused with an actionable message (for example "HP is full; take damage first"). It does not press.
- **D-05:** Pet food is bound in Phase 1 but has no probe. The pet-food probe moves to Phase 3 with feeding.

### Alarm
- **D-06:** The alarm is a WAV bundled as package data next to `static/`. It loops through `winsound` `SND_FILENAME|SND_ASYNC|SND_LOOP` and stops with `PlaySound(None, 0)`. If the file is missing or playback fails, it falls back to repeated `MessageBeep`. It is played only from runtime, never from `decision.py`.
- **D-07:** F8 acknowledges an active alarm. After an alarm stop, keys are already released, so F8 has no other job. The debugger also gets an Acknowledge button. Either one silences the alarm.
- **D-08:** Stops caused by the operator are silent: the F8 emergency stop and the debugger Stop button.
- **D-09:** Severity split for the existing stop paths. **ALARM:** capture worker crash, input watchdog or backend failure, focus or obscuration lost while armed, calibration invalid while armed, player uncertain while armed, debugger command timeout. **SILENT (pause):** no targets, operator stop, dry-run stops, capture-only stops, probe finished. New stop reasons in later phases must declare a severity.
- **D-10:** The alarm repeats until acknowledged. It never times out by itself.

### After a stop
- **D-11:** The debugger shows a sticky stop banner with severity, a stable reason code, the message, the time and the saved clip path. It stays until the alarm is acknowledged or the bot is re-armed. Every stop also goes into the existing history list with its code.
- **D-12:** After acknowledging, the operator can arm again without re-probing. The existing arm gates still apply: confirmed player, 3 s countdown, calibration. Probes are cleared only when the cause touched input: calibration change, focus or window change, or input backend failure.
- **D-13:** A capture worker crash releases keys and starts the alarm without needing the worker. The debugger stays usable, and Acknowledge works without the dead worker. A fresh worker restarts in IDLE with input disabled and all probes cleared. The operator must recalibrate (or re-verify), probe and arm again.

### the agent's Discretion
- Input threading model: a dedicated input thread, or synchronous with renewable leases on the watchdog. The roadmap defers this to planning, and research recommends leases on the watchdog with input off the capture thread.
- Lease length, the hard per-kind maximum, and the potion-probe effect window. All bounded, all in `config.toml` with validation.
- Policy-only replay diff: what fields count as a difference, the report format, and whether pre-Phase-1 recordings are supported (they lack `PolicyInput`). The user chose not to discuss this.
- Whether arming is refused while an alarm is still unacknowledged. Refusing is the suggested default, because arming with the alarm still sounding would be confusing.
- Stop reason code names and the banner layout.

### Deferred Ideas (OUT OF SCOPE)
- Pet-food probe: Phase 3, alongside timed feeding (SUST-06).
- Requiring the Up/Down probes for arming: Phase 4. Requiring the potion probes for arming: Phase 3.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FND-01 | Every decision uses capture time and policy-only replay reports differences. | Log `PolicyInput`, policy state, decision, and async action outcome; replay those inputs without perception or input. |
| FND-02 | Keyboard actions do not block capture. | One serial input-executor thread accepts plans without waiting on the capture worker. |
| FND-03 | Bind/probe new keys and flag extended keys. | Expand `InputConfig`/`KEYS`, use the verified extended-key set, and generalize probes. |
| FND-04 | Up/Down leases renew and expire while the global cap remains. | Add bounded vertical-only leases checked by the existing watchdog; keep normal action cap unchanged. |
| FND-05 | Chords retain their defined order. | Add an ordered-chord plan whose ordering is fixed before timing jitter is applied. |
| FND-06 | Show frame-stage timing and remove worker PNG encoding. | Publish capture/perception/policy/annotation/queue timing and encode in one bounded encoder worker. |
| SAFE-01 | Every stop releases keys, saves a clip, and reports structured reason. | One idempotent, cross-thread `safe_stop` owns all three effects. |
| SAFE-02 | Alarm stops repeat until acknowledged; pauses are silent. | Runtime-owned `AlarmManager`, stop severity, direct acknowledge path, and sticky status. |
| SAFE-03 | Capture-worker crash still releases keys and alarms. | Worker `finally` invokes cross-thread `safe_stop`; debugger acknowledgement does not use its command queue. |
</phase_requirements>

## Summary

[VERIFIED: src/maplebot/runtime.py:422-527,529-605] The capture worker currently calls the policy with `time.perf_counter()`, then blocks in `KeyboardController.execute`, and encodes raw plus annotated PNGs before publishing the next frame. [VERIFIED: src/maplebot/keyboard.py:181-245] `execute_sequence` deliberately owns a complete timed sequence and releases keys in `finally`, so merely adding renewable deadlines to the current synchronous call cannot satisfy FND-02.

**Primary recommendation:** use one dedicated serial input-executor thread inside `KeyboardController`, retain its independent watchdog for gates and lease expiry, and make `Application.safe_stop` the sole idempotent terminal transition callable without the capture worker. [VERIFIED: src/maplebot/keyboard.py:247-269] The existing watchdog already wakes every 5 ms, owns held-key deadlines, and can stop the controller; it is the correct expiration/fail-safe owner, but not the execution thread. [VERIFIED: .planning/STATE.md:40-44] This resolves the recorded input-threading concern without moving policy or Win32 calls into `decision.py`.

[VERIFIED: pyproject.toml:9-13] Keep the existing Python 3.12/std-HTTP/HTML stack and add no dependency. [VERIFIED: .planning/research/STACK.md:11-22] The phase fits the standard library plus the installed capture/perception stack; do not introduce React, Node, a queue package, or an audio package.

## Project Constraints (from AGENTS.md)

- Keep the change narrowly scoped; touch only files required by this phase and do not do drive-by refactors.
- Preserve the repository's existing actual Python 3.12/std HTTP/HTML stack named by the task; the generic React/TypeScript/Node instruction is not applicable to this project.
- Use the established style and patterns, avoid unnecessary Windows process churn, and do not alter source, arm input, deploy, or commit during research.
- Before requesting a later verification, implementation should run its safe local install/deploy workflow when appropriate; this research phase performs no installation.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Capture timestamp and policy input | Capture worker | Recorder/replay | The worker owns frame acquisition; its captured time becomes the only policy clock. |
| Deterministic decision | `decision.py` | Replay | Policy remains pure and serializable. |
| Timed keys, chords, leases | `KeyboardController` input executor | Watchdog | One FIFO executor serializes `SendInput`; watchdog independently releases expired or unsafe keys. |
| PNG encoding | Encoder worker | Debugger/recorder | A bounded latest-frame queue protects capture from encoding and disk backpressure. |
| Stop, clip, banner, alarm | `Application.safe_stop` | `AlarmManager`, recorder | It must be callable from worker, watchdog, request timeout, and worker-finally paths. |
| Acknowledge and worker restart | Direct thread-safe application methods | Debugger/F8 callback | These operations must work after the capture worker has died. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `threading`, `queue`, `dataclasses`, `json` | Python 3.12 | Serialized input work, bounded queues, structured logs and replay. | [VERIFIED: pyproject.toml:9-13] Already available; no package installation. |
| `winsound` | Python 3.12 stdlib | Repeating WAV alarm and fallback beeps. | [CITED: https://docs.python.org/3.12/library/winsound.html] `SND_LOOP` requires `SND_ASYNC`; `PlaySound(None, 0)` stops active waveform audio. |
| Win32 `SendInput` through `ctypes` | Existing | Ordinary keyboard input. | [VERIFIED: src/maplebot/keyboard.py:40-85] Existing backend already uses scan-code `SendInput`. |

### Supporting

| Existing component | Purpose in Phase 1 | Required change |
|--------------------|--------------------|-----------------|
| `SessionRecorder` | Ring-buffer clip and JSONL history. | Make terminal triggering safe for concurrent `safe_stop`, and persist replay fields. [VERIFIED: src/maplebot/recorder.py:68-104] |
| `PotionMonitor` / `BarReading` | HP/MP probe baseline and visual effect check. | Reuse only readings; do not add sustain behavior. [VERIFIED: src/maplebot/autopotter.py:25-70,193-243] |
| `static/index.html` | Read-only bindings, probe controls, timing, stop banner and acknowledge. | Retain the no-build static UI. [VERIFIED: src/maplebot/static/index.html:39-45] |

## Recommended Architecture

### 1. Input: dedicated executor plus watchdog-owned renewable leases

[VERIFIED: src/maplebot/runtime.py:477-483] The capture worker synchronously executes each policy action today. [VERIFIED: src/maplebot/keyboard.py:181-245] The controller serializes and waits through its complete schedule, so a dedicated input executor is required to keep capture responsive while a key is held.

Use one daemon `key-executor` owned by `KeyboardController`, with a bounded FIFO of immutable input plans. `submit(plan)` only validates/gates and enqueues; it never waits for a key duration. The executor alone calls `_send`, preserves plan order, and publishes structured outcomes for the next captured frame. Keep the existing `key-watchdog` as a separate authority that: (1) checks F8/focus/calibration safety, (2) expires leases, and (3) invokes `safe_stop` on watchdog/backend failure. [VERIFIED: src/maplebot/keyboard.py:247-263] The watchdog already contains the safety/expiry loop; extending it avoids a second lease clock.

[ASSUMED] Add `[input] vertical_lease_seconds = 1.0` and `vertical_lease_max_seconds = 8.0`, validating `0.5 <= vertical_lease_seconds <= 2.0`, `1.0 <= vertical_lease_max_seconds <= 10.0`, and `vertical_lease_max_seconds >= vertical_lease_seconds`. A lease is only for `up`/`down`: each confirmed frame renews the 1.0 s deadline, but no continuous vertical hold survives 8.0 s since its start. This tolerates several slow frames while releasing within one second of lost renewal; it does not alter the existing global normal-action cap. [VERIFIED: config.toml:32-38] The current literal setting is `max_action_seconds = 0.25`. [VERIFIED: src/maplebot/config.py:141-145] Normal movement and attack durations are already rejected when they exceed that cap.

The policy must not emit renewal side effects. It returns a declarative `lease_start`, `lease_renew`, or `release` intent; runtime enqueues it, and the controller rechecks `enabled`, stop state, and `safe()` while holding its lock immediately before each key-down and renewal. This closes the watchdog-versus-act race documented for the current design. [VERIFIED: .planning/research/PITFALLS.md:256-268]

### 2. Ordered chords must bypass random reordering

[VERIFIED: src/maplebot/input_timing.py:63-140] Existing `TimingPlanner.plan` sorts events by timestamp and applies offset variation to nonzero starts. It is suitable for compatible overlap, but it does not express a hard invariant such as “Down is down before Jump is down.” [VERIFIED: tests/test_input_timing.py:27-36] The disabled profile currently asserts the event order `right down`, `space down`, `space up`, `right up`.

Add explicit `KeyChord`/ordered-plan construction for `down_then_jump` and `direction_then_jump`. The constructor fixes the required down-event order and a minimum inter-key interval before `TimingPlanner` adds only allowed duration/reaction variation; the executor consumes its already-ordered events FIFO. Do not model a chord as two independently submitted actions, do not use a per-key executor thread, and do not rely on sort stability as the contract. [CITED: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput] `SendInput` inserts supplied events serially, so a single ordered sender preserves the constructed sequence.

### 3. Key map and probes

[VERIFIED: src/maplebot/keyboard.py:17-26] `KEYS` currently contains only `left`, `right`, `a`, `d`, `z`, `ctrl`, `space`, and `f8`; [VERIFIED: src/maplebot/input_timing.py:10-17] `ACTIONS` is exactly `("left", "right", "attack", "jump")`. Extend both using D-01's `InputConfig` fields: `up`, `down`, `hp_potion`, `mp_potion`, `pet_food`, and `skill`; validate every bound key in the same controller constructor. [VERIFIED: src/maplebot/keyboard.py:99-102] Unsupported configured keys already raise `ValueError` there.

[CITED: https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput] With `KEYEVENTF_SCANCODE`, `wScan` identifies the key; `KEYEVENTF_EXTENDEDKEY` marks the required `0xE0`-prefixed scan-code form. [CITED: https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input] Microsoft lists Arrow, Insert, Delete, Home, End, Page Up, and Page Down among the extended-key set. Replace the current two-key special case with a named full extended-key set containing exactly those keys (plus any already-supported right Ctrl only if it is intentionally introduced); apply the flag to both down and up events. [VERIFIED: src/maplebot/keyboard.py:74-85] The current code sets the flag only when `key in ("left", "right")`.

Generalize the current 3-second `probe_wait` state rather than creating a second probe subsystem. [VERIFIED: src/maplebot/runtime.py:273-299,435-459] Current probes accept only four actions, wait three seconds, cap the tap with `min(0.12, max_action_seconds)`, and save names in `probed`. Keep that flow for Up/Down and add the D-03 portal/rope warning. Require `{left, right, attack, jump, skill}` only for Phase-1 arming; offer Up/Down/HP/MP without requiring them; bind but do not offer pet food. The probe set remains in memory and clears only for D-12 input-affecting causes.

[ASSUMED] For each potion probe, reject before input when the matching `BarReading.percent >= 95.0`; otherwise snapshot its baseline, enqueue one normal bounded tap, and pass only when a fresh reading rises by at least 1.0 percentage point within `potion_probe_effect_seconds = 2.0`. Validate `0 < potion_probe_effect_seconds <= 5`, `0 < potion_probe_min_gain_percent <= 10`, and `0 <= potion_probe_full_percent <= 100`. [VERIFIED: src/maplebot/autopotter.py:47-70] Readings are already percent values or `None` with a diagnostic reason, making the result visible and testable without adding gameplay policy.

### 4. Capture-time policy replay and asynchronous PNG

[VERIFIED: src/maplebot/decision.py:19-30,59-140] The decision model is a pure dataclass result and `Agent.step(observation, now)` accepts time explicitly. [VERIFIED: src/maplebot/runtime.py:539-574] The worker currently captures `capture_began`, passes it into `_process`, then PNG-encodes twice inline and records the result. Preserve that boundary: define serializable `PolicyInput(observation, now, previous_action_outcome)` and log, for every frame, `policy_input`, `policy_before`, `decision`, and `action_outcome` alongside the existing frame/status fields.

[ASSUMED] Use a session-relative capture monotonic timestamp (`capture_started_at` is zero for the first accepted frame) as `PolicyInput.now`; never replace it with decision-start time. The exact policy-only diff compares `state`, `action.kind`, `action.seconds`, `reason`, and serialized target; write `policy-diff.jsonl` entries containing `frame`, `fields`, `expected`, and `actual`. Refuse pre-Phase-1 sessions with a clear “missing PolicyInput” error rather than silently falling back to re-perception. This is the smallest deterministic contract and makes a deliberate policy change observable.

Move raw/annotated encoding and recorder observation to one `frame-encoder` thread fed by `Queue(maxsize=1)`. Capture publishes immutable frame copies plus status through non-blocking replacement/drop-old semantics; it reports `capture_ms`, `perception_ms`, `policy_ms`, `annotation_ms`, and `publish_ms`. Encoder timing may report `png_encode_ms` separately but must not contribute to capture-worker frame timing. [VERIFIED: .planning/research/STACK.md:24-32] At 1366x768 the recorded cost is `cv2.imencode(".png")` at 31.8 ms and the worker does it twice per frame. A new frame must replace, not backlog behind, stale debugger images.

### 5. One idempotent safe stop, alarm, and restart

[VERIFIED: src/maplebot/runtime.py:177-185] `_stop` currently releases keys, stops policy/preview, appends a string history entry, and triggers the recorder only if active. [VERIFIED: src/maplebot/runtime.py:599-605] The worker `finally` currently calls only `controller.stop("Capture worker exited")`, which cannot create the required clip, alarm, or structured banner. Replace both with one `Application.safe_stop(reason_code, message, severity)` guarded by a dedicated stop lock.

`safe_stop` must always call `controller.stop` first; the first caller then cancels queued plans/leases, stops policy and preview, calls `SessionRecorder.trigger`, stores a sticky `stop` object `{code, severity, message, time, clip_path, acknowledged}`, appends the same structured record to history, and starts the alarm only for `ALARM`. Later callers release keys again but must not create duplicate clips/history or restart audio. [VERIFIED: src/maplebot/recorder.py:85-104] `trigger` already returns the clip path and flushes the buffered frames, so it is the correct recorder integration point.

[ASSUMED] Use stable codes `CAPTURE_WORKER_EXIT`, `INPUT_WATCHDOG_FAILURE`, `INPUT_BACKEND_FAILURE`, `ARMED_FOCUS_LOST`, `CALIBRATION_INVALID`, `PLAYER_UNCERTAIN`, and `DEBUGGER_COMMAND_TIMEOUT` for D-09 alarm stops; use `NO_TARGETS`, `OPERATOR_STOP`, `DRY_RUN_STOP`, `CAPTURE_ONLY_STOP`, `PROBE_FINISHED`, and `EMERGENCY_STOP` for silent stops. Reject arm while an unacknowledged alarm is active. This default prevents an operator from arming behind an audible unresolved fault.

`AlarmManager` belongs in runtime I/O, not policy. [CITED: https://docs.python.org/3.12/library/winsound.html] `winsound.PlaySound` accepts a filename with `SND_FILENAME`; `SND_LOOP` must be combined with `SND_ASYNC`, and `PlaySound(None, 0)` stops a waveform. Start the bundled WAV with those flags after key release. If it is absent or raises `RuntimeError`, a dedicated alarm thread repeatedly calls `MessageBeep` and waits on an acknowledgement event; never call synchronous fallback audio from capture or input execution. [CITED: https://docs.python.org/3.12/library/winsound.html] `MessageBeep` itself can raise `RuntimeError`, so that final failure is recorded in status without blocking safety actions.

`/api/acknowledge` and the F8 callback must call an application lock-protected `acknowledge_alarm()` directly, never enqueue a worker command. [VERIFIED: src/maplebot/runtime.py:114-140] Ordinary debugger commands wait for the capture worker through a `Future` and timeout after 10 seconds, so they cannot satisfy D-13 after a worker crash. F8 acknowledges an active alarm; otherwise it requests the silent `EMERGENCY_STOP`. [VERIFIED: src/maplebot/debugger.py:60-72] The debugger already maps request failures to visible JSON errors and is the right endpoint to add the direct acknowledgement control.

After a fatal worker exit, expose an explicit direct `restart_capture` operation only when no worker is alive. It creates a fresh worker in IDLE, with controller disabled, queues drained, probes cleared, and calibration/input re-verification required. Do not auto-arm or auto-restart into live mode. [VERIFIED: src/maplebot/runtime.py:79,104-112] The current thread object is constructed once in `__init__`, so restart requires a small worker-lifecycle helper rather than calling `start()` on the same Python thread object.

## Code Touchpoints

| File | Planner responsibility |
|------|------------------------|
| `src/maplebot/config.py`, `config.toml` | Add D-01 bindings and bounded lease/probe settings as frozen validated configuration. [VERIFIED: src/maplebot/config.py:40-61,117-146] |
| `src/maplebot/input_timing.py` | Extend actions, preserve normal cap, and introduce hard ordered-chord construction. [VERIFIED: src/maplebot/input_timing.py:42-140] |
| `src/maplebot/keyboard.py` | Full extended key map/flag set, single input queue executor, watchdog leases, direct watchdog/F8 stop callback, structured outcomes. [VERIFIED: src/maplebot/keyboard.py:88-115,145-269] |
| `src/maplebot/decision.py` | Add serializable policy input/state snapshot/restore only; retain no runtime, keyboard, or audio import. [VERIFIED: src/maplebot/decision.py:1-9] |
| `src/maplebot/runtime.py` | Capture timestamp handoff, async input/encoder integration, direct safe-stop/ack/restart, probes, stop status/history, timings. [VERIFIED: src/maplebot/runtime.py:32-185,422-605] |
| `src/maplebot/replay.py` | Add strict policy-only replay and JSONL diff output; do not send input. [VERIFIED: src/maplebot/replay.py:18-83,117-150] |
| `src/maplebot/recorder.py` | Persist policy replay records and make trigger usable from the terminal path. [VERIFIED: src/maplebot/recorder.py:21-104] |
| `src/maplebot/debugger.py`, `src/maplebot/static/index.html` | Direct acknowledge/restart controls; sticky banner; bindings/timing/probe displays. [VERIFIED: src/maplebot/debugger.py:11-75; src/maplebot/static/index.html:39-45] |
| `src/maplebot/alarm.py`, `src/maplebot/static/alarm.wav`, `pyproject.toml` | Focused runtime alarm wrapper, packaged WAV, and `static/*.wav` package-data inclusion. [VERIFIED: pyproject.toml:21-22] The current exact package-data quote is `maplebot = ["static/*.html"]`. |
| `tests/test_keyboard.py`, `tests/test_input_timing.py`, `tests/test_runtime.py`, `tests/test_replay.py`, `tests/test_recorder.py`, `tests/test_autopotter.py`, `tools/input_smoke.py` | Regression coverage and a Tk-only Windows smoke fixture. [VERIFIED: tools/input_smoke.py:1-104] |

## Don't Hand-Roll

- Do not add a dependency for queues, scheduling, audio, or HTTP; use Python's current standard library and existing debugger. [VERIFIED: pyproject.toml:9-13]
- Do not create a second source of bindings in `data/` or a binding editor. D-01 is configuration-only.
- Do not generate a thread per key action or per alarm; own one serial executor and one long-lived alarm helper.
- Do not duplicate stop logic inside watchdog, command timeout, worker-finally, and decision handling; all delegate to `safe_stop`.
- Do not encode PNG in capture, use unbounded queues, or let recorder/debugger work delay capture. [VERIFIED: src/maplebot/recorder.py:119-148] Recorder already has a bounded pending-frame mechanism.
- Do not use any memory, packet, client-file, injected-code, anti-cheat-evasion, or input-concealment technique. [VERIFIED: .planning/REQUIREMENTS.md:77-79]

## Common Pitfalls

- A serial input executor alone is not safe: watchdog expiry must still release an Up/Down key if capture stalls or the executor is wedged. [VERIFIED: src/maplebot/keyboard.py:247-263]
- A renewal must validate safety under the controller lock immediately before the renewal/key-down; otherwise stop and act can race. [VERIFIED: .planning/research/PITFALLS.md:256-268]
- Current planner jitter may change timing; an ordered chord must make event ordering invariant before jitter. [VERIFIED: src/maplebot/input_timing.py:88-140]
- A worker-only debugger command cannot acknowledge an alarm or restart capture after worker death. [VERIFIED: src/maplebot/runtime.py:114-140]
- A capture exception currently clears calibration/probes only in the per-frame catch; fatal worker exit needs the same reset path. [VERIFIED: src/maplebot/runtime.py:575-605]
- Native `SendInput` and audio tests prove the local OS boundary only; they do not prove a game client received the intended action.

## Validation Strategy

### Automated regression scenarios

Add focused fake-backend tests for:

1. Key map validation and extended flag selection for `up`, `down`, arrows/navigation keys, and ordinary keys.
2. Input submit returns before a held action completes; capture/policy processing continues while the fake backend holds a key.
3. Lease start/renew/expiry, hard 8.0 s total cap, focus loss, F8, backend exception, and watchdog exception all release every held key exactly once.
4. 1,000 seeded `down_then_jump` and `direction_then_jump` schedules preserve the required down-event order despite timing variation.
5. Probe gates: required skill, optional Up/Down/HP/MP, D-03 warning/countdown, full-bar potion refusal, fresh-bar increase pass, timeout/no-increase fail, and pet-food no probe.
6. Policy-only replay: identical logged inputs produce no diff; one intentionally changed policy output produces one stable diff entry; a pre-Phase-1 log fails as missing `PolicyInput`.
7. Encoder queue stays bounded and capture-stage timings omit PNG work; recorder still receives a saved stop clip.
8. Every D-09 severity path yields one structured stop/history record; silent stops never start audio; acknowledge clears audio but preserves gates; worker fatal exit leaves direct acknowledge/restart usable.

### Exact Windows PowerShell checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_keyboard.py tests/test_input_timing.py tests/test_runtime.py tests/test_replay.py tests/test_recorder.py tests/test_autopotter.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests tools
.\.venv\Scripts\python.exe .\tools\input_smoke.py
```

[VERIFIED: tools/input_smoke.py:16-101] The last command targets only its own temporary Tk window and reports `"unity_verified": false`; extend that fixture for Up/Down/ordered-chord reception before using it as the Windows-boundary check. It must not be called live-game proof.

### Current baseline

[VERIFIED: local command 2026-10-24] `.venv\Scripts\python.exe -m pytest -q` passed 124 tests in 2.36 seconds. [VERIFIED: local command 2026-10-24] `.venv\Scripts\ruff.exe check src tests tools` reported `All checks passed!`.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Project Python venv | tests/runtime | Yes | Python 3.12.10 | — |
| pytest | regression suite | Yes | 9.1.1 | — |
| Ruff | lint | Yes | 0.17.2 | — |
| Windows `SendInput` / `winsound` | native input/alarm boundary | Windows-only, not invoked in this research | — | Fake backend and Tk smoke fixture for automated/offline checks. |

## Confidence and Open Questions

| Area | Level | Reason |
|------|-------|--------|
| Existing runtime/input/recorder design | HIGH | Read the current source and tests this session. |
| Dedicated executor + watchdog leases | HIGH | Direct consequence of the current synchronous execution path and FND-02. |
| Extended-key and winsound semantics | MEDIUM | Verified from Microsoft Learn and Python primary documentation; native smoke remains required. |
| Lease/probe default values | LOW | Deliberate bounded defaults, not live measured values. |
| Up/Down and potion visual effect in the target game | LOW | Requires supervised targeted acceptance after offline tests; Phase 1 does not claim it now. |

**Open questions for later live acceptance, not planning blockers:** whether the target game confirms arrow-key Up visibly under the D-03 guard, and whether a 2.0-second potion effect window matches target-client HUD latency. Both are bounded configuration defaults, so neither changes Phase 1's architecture.

## Planner Handoff

Plan the phase in dependency order: (1) pure config/timing/controller primitives and tests; (2) runtime async input, encoder, capture-time policy logging/replay; (3) idempotent stop/alarm/worker lifecycle; (4) debugger and packaged WAV integration; (5) complete regression plus Tk-only smoke. Keep the source changes concentrated in the listed files, make no game-input claim from tests, and do not schedule Phase 3/4 behavior beyond the locked bindings/probes/lease primitives.
