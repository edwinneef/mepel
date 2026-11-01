# Southperry recorded-camera acceptance

The offline Southperry scenery/camera check is complete for the available tested views.
It found and fixed a shared camera-tracker defect; no map-specific visual bank or offset
was added to the runtime.

## What was checked

Frozen development references were the previously extracted house and star decoration.
Each screenshot is matched independently at 1:1 scale. Before expanding beyond the nine
development frames, the diagnostic gates were fixed: exact opaque fraction >=0.65/0.75,
best-versus-spatially-separated-runner-up margin >=0.10, and two source-placement camera
translations agreeing within one pixel. These are diagnostic acceptance thresholds;
runtime safety/readiness gates are unchanged. Blank and repeated scenes refuse.

The first full batch covered three saved clips: 393 logged Southperry rows, 361 available
PNGs and 32 pre-existing missing PNGs. All 361 available frames passed the two-anchor
check. Missing frames reset temporal state and remain in the coverage denominator.
The stock camera tracker was scored on 358 adjacent accepted pairs (38 moving pairs),
using pixels only. Logged player positions, calibration and camera estimates were not
inputs. The scenery answers were applied after prediction.

The old tracker accumulated **18.326 px** of drift. Individual step errors were small
(p95 0.249 px), demonstrating why checking single frames was insufficient.

## Root causes and changes

`src/maplebot/perception.py`, `CameraTracker.update`:

1. OpenCV's `phaseCorrelate` can modify arrays while applying its Hanning window. For
   optimal DFT sizes this corrupted the stored next-frame reference. Copying the inputs
   fixes a reproducible stationary-frame regression. This alone did **not** improve the
   1366x768 recordings; their padded transform sizes avoid the same mutation path.
2. Strong global correlation still accumulated bias in the recorded scenes, whose
   overlays/animation violate a pure translation. Existing distributed forward/backward
   feature verification is now preferred whenever its unchanged >=0.60 confidence gate
   passes. Phase correlation remains a search hint and the existing fallback. Feature
   count, spatial spread, consistency, displacement, weak-correlation and safety gates
   were not weakened. No per-map branch, asset, calibration or readiness override exists.

Two regression tests failed before their corresponding fixes and pass afterwards:
stationary windowing drift, and a biased high-correlation estimate corrected by verified
features. Existing weak-correlation, large-motion and unrelated-frame tests still pass.

## Final measured results

The corrected tracker was replayed against the exact frozen scene answers and frame
hashes; it never receives those answers as prediction input.

- Original three clips: 361 frames, 358 scored pairs, 38 moving pairs, horizontal span
  213 px. Step error p95 **0.000092 px**, maximum **0.000214 px**, maximum accumulated
  drift **0.004327 px**.
- Audit of all saved recording logs found 11 Southperry logs. First/middle/last available
  samples from the remaining eight logs all matched: 24/24. No unknown/reserved map
  frames were decoded.
- A fourth full clip selected from that audit included vertical camera motion: 120/120
  frames accepted, 119 scored pairs, 11 moving pairs, vertical span **8 px**. Step error
  p95 **0.000061 px**, maximum accumulated drift **0.001913 px**.
- 58 affected perception/camera/scenery checks and 183 runtime, navigation, input-timing,
  first-visit and shutdown checks pass. Ruff and `git diff --check` pass.

These small numerical errors measure camera translation against static raster anchors.
They are **not** subpixel native world-position or character-foot accuracy. The two
anchors are parts of one known house. The long recordings cover a limited Southperry
region and only eight pixels of vertical movement. Full-map vertical scroll, native
feet/contact, collision, routing, live behavior and unseen-map performance remain open.

## Installation and evidence

The existing editable installation imports the corrected `src/maplebot/perception.py`.
Rollback source/hash receipt: `artifacts/southperry-camera-rollback/`. The running engine
was not restarted, reloaded or activated; no new recording, capture or gameplay input
was used. No saved map, profile, calibration or existing recording was changed.

Evidence and executed-run inventory:

- `artifacts/southperry-camera-check/`: original frozen references/baseline.
- `artifacts/southperry-camera-corrected/`: window-copy-only replay; unchanged recorded
  drift retained as a failed hypothesis for this specific symptom.
- `artifacts/southperry-camera-feature-corrected/`: final replay.
- `artifacts/southperry-additional-coverage.json`: 24-frame audit.
- `artifacts/southperry-vertical-camera-check/`: fourth full clip.
- `artifacts/southperry-camera-verification.md`: all runs and command/test timing.

Tools: `python -m tools.check_southperry_camera --help` builds raster references;
`python -m tools.replay_southperry_camera --help` scores a changed camera tracker against
them. Use new output paths. References remain evaluation-only and never enter runtime.

The next acceptance step requires the operator present and explicit authorization for
a bounded Southperry capture-only check. Any engine restart must use the managed
restart script. Gameplay input and route testing remain unapproved.
