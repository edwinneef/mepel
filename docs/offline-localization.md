# Offline localization slice

This is an input-free Phase 2 probe, not a live navigator or an arming gate.
It uses existing PNG recordings, their logged player detections, and manually
marked reference geometry. No runtime settings, calibration or saved templates
are changed. NAV-01/02/03 and SAFE-04 remain incomplete.

## Decisions supported by the existing recordings

- Layout coordinates belong to a taught reference view, not the current screen.
  The subway recording `session-1792888007516281700-clip` contains visible
  scrolling in both axes. The foreground-anchor probe found absolute
  reference-to-frame offsets ranging from x=0 to 383 and y=0 to 136 pixels.
- The existing `CameraTracker` estimates translation between successive frames
  and returns zero for rejected estimates. Summing it would hide missed shifts
  and accumulate drift. The probe instead locates taught anchor crops afresh in
  every screenshot and subtracts their absolute offset from the player's feet.
- Two distinct anchors must have unique strong matches and agree within two
  pixels. Repeated beams, tiled floors, moving characters and parallax scenery
  are poor anchor choices. A lost, ambiguous or conflicting match means unknown.
- A minimap cross-check remains unproven. The inspected subway reference has a
  yellow marker, but there are no identity labels or minimap-to-layout transform
  in the saved data. Do not turn that color candidate into a trusted player or
  use it for whole-map navigation, which the project excludes.

## Implemented boundary

`src/maplebot/localization.py` provides reference geometry, an `AnchorMatcher`,
and a `SurfaceTracker`. It does not import the keyboard or runtime.

The tracker uses a confident, untracked player detection and the frame's capture
time. It requires two observations at least 150 ms apart, with no gap longer
than one second. Missing anchors, weak/tracked-only players, ambiguous geometry
and feet outside the taught surfaces immediately clear the candidate. A
knock-off therefore drops the old platform; a new platform must qualify again.
These fixed prototype thresholds are not deployed runtime configuration.

The result is a stable **spatial match**, not proof of grounded contact. Rope
proximity is deliberately called `near_rope`: overlapping a ladder in flight
does not prove attachment. Platform matches take precedence at rope endpoints.
This slice cannot confirm a completed move or renew a climb lease.

`tools/localization_probe.py` replays saved PNGs and logged `PolicyInput` player
boxes. Missing PNGs remain unknown. It does not rerun the player detector or
measure detection accuracy. Source recordings are read-only; existing probe
outputs are refused.

## Reproduce the measured probe

The following example geometry was manually marked for the offline subway
reference `00000511.png`. It is an illustrative probe, not an operator-approved
spot. Store this JSON in a new file under `artifacts/`:

```json
{
  "version": 1,
  "reference": "00000511.png",
  "anchors": [
    {"x": 348, "y": 365, "width": 53, "height": 32},
    {"x": 542, "y": 480, "width": 40, "height": 50},
    {"x": 588, "y": 340, "width": 62, "height": 30}
  ],
  "platforms": [
    {"id": "middle", "left": 0, "right": 1023, "y": 470},
    {"id": "lower", "left": 0, "right": 1023, "y": 600},
    {"id": "upper-left", "left": 0, "right": 695, "y": 347},
    {"id": "upper-right", "left": 886, "right": 1023, "y": 347}
  ],
  "ropes": [
    {"id": "middle-lower-ladder", "x": 562, "top": 470, "bottom": 600}
  ]
}
```

```powershell
.venv\Scripts\python.exe tools\localization_probe.py `
  data\recordings\session-1792888007516281700-clip `
  --layout artifacts\offline-localization\subway-foreground-probe-layout.json `
  --output artifacts\offline-localization\NEW_OUTPUT_DIRECTORY
```

Measured output is saved in
`artifacts/offline-localization/subway-foreground-replay/`:

- 120 logged frames over 30.40 seconds, at 1023x766 pixels.
- 13 frames aligned with at least two agreeing anchors.
- 11 stable platform matches; 109 unknown results.
- Unknown reasons: 75 frames with fewer than two unique anchors, 32 with
  conflicting anchors, and two awaiting the second surface observation.
- `input_sent: false`; accuracy is null because no ground-truth locations exist.

An earlier probe using two background patches aligned only the reference frame
(1/120), confirming that choosing scenery by texture alone is insufficient.
Both experiment outputs are retained under `artifacts/offline-localization/`.
These are coverage counts, not a success rate or native acceptance. The saved
1023x766 reference cannot be reused automatically for the current 1366x768 view.

Tests cover absolute scrolling, repeated/lost/conflicting anchors, capture size
changes, camera motion versus displacement, knock-off reacquisition, timestamp
ordering, tracked-only uncertainty, rope endpoints, ambiguous platforms, replay
determinism, missing PNGs, and unchanged source recordings.

## Next supported development

Use these existing recordings to test multiple taught reference views with
overlapping anchors and explicit transforms into one spot coordinate frame.
First prove that the same platform keeps its identity as the initial anchors
leave the viewport, and that wrong-map/repeated scenery stays unknown. Keep
this offline until that coverage and rejection evidence exists; then expose
spot teaching and location preview in the debugger. Climbing still requires
separate attachment, contact and post-release arrival evidence.
