# Offline farming validation, 2026-10-31

Evidence: `artifacts/offline-farming-20261031-validation/`. No game attachment,
focus request, engine restart, gameplay input, asset download or live test ran.
Existing dirty `AGENTS.md` and `CLAUDE.md` were preserved.

## Repairs and checks

- `src/maplebot/farming.py`: invalid HP/MP percentages and confidence now take the
  existing unreadable-HUD stop path. Includes NaN, infinity, booleans, strings and
  out-of-range percentages. Twenty-two regression cases first produced 18 failures
  and four passes; all pass after repair.
- `src/maplebot/live_position.py`: restore the capture-only provisional-platform
  fallback after the tracker's no-surface reason changed to include ropes. Its
  existing opt-in, pinned-map, observation-only and navigation-refusal tests pass.
- `tests/test_cli.py`: model immediate key release and assert that release precedes
  server shutdown and worker cleanup. No actual restart or process exit is performed.
- `tests/test_computed_navigation.py`: verify proof saving stays deferred until
  cancellation after input release. Test data stays in pytest temporary directories.

The full Python suite initially had six failures (four outdated CLI fixtures,
one outdated proof-save expectation, and the localization bug). The repaired
suite passes **1,122 tests in 57.27 seconds**. Commands and logs:

```powershell
.venv/Scripts/python.exe -m pytest -q --junitxml=artifacts/offline-farming-20261031-validation/python-final.xml
.venv/Scripts/ruff.exe check src tests tools
# From ui/:
npm.cmd test -- --reporter=default --reporter=json --outputFile=../artifacts/offline-farming-20261031-validation/ui.json
npm.cmd run build
```

Ruff passes. All 111 UI tests in 20 files pass. The build runs TypeScript checking
and Vite, and installs the UI assets into `src/maplebot/static/workbench`.
Previous assets are in the evidence directory's `workbench-backup/`. Python uses
the editable source checkout. The running engine was left untouched.

## Replay and simulation evidence

- `python -m tools.recognition_eval --report <evidence>/recognition.json`:
  630 scored frame entries, 99.7% visible identity recall, zero wrong identities,
  zero off-target tracked boxes and at most one pixel fresh position error.
  Saved-frame recovery includes successful reacquisitions and a justified occlusion
  timeout. There are 575 unique labels and 1,417 unlabeled frames: replaying an
  unlabeled frame cannot establish recognition accuracy. Required route-pose gaps
  are empty, but air/back, hit/left, hit/right, transition/back and transition/right
  remain unverified. Saved coverage/configuration was not overwritten.
- `python -m tools.navigation_harness --seeds 1000 --output <evidence>/navigation.json`:
  all 1,007 synthetic round trips and fault cases pass.
- `python artifacts/offline-farming-20261031-validation/navigation_matrix.py`:
  54/54 timing variations and 16/16 injected faults pass. Across six saved maps,
  500/1,212 platform-route model experiments arrive; 712 stop. Their reasons are
  578 edge deadlines, 96 corridor departures, 23 departure retry limits, 12
  unexpected/excluded surfaces, two replan limits and one route-budget refusal.
  Another 436 routes are skipped (357 unsupported rope/climb routes and 79 without
  a safe route within the edge budget). All experiments clear held input, pending
  events and tickets, with zero harness invariant violations. Map hashes match.
  These are counterexamples under illustrative physics, not proven native route
  failures or native passes; do not tune the real gates to satisfy this model.
- `python -m tools.calibrate_navigation_physics --output <evidence>/physics.json`:
  zero accepted ballistic fits. Two flights support only an approximate 78-pixel
  rise constraint with a 16-pixel margin. Speed, acceleration, braking, gravity
  and jump speed remain unidentified. Defaults and calibration data are unchanged.
- `python artifacts/offline-farming-20261031-validation/latency_probe.py`:
  tests direct masked normalization as an artifact-only candidate, then replays
  both complete saved clips twice against historical observations. Full results,
  exact-output comparisons, catalog startup and detection timings are in
  `latency.json`. Eight numerical fixtures agree, but direct normalization is
  roughly 2.4–20 times slower on those fixtures. It is rejected; production
  recognition is unchanged. Both 241-frame passes have zero exact output changes;
  mean detection times are 70.2 and 73.3 ms/frame, with 74.6 and 78.1 ms p90.
  Catalog startup took 34.9 seconds. No latency improvement is claimed.

Full tests also cover no-consumables suppression, repeated target acquisition,
combat ticket attribution, low/unreadable HP/MP, camera motion, focus/identity
loss, route handoffs, delayed tickets, cancellation, Stop and shutdown ordering.
They exercise policies and adapters with fake observations/controllers. They
cannot prove OS key delivery, actual watchdog/F8 operation, overlay lease behavior,
capture freshness in a live session, terrain contact, real hits or kills.

`summary.json` records command runtimes and measured wall time. Summed command
time includes overlap and is not total elapsed time. Replay startup includes
catalog loading; final latency passes run after the other heavy checks finish.

## Smallest remaining supervised check — not authorized by this report

1. Operator present, explicit authorization for the exact batch, bot-friendly
   server, intended map and clear continuous floor confirmed. Use existing
   accepted controls only while bindings/calibration still match. Require fresh
   recognized player identity, calibrated/readable HP and MP, active overlay
   lease and all readiness gates. Missing evidence or a gate refusal stops setup.
   If a restart is needed, announce it and use only
   `tools/restart_engine.ps1 -EnableGameplayInput`, followed by
   `tools/start_overlay.ps1 -WaitForEngine`. Recheck readiness after restart.
2. Run one minute of single-platform, no-consumables combat, substituting the
   freshly verified area ID:

   ```powershell
   .venv/Scripts/python.exe -m tools.farming_check --run --area <verified-area-id> --single-platform --session-minutes 1 --bot-friendly-server
   ```

   Expected: deadline reached, completed attack dispatches for at least two
   distinct target acquisitions, no potion/feed input, and confirmed Off after
   Stop. The clip must separately show actual attacks/hits; dispatch is not hit
   evidence. Low HP/MP or operator Stop is a safe stop, not functional success.
3. At the first failure: release every key, save the clip, sound the alarm, leave
   the game open and hand control back immediately. Never investigate with the
   character exposed or repeat an unchanged failing run. A failed focus request
   or denied gate is not retried or bypassed.

This minimal check does not close multi-platform acceptance. All taught-route
navigation, rope/climb behavior, a native combat check and the original bounded
15-minute farming acceptance remain separately pending. Only a separately
authorized supervised batch may run `tools.navigation_check --run --all-routes`,
`tools.combat_check --run`, or the 15-minute farming runner. Preserve earlier
observations and stop at that batch's first failure.
