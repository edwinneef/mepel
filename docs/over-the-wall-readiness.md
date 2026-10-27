# Over the Wall readiness — 2026-10-27

**Partial pass for observation; native navigation remains unverified.** Revision 4
recognizes the map and supports stable localization on covered platforms. It does
not cover every place the player can stand. No gameplay input, new recording,
engine restart, calibration change or map save was performed for this validation.

## Existing recordings

Replayed all 13 retained decision logs that reference Over the Wall using the
current `AreaMinimap`, `MinimapTracker`, slope-aware platforms and the unchanged
saved transform. Player detections and camera shifts came from the logs; the
full sprite detector was not rerun. No independent feet labels exist for this
map, so these are coverage/consistency results, not measured localization accuracy.

- 1,573 available frame occurrences, representing 1,053 distinct capture timestamps.
  Overlapping clips were counted once in the distinct totals. Another 28 log rows
  had no retained PNG and were excluded.
- All available frames matched the Over the Wall minimap and a unique marker.
- 618 distinct captures produced a platform match; 435 remained unknown. Of those,
  414 had no matching saved platform, 16 were fusion/platform warmup, two were
  vertical motion and three lacked a fresh name-tag/player detection.
- No replayed platform result lacked a marker or fresh player detection.
- Known surfaces in these recordings include P1, P3 and P7. Initial differences
  from logged classifications reflect resetting the tracker at each clip boundary;
  logged classifications are not ground truth.

The retained frame
`data/recordings/session-1793054706422588800-dry-run/00003606.png` visibly shows
ScrollAddict on the small middle ledge. Its marker maps to approximately
**(666.7, 397.7)**. Neither saved platform crossing that x coordinate is near its
height, so returning unknown is consistent with the saved geometry.

The earlier teaching log has 39 nearby ground samples at exactly one coordinate,
approximately (634.8, 397.7): zero observed horizontal span. The later teaching log
has none there. Those samples cannot establish a platform width or justify
inventing a connection. Other unknown positions also occur outside taught spans.

## Current capture

Observed one unchanged capture-only engine session for 60 seconds using HTTP GETs:
562 polls and 294 distinct early-detection frames. Capture stayed stopped for
gameplay throughout; the five saved movement confirmations were not retested.

- 203 distinct frames matched a platform; 91 were unknown. Observed surfaces were
  P3 (147), P4 (55) and P9 (one). These counts do not verify physical contact.
- P3 remained continuously reported for an observed 19.04-second interval.
  The longest unknown interval was 3.10 seconds.
- Drawing-packet age at the HTTP client: median **307.6 ms**, p95 **422.3 ms**,
  maximum **789.6 ms**. Encoded-frame age: median **402.9 ms**, p95 **520.9 ms**.
- Early packets were 93.8 ms newer on average in paired samples. No sampled
  detection exceeded the 1.5-second drawing cutoff. This does not measure native
  renderer paint/compositor delay or unsampled spikes.
- Saved-terrain projection was eligible in 389/562 polls (69.2%). Nine polls had
  position age over 500 ms; renderer gates require hiding these stale projections.
  Other interruptions included name-tag uncertainty, vertical movement, warmup
  and positions outside taught geometry.

All seven protected current JSON/config files retained their hashes. All replayed
source PNGs, logs and the active map/reference also retained their hashes.

## Controls and remaining work

The existing identity-control tool recovered all five retained minimap miss images
without losing or changing a previously accepted marker. Both saved references
matched themselves and rejected the other map. The focused minimap, localization,
position and early-drawing tests passed: 27 tests. None proves contact or arrival.

Keep P5/P16 excluded as documented in `bounded-navigation.md`. Preserve the existing
movement confirmations. Whole-map readiness is limited by uncovered geometry;
prepare any correction as a reversible draft from retained screenshots, without
adding unsupported movement links. The P3-to-P2 and rope-route native acceptance
checks remain deferred and were not attempted here.

## Evidence

Local artifacts: `artifacts/over-the-wall-readiness-20261027/` contains `replay.json`,
per-frame replay rows, source hashes, `live.json`, per-poll live rows, the initial
capture, `identity-controls.json` and `coverage-witnesses.json`. The task-local
`validate.py` implements the replay and 60-second GET-only sample. Its outputs
refuse overwrite; copy it to a fresh sibling artifact directory for another run.

Identity controls were run with:

```powershell
.venv/Scripts/python.exe tools/validate_minimap_mask.py --before artifacts/minimap-mask-fix/before.py --output artifacts/over-the-wall-readiness-20261027/identity-controls.json --controls-only
```
