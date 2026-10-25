---
phase: 01-deterministic-input-and-safe-stop
verified: 2026-10-25
status: gaps_found
score: 42/43 must-have checks verified
covered_files: [".planning/phases/01-deterministic-input-and-safe-stop/01-01-PLAN.md",".planning/phases/01-deterministic-input-and-safe-stop/01-01-SUMMARY.md",".planning/phases/01-deterministic-input-and-safe-stop/01-02-PLAN.md",".planning/phases/01-deterministic-input-and-safe-stop/01-02-SUMMARY.md",".planning/phases/01-deterministic-input-and-safe-stop/01-03-PLAN.md",".planning/phases/01-deterministic-input-and-safe-stop/01-03-SUMMARY.md",".planning/phases/01-deterministic-input-and-safe-stop/01-04-PLAN.md",".planning/phases/01-deterministic-input-and-safe-stop/01-04-SUMMARY.md","artifacts/input-realism-smoke-1792890372852900500.json","config.toml","pyproject.toml","src/maplebot/__init__.py","src/maplebot/__main__.py","src/maplebot/alarm.py","src/maplebot/autopotter.py","src/maplebot/capture.py","src/maplebot/catalog.py","src/maplebot/config.py","src/maplebot/debugger.py","src/maplebot/decision.py","src/maplebot/frame_encoder.py","src/maplebot/geometry.py","src/maplebot/input_timing.py","src/maplebot/keyboard.py","src/maplebot/perception.py","src/maplebot/probe_store.py","src/maplebot/recorder.py","src/maplebot/replay.py","src/maplebot/runtime.py","src/maplebot/static/alarm.wav","src/maplebot/static/index.html","src/maplebot/windows.py","tests/test_alarm.py","tests/test_autopotter.py","tests/test_capture.py","tests/test_catalog.py","tests/test_cli.py","tests/test_config.py","tests/test_debugger.py","tests/test_debugger_ui.py","tests/test_decision.py","tests/test_frame_encoder.py","tests/test_input_timing.py","tests/test_keyboard.py","tests/test_perception.py","tests/test_probe_store.py","tests/test_probes.py","tests/test_recorder.py","tests/test_replay.py","tests/test_runtime.py","tools/input_smoke.py"]
covered_digest: "v3:sha256:f496731fc39245bc9a239e56ce16603d70d966ec59854cf5ae02e6d7dda7ce6a"
behavior_unverified: 0
overrides_applied: 4
overrides:
  - must_have: "Pet food can be bound and probed"
    reason: "Original locked D-05 explicitly keeps pet food bind-only; probing and feeding belong to Phase 3."
    accepted_by: operator
    accepted_at: "2026-10-24"
  - must_have: "Per D-13, fatal worker exit invokes safe_stop without worker cooperation, leaves HTTP and alarm alive, supports direct acknowledge and fresh-worker restart, and restarts IDLE with input disabled, queues drained, calibration re-verification required, and every probe cleared."
    reason: "Later explicit operator requests preserve matching probes across restart and verify matching capture from confident recognition; input still starts stopped. See 01-CONTEXT.md amendments."
    accepted_by: operator
    accepted_at: "2026-10-25"
  - must_have: "Per D-02, current-session confirmed probes `{left, right, attack, jump, skill}` are required to arm; Up/Down/HP/MP are offered but optional in this phase, and every probe permission resets on process restart."
    reason: "Later explicit operator requests preserve matching probes across restart and verify matching capture from confident recognition; input still starts stopped. See 01-CONTEXT.md amendments."
    accepted_by: operator
    accepted_at: "2026-10-25"
  - must_have: "Per D-12, acknowledging an alarm permits rearm without repeating unaffected current-session probes, while restart/calibration/focus/window/backend invalidation clears the required permissions."
    reason: "Later explicit operator requests preserve matching probes across restart and verify matching capture from confident recognition; input still starts stopped. See 01-CONTEXT.md amendments."
    accepted_by: operator
    accepted_at: "2026-10-25"
gaps:
  - truth: "Arming remains blocked until the active alarm is acknowledged"
    status: failed
    reason: "The arm command enters pending_arm while the current alarm remains active; no active-alarm refusal is present."
    artifacts:
      - path: src/maplebot/runtime.py
        issue: "_command arm branch around line 830 omits the active-alarm guard."
      - path: artifacts/arm-alarm-gate-audit-1792890582357768300/evidence.json
        issue: "Fake-boundary reproduction: pending_arm with alarm_active=true; keyboard_events=[]."
    missing:
      - "Refuse Arm while the alarm is active before preparing the countdown."
      - "A behavioral regression proving refusal until acknowledgement, then permitted countdown."
human_verification: []
---

# Phase 01 — Goal Verification

**Verdict: gaps_found. Phase completion is blocked by one reproduced D-12 failure.**

Inline Codex goal-backward verification under the no-automatic-subagent fallback; no independent verifier is claimed. The skipped Plan 01-04 close-out is treated as an operator-selected documentation anomaly, never as evidence of implementation or completed requirements.

## Evidence Run

- Full suite after the stale-acknowledgement fix: **259 passed**; Ruff `src tests tools` passed; `pip check` passed.
- `tools/input_smoke.py` passed against its own temporary Tk window only: ordinary arrows, Down+Jump and Right+Jump receipt/order. Evidence: `artifacts/input-realism-smoke-1792890372852900500.json`; `game_verified=false`.
- Prior explicit operator observations: all nine offered control probes worked, and both debugger acknowledgement and F8 silenced the repeating alarm. These checks are not requested again.
- Stale-acknowledgement regressions first failed, then passed; real HTTP propagation and browser displayed-ID payload checks passed. ASVS L1 authored-register security audit has 14 closed threats and zero open.
- Decision coverage owner query reports 13/13 honored, non-blocking.
- Separate arming counterexample used a fake keyboard/audio Application. It did not advance the countdown or send native/game input.

## Roadmap Success Criteria

| Check | Status | Actual evidence |
|---|---|---|
| SC1 — Policy-only replay reproduces recorded decisions and reports deliberate changes | VERIFIED | PolicyInput and policy snapshot restore, strict sequence/capture-time validation, stable declared-field diff; replay tests cover exact replay, one deliberate changed decision and malformed/legacy records. |
| SC2 — Held input does not stall frames; timing visible and PNG off capture worker | VERIFIED | Serial executor submit returns before completion; runtime liveness test processes frames during a held fake key; bounded FrameEncoder worker and replacement/flush tests; live browser timing panels present. |
| SC3 — Complete key path, extended arrows and ordered chords | VERIFIED with D-05 override | Nine accepted game probes, extended-key flag tests and own-window receipt/order smoke; 1,000 seeded chord schedules. Pet food is bound but intentionally has no Phase 1 probe under locked D-05. |
| SC4 — Vertical leases expire and normal-action cap remains | VERIFIED | Fixed and total deadlines, strict-before-expiry renewal, generation cancellation and watchdog release; invalid/empty/nonvertical cases are active behavioral tests. |
| SC5 — Stop releases, records and classifies audible/silent incidents, including worker failure | VERIFIED | Release-first safe_stop ordering, idempotent/promotion tests, encoder cutoff and clip tests, fatal-worker/direct-control tests, runtime incident records, and operator-confirmed sound/acknowledgement. |

SC3's pet-food exception was a planning-time operator decision, not a new verification waiver. The additional D-12 arming condition below is not waived by persistent probes or automatic capture recognition.

## Additional Plan Boundary Checks

The five roadmap checks plus the 38 explicit plan boundary checks form the 43-check headline. Plan boundary checks retain their detailed empty/order/precision/cancellation cases rather than substituting source-presence assertions.

| ID | Status | Truth and evidence |
|---|---|---|
| 01-01-01 | VERIFIED | FND-02 unclassified edge is a flagged assumption: with a fake backend holding one key for the unchanged 0.25 s normal-action cap, submit returns before the hold completes and at least two capture/policy ticks complete during that hold; a bounded two-second regression test is the backstop. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-02 | VERIFIED | Per D-01, config.toml [input] is the sole binding source for left, right, attack, jump, up, down, hp_potion, mp_potion, pet_food, and skill; InputConfig validates the same fields and no data-file binding source exists. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-03 | VERIFIED | Per D-05, pet food is bindable but this plan creates no pet-food probe. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-04 | VERIFIED | FND-04 boundary: a vertical lease releases at now >= lease deadline and at now >= started_at + vertical_lease_max_seconds; the unchanged max_action_seconds = 0.25 continues to cap every normal action and ordered chord. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-05 | VERIFIED | FND-04 adjacency: renewal strictly before expiry extends only the short deadline and never the total deadline; renewal at or after expiry cannot resurrect the lease. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-06 | VERIFIED | FND-04 empty: renewing or releasing a nonexistent lease is a no-key-down idempotent result, while starting an empty or non-vertical lease is rejected. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-07 | VERIFIED | FND-04 ordering: stop, F8, failed safety gate, backend failure, and watchdog failure advance the controller generation, cancel queued work and leases, and win every race against a later renewal or key-down. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-08 | VERIFIED | FND-04 precision: NaN, infinity, out-of-range lease values, a total maximum below the short lease, and any attempt to grant a lease to a normal or chord action are rejected by bounded validation. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-01-09 | VERIFIED | FND-05 unclassified edge is a flagged assumption: 1,000 seeded schedules plus the own-window Tk smoke preserve Down-down before Jump-down and direction-down before Jump-down; this establishes scheduler and local Windows ordering only, not game reception. Evidence: keyboard.py/config.py/input_timing.py; active keyboard/timing/config/runtime tests; own-window input smoke. |
| 01-02-10 | VERIFIED | FND-01 adjacency: frame N's completed asynchronous ActionOutcome is adopted once as frame N+1's `PolicyInput.last_outcome`; no later frame reuses it and a not-yet-complete action yields an explicit pending/not-sent value. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-02-11 | VERIFIED | FND-01 empty: policy-only replay exits nonzero with a clear diagnostic for an empty log, a pre-Phase-1 record without PolicyInput, or a record missing the policy snapshot needed for deterministic continuation. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-02-12 | VERIFIED | FND-01 ordering: recorder sequence is strictly increasing, replay consumes that sequence without filename sorting, and duplicate/decreasing sequence ids or capture-relative timestamps fail instead of being reordered silently. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-02-13 | VERIFIED | Every policy timer receives the frame's session-relative monotonic capture timestamp; decision-start, replay wall time, PNG completion time, and action-executor wall time never replace it. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-02-14 | VERIFIED | An unchanged policy replays every logged frame with zero differences, while a deliberate policy change produces stable `policy-diff.jsonl` rows for only `state`, `action.kind`, `action.seconds`, `reason`, and serialized target differences. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-02-15 | VERIFIED | FND-06 unclassified edge is a flagged assumption: with a deliberately slow fake encoder and three rapidly published frames, capture-stage counters complete without waiting, the queue remains size one with explicit replacement accounting, and the newest frame becomes available within a bounded two-second test. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-02-16 | VERIFIED | Stop during queued encoder or recorder work uses a sequence cutoff and bounded flush barrier: accepted data through the stop frame is flushed before clip trigger when possible; encoder failure/timeout records incomplete encoding but cannot prevent key release or terminal stop work in Plan 03. Evidence: decision.py/replay.py/frame_encoder.py/runtime.py; replay/encoder/runtime lifecycle tests. |
| 01-03-17 | VERIFIED | SAFE-01 adjacency: simultaneous watchdog, worker-finally, debugger-timeout, and operator stop calls release keys idempotently but coalesce into one incident id, one clip trigger, one history record, and at most one alarm start. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-18 | VERIFIED | SAFE-01 empty: safe_stop creates an incident directory/event and returns a clip path even when no recording session or encoded pre-roll frame exists; missing frame data is explicit rather than preventing the stop record. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-19 | VERIFIED | SAFE-01 ordering: input disable/generation cancellation/key release completes before encoder cutoff flush, recorder trigger, sticky status/history publication, and alarm start, in that order. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-20 | VERIFIED | Per D-06, a runtime-owned AlarmManager loops the packaged `static/alarm.wav` with winsound filename/async/loop flags, holds the package-resource path for playback lifetime, and uses a repeated MessageBeep fallback without importing audio from decision.py. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-21 | VERIFIED | Per D-07 and D-10, the debugger Acknowledge action or F8 stops an active alarm; without acknowledgment the WAV/fallback repeats indefinitely and never auto-times out. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-22 | VERIFIED | Per D-08, debugger Stop and F8 used as an emergency stop when no alarm is active are silent terminal incidents. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-23 | VERIFIED | Per D-09, capture worker crash, input watchdog/backend failure, armed focus/obscuration loss, armed calibration invalidation, armed player uncertainty, and debugger command timeout are ALARM; no targets, operator stop, dry-run/capture-only stops, and probe completion are SILENT. Every new stop call must name an explicit severity. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-24 | VERIFIED | SAFE-02 unclassified edge is a flagged assumption: fake winsound verifies looping flags, repeated fallback, indefinite active state, silent-pause separation, and both acknowledgment paths; a bounded local audio check may confirm PC output but is not game evidence. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-25 | VERIFIED | Per D-11, the debugger receives a sticky stop record containing incident id, severity, stable code, message, time, clip path, acknowledged state, and encoder-completeness status; the same code-bearing record is appended once to history. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-26 | FAILED — BLOCKER | Per D-12, acknowledgment preserves probes and arming remains blocked only until the alarm is acknowledged; probes clear only for calibration/focus/window/input-backend causes, while rearm clears the sticky banner and still enforces player, calibration, countdown, and required-probe gates. Evidence: runtime.py arm branch and isolated pending_arm/alarm_active=true counterexample. |
| 01-03-27 | VERIFIED (operator amendment) | Per D-13, fatal worker exit invokes safe_stop without worker cooperation, leaves HTTP and alarm alive, supports direct acknowledge and fresh-worker restart, and restarts IDLE with input disabled, queues drained, calibration re-verification required, and every probe cleared. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-03-28 | VERIFIED | SAFE-03 unclassified edge is a flagged assumption: an injected fatal capture exception must yield released keys, one clip/reason/alarm, responsive direct acknowledge, and one fresh IDLE worker within bounded one-second fake-thread assertions; native process survival remains a later local acceptance check. Evidence: runtime.py/alarm.py/debugger.py; stop/alarm/worker tests and recorded operator audio observations. |
| 01-04-29 | VERIFIED | Per D-01, the debugger displays effective bindings read-only from InputConfig and offers no binding editor, save endpoint, or second data source. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-30 | VERIFIED (operator amendment) | Per D-02, current-session confirmed probes `{left, right, attack, jump, skill}` are required to arm; Up/Down/HP/MP are offered but optional in this phase, and every probe permission resets on process restart. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-31 | VERIFIED | FND-03 idempotency: confirming the same completed manual probe twice changes no state and sends no second key; an already confirmed probe may be intentionally rerun only through a new explicit probe request/countdown. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-32 | VERIFIED | FND-03 concurrency: while any countdown, manual confirmation, or potion-effect window is active, a second probe request is refused before input; stop/F8/safe_stop cancels the active probe generation and no late confirmation can pass it. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-33 | VERIFIED | Per D-03, Up warns exactly `stand away from portals and ropes`, then uses the normal three-second focus countdown and one short cap-bounded tap; Down follows the same countdown/tap flow, and manual success is recorded only after the operator confirms the observed effect. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-34 | VERIFIED | Per D-04, an HP/MP probe refuses without sending when its fresh confident matching bar is at or above 95%, otherwise snapshots the baseline, sends one normal bounded tap, and passes only on a fresh gain of at least 1.0 percentage point within the validated 2.0 s window. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-35 | VERIFIED | Per D-05, pet food appears in the read-only bindings but has no probe button, command path, permission, or acceptance step. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-36 | VERIFIED | Per D-07, D-11, and D-13, the same debugger page exposes Acknowledge, structured sticky stop details, and dead-worker Restart alongside probe state; those controls remain direct and worker-independent. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-37 | VERIFIED (operator amendment) | Per D-12, acknowledging an alarm permits rearm without repeating unaffected current-session probes, while restart/calibration/focus/window/backend invalidation clears the required permissions. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |
| 01-04-38 | VERIFIED | The debugger exposes capture/perception/policy/annotation/publish timing and separate encoder PNG timing/replacement status; it never folds PNG time back into capture-worker latency. Evidence: runtime.py/debugger.py/index.html/probe_store.py; probe/HTTP/persistence/runtime tests and nine accepted controls. |

## Artifact and Wiring Checks

- Config bindings flow through InputConfig, validated KEYS, TimingPlanner and the serial KeyboardController. The configured live input cap remains 0.25s; leases have separate bounded deadlines.
- Capture-relative PolicyInput and ActionOutcome flow through Agent.step_input, recorder JSON records and policy-only replay. Encoder publication is bounded and outside the capture thread.
- Controller callbacks and fatal worker exit reach safe_stop. Direct acknowledgement/restart survive a dead capture worker. Stale HTTP acknowledgement now validates the displayed ID while F8 intentionally acknowledges the current incident.
- Effective bindings, probes, timing, sticky incident details, copy/acknowledge and restart are wired to the debugger. The browser shows unnumbered collapsible panels and recognition-based capture verification.
- Saved probe profiles are signatures of the relevant title/layout/key/HUD reference, not a second binding source. Retests revoke approval; capture-only constructs DisabledInput; restart/recognition never enables input.
- **Failed wiring:** Arm validates capture and required probes but omits the active-alarm refusal present in the probe and live-potion start paths.

## Test Quality Audit

| Tests | Linked requirements | Disabled | Strongest assertion | Verdict |
|---|---|---|---|---|
| test_replay.py | FND-01 | 0 | Exact roundtrip, literal deliberate-change diff count, malformed-order rejection | Behavioral; replay roundtrip is a determinism property, not a claim of external oracle parity. |
| test_keyboard.py, test_input_timing.py | FND-02..05 | 0 | Terminal events, cancellation, lease expiry/renewal and 1,000 independent schedule seeds | Behavioral |
| test_frame_encoder.py, test_runtime.py | FND-02/06, SAFE-01/03 | 0 | Blocking fake boundary, replacement/flush/failure, release-before-effects and direct dead-worker lifecycle | Behavioral |
| test_alarm.py, test_debugger.py, test_probes.py | SAFE-02, FND-03 | 0 | Loop/fallback lifecycle, HTTP ID forwarding, resource-specific effect windows and stale confirmation rejection | Behavioral |
| Existing arm tests | D-12 active-alarm refusal | 0 | Required probes/capture are checked; active-alarm refusal was not exercised | **Missing behavioral coverage; reproduced implementation failure.** |

No disabled-only requirement or circular external-parity fixture was found. A passing suite does not close the untested arming invariant; its fake-boundary counterexample takes precedence.

## Reviews and Anomalies

- Security: passed at authored-register ASVS L1; T-01-10 is fixed in b5685b5 without accepting risk.
- UI: 20/24 advisory source/DOM assessment; no raster capture or independent reviewer is claimed.
- Source review/disposition: CR-01 open (arming alarm guard), IR-01 open (stale restart tooltip). Review is advisory; CR-01 independently fails a must-have and blocks goal verification.
- 01-04-SUMMARY.md records explicit mark-and-skip. The original reconstructed close-out was not created, and this report does not rewrite that disposition.

## Deferred Scope

Standalone live Autopotter was explicitly added, but full sustain/preemption, independent resource cooldowns, effect/exhaustion/critical-HP checks, pet feeding and spot/navigation policy remain Phase 2–5 work. Native live-sustain and portal-recovery effects are not inferred from the successful control probes or offline tests and are not asserted as Phase 1 completion evidence.

## Required Gap Closure

Refuse Arm while an alarm is active before starting its countdown; cover an active alarm rejection, unchanged input generation/state and zero key events, followed by acknowledgement and an allowed explicit arm request. Then rerun the existing phase verification gates. No repeated game probe round or recording is requested.

