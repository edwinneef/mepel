---
phase: 01-deterministic-input-and-safe-stop
plan: 03
subsystem: safe-stop
tags: [python, alarm, debugger, recovery, safety]
requires:
  - phase: 01-02
    provides: Bounded encoder flush and clip recorder handoff
provides:
  - Idempotent structured safe-stop incidents with explicit severity codes
  - Packaged local-PC alarm with WAV and repeated fallback lifecycle
  - Direct debugger acknowledge and single-worker capture restart recovery
affects: [runtime, debugger, capture lifecycle, recording]
actuals:
  tasks: 3
  commits: 4
tech-stack:
  added: []
  patterns: [stop registry, release-first terminal ordering, direct dead-worker controls]
key-files:
  created: [src/maplebot/alarm.py, src/maplebot/static/alarm.wav, tests/test_alarm.py]
  modified: [pyproject.toml, src/maplebot/runtime.py, src/maplebot/keyboard.py, src/maplebot/debugger.py, src/maplebot/__main__.py, src/maplebot/static/index.html, tests/test_runtime.py]
key-decisions:
  - "safe_stop releases input before bounded encoding, clip recording, status publication, and optional alarm start."
  - "Stop reasons are stable codes with declared ALARM or SILENT severity, never parsed from messages."
  - "Acknowledge and restart are direct methods and do not wait on the capture command queue."
requirements-completed: [SAFE-01, SAFE-02, SAFE-03]
duration: 53min
completed: 2026-10-24
status: complete
---

# Phase 1 Plan 03: Safe Stop, Alarm, and Dead-Worker Recovery Summary

**One release-first stop coordinator now records a structured incident, preserves debugger control after worker failure, and uses a local-PC alarm only for declared alarm severities.**

## Accomplishments

- Added `StopSeverity`, `StopRecord`, and `STOP_REASONS`, then routed runtime and keyboard terminal paths through idempotent `Application.safe_stop`.
- Added `AlarmManager`, a repository-owned WAV package resource, exact asynchronous looping waveform playback, and a repeated `MessageBeep` fallback that stops only on acknowledgment.
- Added a sticky debugger stop banner plus direct acknowledge/restart endpoints; restart remains disabled, clears probes, invalidates calibration verification, and starts only one fresh worker.

## Task Commits

1. **Task 1: Drive one worker crash through central safe_stop** - `c98a573` (feat)
2. **Task 2: Package the looping alarm and enforce the severity registry** - `2b99e38` (feat)
3. **Safe-stop formatting correction** - `8f04b90` (fix)
4. **Task 3: Keep debugger acknowledge and worker restart alive after failure** - `747dde0` (feat)

## Verification

- `D:\projects\maple-external-bot\.venv\Scripts\python.exe -m pytest -q tests/test_runtime.py tests/test_recorder.py tests/test_alarm.py` - PASS, 32 tests.
- `D:\projects\maple-external-bot\.venv\Scripts\ruff.exe check src tests tools` - PASS.
- Package-resource assertion using `importlib.resources.files('maplebot').joinpath('static/alarm.wav').is_file()` - PASS.
- `git diff --check` - PASS.

All checks used fake input/audio boundaries or offline fixtures. No game was launched, input was not armed, gameplay keys were not sent, and no check claims game or speaker effects.

## Deviations

- Used the existing project virtual environment at `D:\projects\maple-external-bot\.venv` because this isolated checkout has no local `.venv`.
- Corrected Ruff formatting in the new keyboard callback calls after task verification; no behavior changed.

## Files Changed

- `src/maplebot/runtime.py`, `src/maplebot/keyboard.py` - Central stop lifecycle, severity registry, input callback routing, and worker recovery.
- `src/maplebot/alarm.py`, `src/maplebot/static/alarm.wav`, `pyproject.toml` - Alarm lifecycle and package resource.
- `src/maplebot/debugger.py`, `src/maplebot/__main__.py`, `src/maplebot/static/index.html` - Dead-worker-safe controls and sticky incident display.
- `tests/test_alarm.py`, `tests/test_runtime.py` - Fake audio, stop ordering, registry, acknowledge, and restart coverage.

## Next Phase Readiness

SAFE-01 through SAFE-03 have offline evidence only. A future bounded local audio check may confirm PC output; it remains neither game-input nor gameplay-effect evidence.
