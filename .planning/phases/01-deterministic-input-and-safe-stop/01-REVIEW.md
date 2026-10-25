---
phase: 01-deterministic-input-and-safe-stop
reviewed: 2026-10-25
depth: standard
files_reviewed: 24
files_reviewed_list:
  - src/maplebot/__main__.py
  - src/maplebot/alarm.py
  - src/maplebot/autopotter.py
  - src/maplebot/capture.py
  - src/maplebot/config.py
  - src/maplebot/debugger.py
  - src/maplebot/decision.py
  - src/maplebot/frame_encoder.py
  - src/maplebot/input_timing.py
  - src/maplebot/keyboard.py
  - src/maplebot/probe_store.py
  - src/maplebot/recorder.py
  - src/maplebot/replay.py
  - src/maplebot/runtime.py
  - src/maplebot/windows.py
  - src/maplebot/static/index.html
  - tests/test_alarm.py
  - tests/test_debugger.py
  - tests/test_frame_encoder.py
  - tests/test_input_timing.py
  - tests/test_keyboard.py
  - tests/test_replay.py
  - tests/test_runtime.py
  - tools/input_smoke.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: issues_found
---

# Phase 01: Code Review Report

## Summary

Inline standard-depth review under the Codex no-automatic-subagent fallback; no independent reviewer is claimed. Scope includes the phase evaluation-scope resolver's source changes and the operator-authorized persistence, recognition and standalone-potion follow-ups. The skipped 01-04 close-out was not used as implementation proof.

No further critical or warning finding was established after b5685b5. Tests: 259 passed; Ruff and pip check passed. The own-window SendInput smoke passed and explicitly reports game_verified=false. Actual game control/audio observations are recorded separately in 01-04-CHECKPOINT.md.

## Narrative Findings (AI reviewer)

### IR-01: Restart tooltip describes superseded setup

**Severity:** Info

**Location:** `src/maplebot/static/index.html`, `restart-bot` title.

The tooltip still instructs reattachment and capture confirmation after restart. The current implementation reconnects a unique matching saved window and verifies it from confident recognition. The stale wording can suggest unnecessary setup work. Update the tooltip to describe automatic reconnection and stopped input. This is advisory copy debt, not an input-boundary failure.

## Boundary Checks

- Both HTTP acknowledgement and Application.request now require and compare incident IDs under stop_lock; F8 intentionally targets the current alarm. Stale/missing/unknown request regressions and the real HTTP handler test pass.
- Controller safety, stop generation and emergency state precede key-down and lease renewal. Queue, timing budget, lease caps and watchdog expiry are bounded. Completion disables one-shot probe/potion input.
- safe_stop releases keys before recorder/encoder/audio effects. Worker-failure, competing-stop, direct acknowledgement/restart and stale encoded-frame regressions exercise lifecycle transitions.
- Replay consumes capture-relative PolicyInput and explicit policy snapshots, reports deliberate decision differences, rejects malformed ordering, and creates no input backend. The encoder runs in a bounded worker rather than the capture loop.
- Saved confirmations match title/layout/key and relevant HUD signatures. Retesting revokes old approval. Recognition does not enable input and cannot repair an active-mode verification failure mid-run.
- Live Autopotter remains separate from combat and preview; tests cover priority, shared cooldown, disabled resources, focus/geometry/confidence failure, portal HUD grace, cancellation and backend failure.
- No external package or network upload was added; debugger remains bound to loopback with Host/token validation.

## Limitations

This standard review is not a proof of all concurrent interleavings or future Phase 2–5 behavior. Full sustain requirements, spot anchors, potion exhaustion and autonomous movement remain deferred. The original 01-04 execution summary remains an operator-selected skipped anomaly.
