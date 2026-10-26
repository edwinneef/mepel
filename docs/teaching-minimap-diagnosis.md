# Saved teaching minimap failures — 2026-10-26

The initial diagnosis below records baseline `ac90fc0`, without changing the
production reader or saved data. Fix validation follows at the end. No new
capture, recording or gameplay input was used for the offline work.

## Finding

The five retained Over the Wall miss images are false map-identity rejections.
They show the same minimap at the reference crop (x=4, y=72, 135x70), each with
exactly one detectable player marker. Identity agreement is 0.8355–0.8478,
just below the unchanged 0.85 threshold. Both the fixed crop and the reader's
search return the same position and agreement: this is not crop misalignment.

`AreaMinimap.__init__` excludes navy and low-saturation dark backgrounds from
its static identity mask. It leaves dark, saturated translucent pixels between
the rocks. The main game scenery shows through those pixels as the camera moves.
They are then compared as though they were opaque terrain. The diagnostic image
`artifacts/minimap-diagnosis/comparison.png` shows the changing scenery and the
rejected pixels alongside the unchanged terrain.

Of 3,345 reference identity pixels, 887 have HSV value below 80. Those pixels
account for 467–504 of the 497–536 mismatches in each saved failure (90–94%).
Excluding them in an isolated mask experiment retains 2,458 reference pixels
and raises same-map agreement to 0.9788–0.9867. The 0.85 acceptance threshold
and player-marker detector were not relaxed. Blank, covered and the saved
Blue Mushroom reference remain rejected; the other-map score is 0.1244.

This experiment isolates the failure mechanism. A fixed value cutoff is not
yet a validated production solution across maps, lighting or capture layouts.

## Recording evidence and limits

| Saved log ending | Checks | Unreadable | With fresh name tag during unreadable check | Longest consecutive unreadable run |
| --- | ---: | ---: | ---: | ---: |
| `1792974870718327400.jsonl` | 1,216 | 84 | 83 | 32 |
| `1792976752344706900.jsonl` | 913 | 373 | 362 | 164 |

The latest log contains 373 map-identity rejections and no separate marker
rejections. The earlier log contains 80 identity rejections and four missing
markers. These are counts of recorded checks, not independent accuracy samples.

Only five miss PNGs were retained: `LivePosition.update` caps identity-failure
screenshots at five per teaching instance. Their timestamps identify the latest
session. The JSONL logs omit identity scores and frame identifiers, so the images
cannot establish the cause of all 373 failures or reconstruct every missed path.

`MapTeacher.add` clears its previous observation and climb run when a marker
is unavailable. Long rejection runs therefore remove movement evidence and can
contribute to missing route links. This evidence does not establish that either
reported missing return journey was actually performed.

## Reproduce

```powershell
.venv\Scripts\python.exe tools\teaching_minimap_diagnosis.py
```

At baseline the summary reported five saved images and five rejections.
Add `--expect-readable` for the red-capable reproduction: it exits 1 while those
images fail the actual production `AreaMinimap.read` path. After the fix below,
it reports zero rejections and exits 0.

Use `--output artifacts\minimap-diagnosis\NEW_REPORT.json` for full per-image
scores, marker coordinates, mask trials, negative controls and source SHA-256s.
The tool refuses to overwrite an existing output. It verifies that all source
files it read have unchanged hashes before returning. The completed report is
`artifacts/minimap-diagnosis/report.json`.

## Recommended follow-up

Correct the static identity mask for translucent background pixels, retaining
the identity threshold, minimum terrain coverage, capture-size check and unique
marker requirement. Validate against the retained failures, existing recordings,
wrong-map/covered/ambiguous controls, and bright and dark terrain before installing.
Keep the current draft; no further walk or recording is needed for this work.

## Fix and validation

The production identity mask now excludes reference pixels with HSV value below
80, in addition to the existing background/marker exclusions. It conservatively
requires at least 200 retained terrain pixels; a dark-only reference is rejected.
The 0.85 identity threshold, 24-channel-value comparison tolerance, capture-size
check, moving-marker exclusions and unique player-marker check remain unchanged.

- All five retained failures now read their unique player marker, with identity
  agreement 0.9788–0.9867 (`artifacts/minimap-mask-fix/diagnosis-after.json`).
- Before/after replay of 2,624 PNGs across 23 existing recording folders loses or
  changes no previously accepted marker. The 287 supported Blue Mushroom frames
  retain exactly 279 accepted and eight unknown readings. All 287 remain rejected
  by the Over the Wall reader. The other 2,337 PNGs have unsupported capture sizes
  and remain rejected; they do not establish map-identity performance.
- Both saved references match themselves and reject each other. The five Over
  the Wall miss images remain rejected by the Blue Mushroom reader. Blank and
  covered controls reject. Results are in `recordings.json` and `controls.json`
  under `artifacts/minimap-mask-fix/`.
- New synthetic regression tests reproduce the dark saturated background failure
  and verify rejection of dark-only references. The full suite passes 439 tests;
  Ruff passes. Existing grey/navy, moved, covered, different-map, ambiguous-marker
  and capture-size tests remain passing.

Reproduce the full saved-image comparison (use a fresh output filename):

```powershell
.venv\Scripts\python.exe tools\validate_minimap_mask.py `
  --before artifacts\minimap-mask-fix\before.py `
  --output artifacts\minimap-mask-fix\NEW_REPLAY.json
```

The preserved baseline is the reader from `ac90fc0`. The validator includes the
retained miss images and cross-reference controls; `--controls-only` skips the
recording folders. PNG hashes are checked before return. Overlapping clips are
not independent samples. These offline results establish recovery of the saved
failures and the stated controls, not live navigation or every historical miss.
