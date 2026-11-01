# Enemy occlusion tracking

The existing masked sprite detector still supplies all combat observations. A small
camera-compensated tracker assigns `enemy:N` IDs after detection. Predictions and partial
matches appear only in `Observation.enemy_tracks`, the diagnostics overlay and replay logs;
they never populate `Observation.monsters` or establish that an attack can connect.

Tracks expose `visible`, `partially_occluded`, `occluded`, and `lost`, with separate visible
bounds, estimated ground contact, confidence and horizontal/vertical uncertainty. Recent
camera-corrected movement estimates horizontal velocity. Nearby configured platform segments
constrain ground height. Hidden motion expands uncertainty in both directions to allow
reversals. Matching uses type, predicted ground distance, movement and detection confidence;
ambiguous one-to-one associations keep detections unassigned rather than inventing IDs.
Perfectly overlapping identical enemies cannot be distinguished from screenshots alone.

Configure `data/templates/enemy-occlusion.json` using
[`enemy-occlusion.example.json`](enemy-occlusion.example.json). Keys must exactly match the
detector's active map title. `reference` names a full screenshot inside the templates
directory, `regions` contains foreground rectangles `[x, y, width, height]`, and `platforms`
contains optional ground segments `[x1, y1, x2, y2]`, all in reference screenshot pixels.
The example covers the wooden bridge in the saved 1366×768 Snail Hunting Ground III view;
terrain segments deliberately exclude the uncertain ground inside the bridge.

Reference registration must agree with scenery before geometry activates; rectangles then
follow camera motion. Unknown camera motion clears geometry and requests registration again.
Capture-source, map, frame-size or enemy-search changes reset tracks. This supports translation only;
resolution changes need a matching reference. Geometry is reloaded with the detector.

In `[perception]`, `enemy_occlusion_seconds` defaults to 4 and `enemy_lost_seconds` to 0.5
(both finite, 0.1–10 seconds). Occlusion retention requires entry through a configured region.
Confidence decays without observations, and even repeated partial pixels cannot extend a
track beyond the last full detection plus the occlusion lifetime. Lost tracks expire;
removed IDs are never reused within a detector session.

Partial matching reuses the existing alpha masks and scorer. It searches at most 24 variants
of a known type within an 80-pixel horizontal radius, excludes foreground pixels, and requires
at least 24 textured pixels, 8% of the sprite mask, three rows and six columns, 90% color
agreement and 0.95 similarity. Evidence shared by plausible nearby tracks is rejected.
RGB-only references without a foreground mask do not support this partial search. Small,
flat-color fragments, wrong regions and changing poses can therefore remain fully occluded.

Run input-free recorded replay:

```powershell
.venv/Scripts/python.exe tools/enemy_tracking_replay.py data/recordings/<session> --output artifacts/enemy-tracking/<new-run>
```

Each fresh output directory contains `tracks.jsonl`, `summary.json` and annotated samples.
No capture, input controller or game commands are used. Counts on unlabelled recordings
are diagnostic coverage, not measured identity accuracy or combat success.

`tests/test_enemy_tracking.py` also exercises reversals, camera translation, expiry,
multiple/overlapping enemies and the attack-evidence boundary. Its controlled artwork
sequences composite a catalog Blue Snail over a cropped recorded bridge screenshot, with
known hidden/reversed positions. These are transformed fixtures, not unmodified recordings.
The fixture scene is cropped from
`session-1793518023198760000-combat/00002265.png` at `[400, 500, 320, 140]`; the alpha sprite
is `catalog/monster/100101-jump-2-7bfcccf0200d.png`.

Next improvement: hand-label identities and exposed pixels across naturally occurring
bridge crossings. This would measure ID switches/false partial matches and tune the
retention/search limits without broadening attack evidence.
