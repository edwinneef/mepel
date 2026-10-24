---
phase: 01-deterministic-input-and-safe-stop
plan: 02
subsystem: deterministic-replay
tags: [python, replay, policy, png, concurrency]
requires:
  - phase: 01-01
    provides: Non-blocking input outcomes consumed by the runtime
provides:
  - Capture-time PolicyInput records with policy snapshots and strict replay validation
  - Stable input-free policy-diff CLI evidence
  - Bounded PNG encoder and terminal sequence flush contract
affects: [safe-stop, debugger-timing, offline-regression]
actuals:
  tokens: 9754
  tasks: 3
  commits: 3
plan_head_before: e93b400ea8f958cfc9abc009e89353bb2e567aa8
plan_head_after: df177bdb2a2b405c7bc840598919e35bd3fa73df
tech-stack:
  added: []
  patterns: [capture-time policy clock, strict policy replay, bounded latest-frame encoder]
key-files:
  created: [src/maplebot/frame_encoder.py, tests/test_frame_encoder.py]
  modified: [src/maplebot/__main__.py, src/maplebot/decision.py, src/maplebot/recorder.py, src/maplebot/replay.py, src/maplebot/runtime.py, tests/test_replay.py, tests/test_runtime.py]
key-decisions:
  - "Policy-only replay restores the logged pre-step state and accepts no legacy, empty, or reordered policy log."
  - "PNG encoding and recorder observation run only on the bounded encoder worker; capture records stage timing separately."
patterns-established:
  - "Replay compares only declared policy decision fields and never constructs an input backend."
  - "Terminal callers use FrameEncoder.flush_through(sequence, timeout) for a bounded encoder cutoff."
requirements-completed: [FND-01, FND-02, FND-06]
coverage:
  - id: D1
    description: Capture-time PolicyInput recording and strict pure policy replay
    requirement: FND-01
    verification:
      - kind: unit
        ref: .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_decision.py tests/test_replay.py tests/test_recorder.py
        status: pass
    human_judgment: false
  - id: D2
    description: Stable policy-only JSONL diff CLI with changed-policy failure status
    requirement: FND-01
    verification:
      - kind: unit
        ref: tests/test_replay.py#test_policy_only_cli_returns_success_for_an_exact_replay
        status: pass
    human_judgment: false
  - id: D3
    description: Bounded latest-frame encoder, recorder handoff, and flush cutoff
    requirement: FND-06
    verification:
      - kind: unit
        ref: .\\.venv\\Scripts\\python.exe -m pytest -q tests/test_frame_encoder.py tests/test_recorder.py tests/test_runtime.py
        status: pass
    human_judgment: false
duration: 16min
completed: 2026-10-24
status: complete
---

# Phase 1 Plan 02: Capture-time Policy Replay and Bounded Frame Encoding Summary

**Capture-time policy records now replay without pixels or input, while PNG encoding and recording handoff run behind a bounded latest-frame worker.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-10-24T19:49:10Z
- **Completed:** 2026-10-24T20:05:00Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Added serializable `PolicyInput`, state snapshot/restore, strict sequence/time validation, and exact policy-only replay.
- Added `replay --policy-only` with deterministic `policy-diff.jsonl`, JSON summary, and nonzero changed/invalid results.
- Moved normal-frame PNG encoding and recorder delivery to `FrameEncoder` with one pending packet, replacement accounting, and bounded `flush_through`.

## Task Commits

1. **Task 1: Record and replay one PolicyInput end to end** - `9ca2c83` (feat)
2. **Task 2: Expose a stable policy-diff CLI and changed-policy result** - `6250df2` (feat)
3. **Task 3: Publish frames through a bounded encoder and terminal flush barrier** - `df177bd` (feat)

## Files Created/Modified

- `src/maplebot/decision.py` - Policy input serialization and explicit agent state restoration.
- `src/maplebot/replay.py` and `src/maplebot/__main__.py` - Strict policy replay and CLI diff output.
- `src/maplebot/frame_encoder.py` - Bounded encoder queue, replacement accounting, and flush barrier.
- `src/maplebot/runtime.py` and `src/maplebot/recorder.py` - Capture-time record assembly and encoder-thread-safe recorder handoff.
- `tests/test_replay.py`, `tests/test_frame_encoder.py`, and `tests/test_runtime.py` - Offline replay, diff, encoder, and timing coverage.

## Verification

- `PYTHONPATH=<checkout>\\src D:\\projects\\maple-external-bot\\.venv\\Scripts\\python.exe -m pytest -q tests/test_decision.py tests/test_replay.py tests/test_recorder.py tests/test_frame_encoder.py tests/test_runtime.py` - PASS, 51 tests.
- `D:\\projects\\maple-external-bot\\.venv\\Scripts\\ruff.exe check src tests tools` - PASS.
- `git diff --check` - PASS.
- Only temporary fixtures and fake encoder callbacks were used; no game was launched and no input was armed or sent.

## Decisions Made

- Rejected legacy, empty, malformed, duplicate-sequence, and non-monotonic policy records rather than falling back to frame perception.
- Kept replay input-free: it restores policy state, invokes `step_input`, and compares declared decisions only.
- Defined encoder replacement as explicit dropped/stale work and exposed a bounded cutoff result for Plan 03 stop ordering.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used the project virtual environment for verification**
- **Found during:** Task 1 verification
- **Issue:** The isolated worktree has no `.venv`.
- **Fix:** Ran the prescribed commands with `D:\\projects\\maple-external-bot\\.venv\\Scripts\\python.exe` and set `PYTHONPATH` to this checkout's `src`.
- **Verification:** All prescribed offline tests and Ruff passed.

---

**Total deviations:** 1 auto-fixed (1 blocking environment issue).
**Impact on plan:** No scope expansion; validation stayed capture-only and input-free.

## Issues Encountered

None after the prescribed offline verification passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 03 can use the sequence cutoff and bounded `flush_through` result when it orders safe-stop clip handling. Offline replay remains policy-only evidence and does not establish live-game input or gameplay effects.

## Self-Check: PASSED

- Task commits `9ca2c83`, `6250df2`, and `df177bd` are ancestors of this branch head.
- Created files `src/maplebot/frame_encoder.py` and `tests/test_frame_encoder.py` exist.

---
*Phase: 01-deterministic-input-and-safe-stop*
*Completed: 2026-10-24*
