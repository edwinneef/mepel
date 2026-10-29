# One separate Henesys Park session

Prepared offline. Do not start this session until the operator explicitly requests it.
No combat, manual recording, recalibration, map import or repeated control probes are
needed. The current 214×58 minimap is supported; do not ask to enlarge it.

## Saved preparation and remaining uncertainty

Use Mushroom/Henesys Park **100000200**, saved area
`de45b3cf261f4e6c9200a1cc407d355e`, revision 3. Start on `fh90` at public world
**x3190, y574**, about 100 pixels left of the only ladder. The accepted start range
is x3100–3240 and y574±20. Stay away from portals.

Already observed: 14/14 calibration pulses, left/right walking, jumping, short up/down
ladder controls and return to ground. Reuse the 62-pair calibration, imported map and
engine-restored control confirmations. Evidence:

- `artifacts/town-live/1793249932316741700/calibration-run.json`
- `artifacts/town-controls/1793250664265852900/result.json`
- `artifacts/town-checks/1793250792795366700/result.json`

The last full batch passed left/right/jump, then the first route stopped before
approach movement. Its input gate reported uncertain/stale fused feedback while the
last recorded window was focused. The last encoded capture preceded the stop by
507.398 ms, but the recording does not include the feedback evaluated at dispatch.
**Age expiry versus motion/marker uncertainty remains unresolved.** Do not describe
the 500 ms timeout as the proven cause. The installed source now records that exact
decision pair, its age, motion/marker state and stage, retaining the failure after
subsequent frames arrive. No freshness limits, watchdogs or input gates changed.

The planner selects `fh190` near the ladder's top. Public collision geometry is still
an assumption; native upper landing/contact is one of the remaining checks. Do not
try alternate surfaces or change geometry during this session.

## Offline preparation command

The prepared manifest is `artifacts/henesys-park-session/bundle.json`. To regenerate
after a reviewed offline code/map/binding change, with the engine still stopped:

```powershell
.venv/Scripts/python.exe -m tools.town_check --plan |
    Set-Content -Encoding utf8 artifacts/henesys-park-session/bundle.json
```

`--plan` uses saved files only; it never constructs a debugger connection. The bundle
pins source, complete saved profile and input bindings, plus all three route targets.
The future run refuses changes or missing engine-restored left/right/jump/up/down
confirmations before input. Local hashes do not prove which code an old process loaded;
start the installed source once at the beginning of the new session.

## Future session: one batch, then release the PC

1. Announce the restart. Start the engine once through
   `tools/restart_engine.ps1 -EnableGameplayInput`, then
   `tools/start_overlay.ps1 -WaitForEngine`. Keep this setup separate from test timing.
   Allow at most two minutes for setup. If a latched alarm, missing recognition,
   missing controls, wrong map/start position or focus prevents readiness, stop and
   report the exact blocker. Do not focus the game, acknowledge alarms, travel,
   re-import, recalibrate or debug interactively.
2. With Bot Off and the operator's already-focused game at the start spot, run once:

   ```powershell
   .venv/Scripts/python.exe -m tools.town_check --run --bundle artifacts/henesys-park-session/bundle.json
   ```

   First: two seconds of passive, healthy, advancing fused feedback, with no input.
   Then exactly three route requests: `fh90 → fh190` via the ladder, `fh190 → rope1`
   with confirmed grip, and `rope1 → fh90` with confirmed lower landing. No-op
   routes do not count. Each route has the existing 70-second checker limit,
   including countdown (engine route budget remains 60 seconds); maximum route
   polling time is 210 seconds. HTTP/clip/cleanup overhead is separate; this is not
   a hard wall-clock guarantee. F8 remains available throughout.
3. Stop at the first failure. No retry, repair, tuning or extra probe during this
   PC session. The checker requests Stop after attempted movement, saves every
   step's clip and the final Off readout in
   `artifacts/town-checks/<timestamp>/result.json`. Passive refusals retain samples
   and send no commands. Inspect clips offline afterward. Stop acceptance and Off
   status alone do not independently prove physical key release.
4. After Stop, shut down the engine through its normal command and close the overlay
   gracefully, releasing the PC. Report all three segment results (including skipped
   segments), setup/test/cleanup times, final Off/shutdown result and evidence paths.
   Finish the session within seven minutes of starting setup; if budget is running
   out, request Stop and end rather than start another segment. Do not restart again.

Acceptance is one observed upper landing, grip on the same ladder and descent to the
starting ground, ending Off with released input. Missing native evidence keeps this
requirement pending. This session is not a sustained automation or farming test.
