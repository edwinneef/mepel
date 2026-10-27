# Over the Wall middle-ledge draft — 2026-10-27

The original draft prepared a **review-only, disconnected interior span** at
area x584–676, y397.7. The active map remains revision 4. That preparation changed
no runtime code, saved map, calibration, teaching checkpoint, rope or navigation
link. The session-only supplement described below keeps the same saved-map boundary.

The versioned proposal is [drafts/over-the-wall-middle-ledge.json](drafts/over-the-wall-middle-ledge.json).
It records the exact active-map hash, retained screenshot hashes, manual pixel
bounds, candidate segment and evidence limits. This is a proposal, not a teaching
checkpoint; the workbench does not load it automatically.

## Screenshot and calibration evidence

The saved reference shows the ledge approximately between x568 and x689, with
an uneven visible top around y397–405. The candidate covers only the interior;
it does not claim full width or collision endpoints. Existing platforms remain
identical, including the separately taught P2 named “Middle ledge”.

Two retained frames, sequences 3606 and 4507 in the proposal, register to the
saved reference with the same translation: reference = screen + (9, -142).
Five and four of 28 textured patches agree, respectively. Both show the same
stationary standing point; these are repeated observations, not independent
measurements of width.

The unchanged minimap transform maps their marker (46.5, 40.5) to
(666.708, 397.667). Registered logged name-tag feet are (665, 401), a difference
of (-1.708, +3.333) pixels. The candidate height is the rounded calibrated height,
consistent with the source used by existing taught platforms. Calibration was
neither refitted nor shifted to force agreement.

The earlier 39 stationary teaching samples establish one nearby point only;
they were not extended into a walked span or used to manufacture transitions.
The visible ladder remains an image feature, with no new rope or connection.

## Offline verification

Replayed the same 13 retained logs as [the readiness report](over-the-wall-readiness.md):
1,573 available frame occurrences, 1,053 distinct capture timestamps, and 28
missing-PNG rows excluded. Current minimap pixels were read again; player/camera
observations came from the logs.

- Existing map: 618 platform matches and 435 unknown captures.
- Isolated candidate: 1,000 platform matches and 53 unknown captures.
- 382 additional matches, all on the new draft segment at the repeated stationary
  point; every existing platform match kept its original surface.
- No platform result lacked a marker or fresh player observation.
- All seven protected JSON/config files and retained replay sources kept their
  hashes. The active profile hash is
  `9826e92b7d38eb1e370afef812418034fc3b07ff4ac2e55b18878cec58cdc4e8`.
- All 33 existing links are identical. The new ledge is unreachable from home
  in the explicit graph; P5/P16 exclusions remain as documented in
  [bounded-navigation.md](bounded-navigation.md).

These are coverage/consistency results. They do not verify physical contact,
collision endpoints, localization accuracy, ladder usability or native arrival.
No gameplay input, capture, recording, engine restart or native test was performed.

## Reproduction and reversibility

```powershell
.venv/Scripts/python.exe tools/prepare_middle_ledge_draft.py --output artifacts/middle-ledge-coverage-20261027
```

Use a fresh artifact directory for another run. The tool refuses existing output,
paths outside this checkout's `artifacts/`, a changed active-map basis, changed
retained evidence, registration/calibration disagreement and existing-match
regressions. It has no activation or restore command and writes no user data.

The local bundle contains `candidate-profile.json`, the exact original bytes in
`active-profile-before.json`, `report.json`, `source-hashes.json`, and three
annotated evidence crops. The candidate retains revision 4 as its basis; it has
not been saved as a new revision and must not be copied over the active profile.
Discarding the proposal requires no rollback: ignoring the bundle leaves the
active map and teaching checkpoint exactly as before. Any activation is separate
work requiring explicit authorization.

Ruff and 64 focused localization, minimap-reader and profile tests passed.

## Session-only localization supplement

The runtime now supports an explicit **Observe middle ledge** toggle under
**Navigation → Teach map**. It is available only in a capture-only session tracking
the exact unchanged revision 4 profile. It starts off after every process restart
or map switch. **Stop observing middle ledge** disables it without a map save.

A separate fallback tracker uses the screenshot span. The original tracker and
saved profile remain unchanged. Existing platform matches always take priority;
the fallback can replace only an otherwise unknown, uncovered-platform result.
Fresh marker/player, fused-motion and confirmation-time gates remain in force.
Supplement matches are marked provisional and excluded from navigation surface
feedback. The game drawing labels the span in amber as observation-only coverage.

Enabling does not write settings, geometry, calibration or a teaching checkpoint.
Teaching/calibration, leaving idle capture observation, changing the pinned profile
bytes or changing the loaded profile disables the supplement. Returning to the
previous state does not re-enable it automatically. Its fixed data is in
`src/maplebot/localization_supplement.py`, matching the versioned draft above.

Do not merge the span into the active map. `navigation_evidence.build_evidence`
requires exact archived geometry: the full candidate would lose all movement
evidence even with identical links. The supplement instead preserves all 33
saved links, the exact 29 usable movement-edge records and the P5/P16 exclusions.

The versioned API command is `position_supplement` with `{"enabled":true}` or
`{"enabled":false}`. Enabling requires idle capture-only observation and no
teaching/calibration. Disabling remains available during area editing.

Verification: 77 focused Python tests, all 76 UI tests, Ruff, TypeScript and the
production UI build passed. The actual `LivePosition` implementation replayed
1,053 distinct retained captures: 618 → 1,000 platform matches, including 382
provisional matches and zero existing-surface regressions. All seven protected
files and all 29 usable navigation-edge records remained identical. This still
does not establish contact, full width or native movement effects.

Local evidence and rollback backup:
`artifacts/middle-ledge-supplement-20261027/` contains `before.zip` (previous
runtime/workbench), `protected-before.json`, `validate.py` and `replay.json`.
Normal reversal is the toggle or a restart; no saved-data rollback is needed.

Deployment is complete after the operator restarted with `tools/restart_engine.ps1`
in capture-only mode. The new engine session
`d38d1bebfd69434e8250a25b6a4dc49c` accepted and published the input-free
enable → disable → enable cycle. The supplement is enabled for this session;
another process restart or map switch leaves it off again.

The served JavaScript matched the built workbench bytes. The live engine reported
revision 4 and 29 usable edges at each control-check step. Independent disk checks
confirmed identical movement-edge records, the same map fingerprint, all 33 saved
links and all seven protected file hashes. No gameplay input or new recording
was requested. A provisional ledge match was not observed during this short
control check; retained-frame coverage remains the offline evidence above.

`deployment.json` records the live state cycle and asset hash, and
`deploy_check.py` records the task-local procedure in the same artifact directory.
The procedure is pinned to this session and refuses to overwrite its report.
