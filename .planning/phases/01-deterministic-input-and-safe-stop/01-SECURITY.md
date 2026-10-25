---
phase: "01"
slug: deterministic-input-and-safe-stop
status: draft
threats_open: 1
asvs_level: 1
block_on: high
register_authored_at_plan_time: true
created: "2026-10-25"
---

# Phase 01 — Security

Preliminary L1 verification of the authored PLAN threat register. The Plan 01-04 close-out was explicitly marked-and-skipped; that disposition does not accept any security risk. No implementation files were modified by this audit.

## Trust Boundaries

- Pixel/window observations to keyboard authority and controller watchdog.
- Localhost Host/token-protected debugger requests to acknowledgement/restart/probe methods.
- Captured frames and policy records to bounded encoders, recorder and offline replay.
- Repository checkout to offline editable installation and local persistent probe records.

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation / evidence | Status |
|---|---|---|---|---|---|---|
| T-01-01 | Spoofing | `KeyboardController` safety gate | high | mitigate | keyboard.py _execute_schedule / start_vertical_lease / renew_vertical_lease; runtime.py _input_block_reason; tests/test_keyboard.py and test_runtime.py | CLOSED (L1) |
| T-01-02 | Denial of Service | serial input queue and leases | high | mitigate | keyboard.py bounded Queue(maxsize=32), deadlines, generation cancellation, _watch and close; lease and cancellation tests | CLOSED (L1) |
| T-01-03 | Tampering | `InputConfig`, `KEYS`, ordered chords | high | mitigate | config.py InputConfig / ProbeConfig validation; keyboard.py configured-key whitelist; input_timing.py ordered constructors; timing/config tests | CLOSED (L1) |
| T-01-SC | Tampering | npm/pip/cargo installs | high | mitigate | Standard-library implementation and repository-owned WAV; repeated offline local editable installs with no-index/no-deps/no-build-isolation and protected-file comparisons; backups under artifacts/ | CLOSED (L1) |
| T-01-04 | Tampering | policy-only replay input | high | mitigate | replay.py strict policy-input validation and policy-only replay; decision.py PolicyInput; tests/test_replay.py | CLOSED (L1) |
| T-01-05 | Denial of Service | `FrameEncoder` and recorder queues | high | mitigate | frame_encoder.py bounded replacement slot, flush_through and bounded close; tests/test_frame_encoder.py | CLOSED (L1) |
| T-01-06 | Information Disclosure | encoded screenshot/recording output | medium | mitigate | recorder.py local data path/retention and replay.py input-free path; no upload added by the phase; replay/recorder tests | CLOSED (L1) |
| T-01-07 | Tampering | stop reason/severity routing | high | mitigate | runtime.py StopSeverity and STOP_REASONS, unknown-code rejection; exhaustive registry tests in test_runtime.py | CLOSED (L1) |
| T-01-08 | Denial of Service | cross-thread safe_stop/alarm/encoder | high | mitigate | runtime.py safe_stop releases controller before encoding/recording; alarm.py asynchronous playback/event fallback; bounded flush/close and stop-order tests | CLOSED (L1) |
| T-01-09 | Elevation of Privilege | worker restart/input authority | high | mitigate | runtime.py restart_capture and __main__.py restart lifecycle leave input disabled; restored confirmations and automatic recognition follow later operator-authorized context amendments; no automatic input enablement | CLOSED (L1) |
| T-01-10 | Spoofing | debugger acknowledge/restart | high | mitigate | OPEN: debugger.py discards acknowledge payload and calls app.acknowledge_stop() without an incident ID; runtime.py acknowledge_stop acknowledges the current alarm unconditionally. Isolated reproduction: artifacts/stale-alarm-audit-1792889830206894400/evidence.json | OPEN |
| T-01-11 | Spoofing | manual probe confirmation | high | mitigate | runtime.py confirm_probe requires active id/generation and awaiting_confirmation reached only from terminal outcome; _cancel_active_probe; tests/test_probes.py | CLOSED (L1) |
| T-01-12 | Tampering | HP/MP visual confirmation | high | mitigate | runtime.py request_probe / _advance_potion_probe enforce full-bar refusal, confidence, fresh sequence/time, resource match and finite deadline/gain config; tests/test_probes.py | CLOSED (L1) |
| T-01-13 | Elevation of Privilege | arming/probe permissions | high | mitigate | Operator-amended mitigation: probe_store.py exact layout/binding/HUD signatures and runtime required sets; capture-only DisabledInput, explicit start and disabled restart; persistence/recognition/input-lock tests | CLOSED (L1) |

## Open threat: T-01-10

A delayed acknowledgement request for incident A can silence incident B because the HTTP handler never passes the supplied incident ID to the acknowledgement method, and the method acknowledges whichever alarm is current. Loopback Host and X-Debug-Token checks are present; the authored stale-click rejection part is absent. The current payload/UI is also not bound to an incident ID.

The reproduction creates an isolated Application with fake keyboard/audio boundaries, acknowledges A, creates B, then submits acknowledgement with A's ID. The returned record is B with acknowledged=true. Evidence includes keyboard_events=[]; no native sound or gameplay input was used.

Proposed mitigation for a future authorized fix: bind dashboard acknowledgement to the displayed incident ID and compare it under stop_lock before changing the alarm. Keep F8 as an intentional acknowledgement of the current active incident. Add a regression rejecting A while B is current.

## Accepted Risks Log

No accepted risks. Mark-and-skip applies only to the missing close-out.

## Security Audit Trail

| Audit date | Threats total | Closed at L1 | Open at high threshold | Scope |
|---|---|---|---|---|
| 2026-10-25 | 14 | 13 | 1 | Authored register; amended persistence/recognition decisions; fake-boundary stale acknowledgement reproduction |

## Sign-Off

Pending. Phase advancement remains blocked by T-01-10 until mitigation is verified or the operator explicitly accepts the risk. The configured code/UI reviews and phase-goal verification have not yet run in this resumed sequence because the security step requires an open-threat decision first.
