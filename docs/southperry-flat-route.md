# Southperry: first flat-platform test proposal

Prepared offline from the saved 234-frame capture and existing source geometry.
No engine command, new capture, game input, map modification, download or
reserved-map inspection is part of this preparation.

The proposed test is **one leftward walk toward a point 80 source-world pixels
away**, on the same flat platform by the blue house. Proposed start X 45,
target X -35, source floor Y 287. Both are inside the previously observed
horizontal range (-87 to 49). The proposed launch band is X 41-49; the arrival
band is X -67 to -3 (32 pixels around the target). These are proposed coordinates,
not independently verified actor-position labels or a current launch location.

Source footholds cover the corridor and the existing 34-pixel horizontal
footprint margin. The saved Southperry profile maps both endpoints to `fh2`;
the full proposed stopping corridor passes the existing zone/boundary checker.
That saved transform includes historical calibration and is diagnostic only.
It is not a substitute for proving the automatic-positioning path.

## Exact blockers

1. **Same-platform targets are unsupported.** The actual `nav_go` method raises
   `You are already on that platform`. A `fh2 -> fh2` graph preview contains
   zero edges and would not perform this walk. A bounded same-platform target
   needs implementation through the existing navigation/controller gates.
   No runtime command or executable test was added here.
2. **Automatic positioning remains locked.** `_gate` refuses any nonempty
   `position.automatic`; `_trusted_feedback` also rejects it. This is currently
   an unconditional code restriction, not an enable checkbox. The feet/actor
   origin and minimap discrepancy need verified resolution before that path can
   legitimately satisfy the gates. Do not remove the gate, clear the automatic
   flag or silently switch to historical calibration to make this test run.
3. **Live authorization and current setup are absent.** This invocation approves
   offline preparation only. No current launch position or runtime readiness is
   claimed. The last observed engine was capture-only with no tracked route.

## Required before one live attempt

- Operator present on the bot-friendly server and explicitly authorizes the
  exact attempt, setup and any missing control probes. Only left/right controls
  are required for this flat walk; both directions are required by the existing
  navigation control check. Existing offline walk/left and walk/right recognition
  coverage matches the captured character identity.
- Load the verified runtime implementation, using `tools/restart_engine.ps1
  -EnableGameplayInput` if a restart is necessary, after telling the operator.
  Retain the valid overlay/control lease, watchdog, F8, window/title/DPI/privilege,
  confirmed capture, focus and unobscured-view checks.
- Track the matching Southperry profile revision/hash, load and preview the
  supported target, and confirm fresh same-player/minimap feedback at the origin.
  No editing, calibration, active probe or unacknowledged alarm. During movement,
  fused feedback must remain within the existing 0.5-second freshness limit.
- Recheck the live starting band, platform and stopping room. Refuse a different
  location rather than automatically walking into position. Explicit supervision
  opt-in remains required.
- Enforce **one attempt**, the existing **3-second countdown**, at most
  **3 seconds of active movement**, then **1 second of settled observation**.
  These are the proposed test bounds, not implemented controls or a prediction
  of travel time. The current navigator's 60-second route-wide budget alone
  does not enforce this shorter test. Setup/probes are additional time.
- Passing evidence must show leftward movement into the accepted target band,
  stable same-platform arrival, zero held keys after Stop and no unintended
  action. First failure ends the batch: release input, save the clip, alarm,
  leave the game open and return control immediately. Never retry unchanged.

## Offline checks and reproduction

`artifacts/southperry-flat-route/prepare.py` pins input hashes, checks the source
floor/footprint and saved route corridor, exercises the real same-platform and
automatic/capture-only refusals with inert objects, and verifies matching walk
pose coverage. It constructs no engine or keyboard controller and has no network
or live-run path. Run from the repository root:

```powershell
.\.venv\Scripts\python.exe artifacts/southperry-flat-route/prepare.py
```

Output: `artifacts/southperry-flat-route/plan.json`. A successful preparation
still records `runnable: false` until the requirements above are met.

Preparation assertions passed. Six existing navigation-runtime checks passed in
0.57 seconds: automatic-position refusal, capture-only refusal, explicit opt-in
and countdown cancellation, same-platform refusal, pose coverage, and physical
focus/freshness gates. These use test controllers, not the game. No live run,
restart, tracking/import command or gameplay input was performed.

The full-map scenery renderer is a separate task. Reading the layout supplies
placements across the whole map at once; visiting each piece is unnecessary.
The known missing copied artwork payload is `Map/Obj/_Canvas/_Canvas_000.wz`
(61,310,435 bytes), plus its required index metadata. Links inside it have not
yet been traced, so complete picture availability is not established. Completing
that artwork is not a prerequisite for preparing this flat-platform test.
