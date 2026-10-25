# Fused minimap localization (p4c) — 2026-10-25

Offline only: no runtime integration and no input. The recording and labels live
under the gitignored `data/` and `artifacts/` directories.

## Result

On `session-1792947575721936400-manual` (287 frames, 1366x768, Blue Mushroom
bottom floor), the minimap-to-area transform scored against 44 reviewed feet
labels held out from their fold's fit:

| Axis | p50 | p95 | max |
|---|---|---|---|
| x | 3.5 px | 14.9 px | 17.3 px |
| y | 0.2 px | 0.2 px | 3.5 px |

One minimap pixel is about 16 area pixels (`scale_x` 15.95, `scale_y` 16.5).
The y labels are all on the floor, so y error says little about other heights.

The fused `MinimapTracker` matched the taught floor in 214/287 frames. The
other 73 frames were unknown:

- 21 vertical motion: jumps, falls and climbs.
- 14 waiting for a second fused observation.
- 11 name tag missing, weak or tracked-only.
- 10 with no unique taught platform.
- 9 waiting for a second platform observation (the 150 ms rule).
- 8 with the minimap collapsed or on another map.

None of the 29 frames where the registered feet were more than 4 px off the
floor got a platform. No location was reported without a minimap marker.

## Method

1. `register_view` finds each frame's camera offset to the reference view. It
   uses consensus template matches of textured patches; parallax scenery
   disagrees and drops out. On the clip, the offset matched the logged camera
   shift with correlation -0.9999. This is calibration only.
2. `tools/minimap_localization_probe.py label` proposes feet as name-tag feet
   plus the registration offset, and draws a review montage. In MapleStory the
   name tag is centered under the character's origin. A person reviewed all 48
   crosshairs: 4 were rejected (3 hanging on a rope, 1 occluded), leaving 44.
3. `evaluate` fits `MinimapTransform` per time fold (alternating 20-frame
   blocks) on frames that are not labels, and scores the labels in the other
   fold. It then replays `MinimapTracker` with the transform fitted on all
   unlabeled pairs.

`MinimapTracker` places the player with the marker. A platform requires:

- The name tag moving with the marker after camera correction (within 32 px).
- A stable height: marker y unchanged and name tag y within 3 px.
- A unique taught platform within 12 px of height.
- Two such observations at least 150 ms apart.

A gap of more than one second starts over.

## Limits

- Labels share the name tag with the fusion check, so they are not fully
  independent. The reviewed montage guards against tag/feet mismatch.
- One area, one clip. Ropes, higher platforms and other maps are untested.
- p4d must calibrate the transform live (walk calibration) rather than reuse
  this clip's fit.
