# Southperry: saved character-position evidence

Offline inspection used the existing 30-second capture in
`artifacts/southperry-live-20261101T041101Z/`. All 234 PNG hashes match the saved
receipts and scenery-analysis hashes. Every saved player observation is a fresh,
untracked name-tag detection at confidence 1.0. No new capture, gameplay input,
download, installed-archive read or reserved-map inspection was performed for
this analysis.

The saved box follows the player across the flat platform, but it is not an
independently measured character origin. `TemplateDetector.body_from_nametag` constructs
a 44×64 box using the name-tag text and `NAMETAG_FEET_GAP = 2`; it does not directly
detect the soles or prove ground contact.

| Saved measurement | Result |
| --- | --- |
| Box center/bottom, minus independently matched scenery translation | World proxy X −87 to 49; Y 290 throughout |
| First / leftmost / last proxy | (49, 290) / (−87, 290) / (−1, 290) |
| Closest source footholds at those X values | IDs 8 and 10, layer 1/group 0, Y 287 |
| Box-bottom proxy minus source platform | +3 pixels in every frame |
| Independent minimap-marker image match | Unique, exact opaque-pixel match in all 234 frames |
| Marker center in source minimap image | X 35–43, Y 106 |
| Minimap scale | 16 world pixels per minimap pixel |
| Existing shared-bias minimap estimate minus scenery/box proxy | X −5.96 to +22.04; Y +15.72 pixels |

The visible 210×138 minimap area matches the left portion of the copied 295×138
canvas: 94.8% exact opaque terrain pixels in the first frame, versus 14.7% for the
next horizontal-crop candidate. With that registration fixed, terrain agreement
stays at least 94.6% across the clip. Moving icons explain some terrain overlap;
this is separate from the exact player-marker match.

The minimap calculation reports the existing `public_map.MARKER_BIAS`
(−0.94, −7.17), measured on other maps, unchanged. It was not fitted to Southperry.
Without any marker-bias assumption, the raw metadata conversion yields marker
coordinates rather than certified character coordinates. Even the existing
bias produces disagreement on this clip, so exact marker pixels do not prove
precise actor XY. The saved capture has no engine `position` snapshots; these
offline reconstructions must not be reported as runtime position outputs.

Manual inspection of frames 0, 55, 117 and 233 shows the visible character on the
same flat platform. Unmodified enlarged crops and annotated copies are saved;
green marks source-platform screen Y 546, red marks inferred box bottom Y 549.
Those annotations visualize the discrepancy; they do not label a true actor
origin or establish collision/contact.

**Conclusion:** the capture supports stable relative horizontal tracking and
coarse agreement with this flat section. Precise feet/actor origin, collision,
slopes, falls, ladders and routes remain unverified. No per-map correction,
runtime alignment change or readiness grant was added. The three-pixel residual
is an observation, not a Southperry calibration value to install.

Reproduce offline from the repository root:

```powershell
.\.venv\Scripts\python.exe artifacts/southperry-live-20261101T041101Z/inspect_positions.py
```

Results: `position-summary.json` and `positions.jsonl` in that capture folder.
The summary pins source geometry, metadata and both minimap images by SHA-256.
