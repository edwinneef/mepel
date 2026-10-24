---
phase: 01-deterministic-input-and-safe-stop
plan: 01
subsystem: input
tags: [python, win32, keyboard, concurrency, safety]
requires: []
provides:
  - Non-blocking serial keyboard execution with terminal outcomes
  - Validated full Phase 1 bindings and bounded vertical leases
  - Extended-key flags and deterministic ordered chord constructors
affects: [runtime, input safety, control probes]
actuals:
  tokens: 4200
  tasks: 3
  commits: 4
tech-stack:
  added: []
  patterns: [single serial executor, watchdog-owned lease expiry, explicit chord ordering]
key-files:
  created: [tests/test_config.py]
  modified: [config.toml, src/maplebot/config.py, src/maplebot/input_timing.py, src/maplebot/keyboard.py, src/maplebot/runtime.py, tests/test_keyboard.py, tests/test_input_timing.py, tests/test_runtime.py, tools/input_smoke.py]
key-decisions:
  - "Capture submits immutable plans and polls terminal outcomes instead of waiting for input holds."
  - "Only Up and Down use renewable leases; every normal action retains the 0.25-second cap."
  - "Chord ordering is constructed before timing variation, never inferred from timestamp sort stability."
patterns-established:
  - "Controller safety paths advance generation, cancel queued plans, and release held keys."
  - "Own-window Tk smoke evidence remains explicitly non-game verification."
requirements-completed: [FND-02, FND-03, FND-04, FND-05]
coverage:
  - id: D1
    description: Non-blocking serial action executor with captured terminal outcomes
    requirement: FND-02
    verification:
      - kind: unit
        ref: tests/test_keyboard.py and tests/test_runtime.py
        status: pass
    human_judgment: false
  - id: D2
    description: Validated bindings and watchdog-owned vertical leases
    requirement: FND-04
    verification:
      - kind: unit
        ref: tests/test_config.py and tests/test_keyboard.py
        status: pass
    human_judgment: false
  - id: D3
    description: Extended navigation keys and deterministic Down+Jump/direction+Jump ordering
    requirement: FND-05
    verification:
      - kind: unit
        ref: tests/test_input_timing.py and tests/test_keyboard.py
        status: pass
    human_judgment: false
duration: 19min
completed: 2026-10-24
status: complete
---

# Phase 1: Deterministic Input and Safe Stop Summary

**Bounded asynchronous keyboard execution, renewable vertical dead-man leases, and invariant chord ordering without weakening capture-only behavior.**

## Performance

- **Duration:** 19 min
- **Started:** 2026-10-24T19:00:00Z
- **Completed:** 2026-10-24T19:19:00Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Added one bounded `key-executor`, immutable terminal `ActionOutcome` records, and non-blocking runtime submission/polling.
- Added the sole `[input]` bindings for Phase 1 plus finite, generation-bound Up/Down lease expiry.
- Added complete extended navigation key flags, deterministic chord constructors, 1,000-seed ordering coverage, and a Tk-only smoke extension.

## Task Commits

1. **Task 1: Submit one bounded action without stalling capture** - `d67fe2a` (feat)
2. **Task 2: Add validated bindings and watchdog-owned vertical leases** - `4b60cc2` (feat)
3. **Task 3: Guarantee extended scan codes and chord order under jitter** - `a910ffb` (feat)
4. **Verification formatting fix** - `a4a6b30` (fix)

## Files Created/Modified

- `src/maplebot/keyboard.py` - Serial executor, outcomes, leases, and extended-key flag map.
- `src/maplebot/runtime.py` - Non-blocking action submission and outcome polling.
- `src/maplebot/config.py` and `config.toml` - Full binding and lease configuration.
- `src/maplebot/input_timing.py` - Explicit chord constructors and complete action set.
- `tests/test_config.py`, `tests/test_keyboard.py`, `tests/test_input_timing.py`, `tests/test_runtime.py` - Offline regression coverage.
- `tools/input_smoke.py` - Own-window Up/Down and ordered-chord evidence only.

## Decisions Made

- Kept capture-only/replay boundaries unchanged: they still construct `DisabledInput` and cannot enable keyboard output.
- Used the existing project virtual environment for verification because this isolated worktree has no `.venv`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used the project virtual environment for verification**
- **Found during:** Task 1 verification
- **Issue:** The isolated checkout contains no `.venv`.
- **Fix:** Ran the prescribed commands with `D:\projects\maple-external-bot\.venv\Scripts\python.exe` and set `PYTHONPATH` to this checkout's `src`.
- **Verification:** All prescribed offline tests and Ruff passed.

**2. [Rule 1 - Formatting] Corrected Ruff line-length failures**
- **Found during:** Overall verification
- **Fix:** Reformatted changed Python and tool lines without behavior changes.
- **Verification:** `ruff check src tests tools` passed.
- **Committed in:** `a4a6b30`

---

**Total deviations:** 2 auto-fixed (1 blocking environment issue, 1 formatting issue)
**Impact on plan:** No scope expansion and no live/game input was invoked.

## Issues Encountered

None after the prescribed offline verification passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The asynchronous input seam, bounded leases, and ordered local input primitives are ready for the dependent Phase 1 plans. Native smoke remains deliberately unrun and is not game-reception evidence.

---
*Phase: 01-deterministic-input-and-safe-stop*
*Completed: 2026-10-24*
