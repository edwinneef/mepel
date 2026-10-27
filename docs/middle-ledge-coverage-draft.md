# Over the Wall middle-ledge draft — 2026-10-27

Prepared a **review-only, disconnected interior span** at area x584–676,
y397.7. The active map remains revision 4. No runtime code, saved map,
calibration, teaching checkpoint, rope or navigation link was changed.

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
