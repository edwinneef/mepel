# Minimap localization validation â€” 2026-10-25

## Result

On the same 120-frame subway recording used for the scenery-anchor baseline,
minimap-marker motion passes the name-tracking cross-check in **91/120 frames
(75.8%)**, versus **13/120 anchor-aligned frames (10.8%)**: 78 more usable frames,
or 65 percentage points more coverage. The yellow marker is detected in 120/120.

These are different coverage gates, not a comparison of labeled absolute-position
accuracy. The anchor probe required two agreeing scenery patches; this probe
requires agreement between minimap-derived displacement and independent logged
name-track displacement after camera correction. It does not validate a platform
ID, rope attachment, map identity or a completed move. Accuracy remains null.

## Method

- Read only existing PNGs and `decisions.jsonl`; no capture, keyboard backend or
  runtime integration. The CLI writes only a new output directory and refuses
  to overwrite it. The existing editable install makes the offline tool available.
- Recognize the saved native-1x, 1023x766 expanded-minimap UI from an explicitly
  selected header crop and panel borders. Other resolutions, covered headers,
  missing PNGs and incomplete minimaps stay unknown.
- Find a unique yellow marker with the native 6x6/24-pixel shape. Generic yellow
  connected components confused map decoration and clipped markers with players;
  the initial run is retained in `artifacts/minimap-validation/run-1`. The final
  native-shape method is in `run-2`. Multiple matching markers remain unknown;
  name tracking is never used to pick a convenient candidate.
- Register textured minimap terrain between consecutive frames, independently
  of the dot. Subtract minimap scrolling before computing marker displacement.
  Reject low-quality or ambiguous registration. This matters in the town clips,
  where the minimap itself can scroll.
- Require consecutive sequences, capture-time gaps no larger than one second,
  and fresh untracked `nametag:` detections with confidence >=0.90 in both frames.
  Sprite-only or weak/tracked-only detections cannot validate a dot.
- Compute name-derived world displacement as change in name-derived feet minus
  the recorded screen-camera shift; require camera confidence >=0.35.
- Fit scale on the separate town recording
  `session-1792887641233734800-clip`, using nonoverlapping six-motion (seven-frame) blocks with
  at least three minimap pixels of net movement. Seven block estimates give a
  median of **16.0364 game pixels per minimap pixel**. Freeze this scale for every
  other recording. The other recordings contain zero overlapping calibration
  capture IDs. Calibration is horizontal; the same scale is assumed vertically
  and evaluated by the held-out checks, not independently calibrated there.
- Count a frame as aligned only when both displacement axes agree within
  **24 game pixels** (about 1.5 minimap pixels). The first frame is uncheckable.
  A marker alone is insufficient. This is an adjacent-frame consistency check;
  it does not establish drift-free absolute coordinates over a long run.

## Per-recording results

The 13/120 anchor baseline was measured only on the marked subway clip; there
is no corresponding scenery-anchor baseline for the other maps. The calibration
row is in-sample and must not be described as held-out validation.

| Recording | PNGs / records | Unique dot | Aligned |
|---|---:|---:|---:|
| `session-1792886153915899200-clip` | 120/120 | 120/120 | **96/120** |
| `session-1792886156297340700-clip` | 120/120 | 120/120 | **96/120** |
| `session-1792886163425491100-clip` | 120/120 | 120/120 | **96/120** |
| `session-1792886173927525300-clip` | 120/120 | 120/120 | **93/120** |
| `session-1792886180373768400-clip` | 120/120 | 120/120 | **113/120** |
| `session-1792886182475221000-clip` | 120/120 | 120/120 | **116/120** |
| `session-1792886189866135800-clip` | 120/120 | 120/120 | **116/120** |
| `session-1792886365679548600-clip` | 46/46 | 46/46 | **41/46** |
| `session-1792886373673510400-clip` | 75/75 | 75/75 | **68/75** |
| `session-1792886506238679200-clip` | 120/120 | 120/120 | **105/120** |
| `session-1792886510484475900-clip` | 120/120 | 120/120 | **113/120** |
| `session-1792886516006942200-clip` | 120/120 | 120/120 | **119/120** |
| `session-1792886520138059800-clip` | 120/120 | 120/120 | **119/120** |
| `session-1792887451089585800-clip` | 120/120 | 75/120 | **0/120** |
| `session-1792887502680721500-clip` | 120/120 | 62/120 | **7/120** |
| `session-1792887511377697000-clip` | 120/120 | 95/120 | **40/120** |
| `session-1792887529241918700-clip` | 120/120 | 120/120 | **91/120** |
| `session-1792887539611541800-clip` | 120/120 | 120/120 | **80/120** |
| `session-1792887555423993800-clip` | 120/120 | 120/120 | **46/120** |
| `session-1792887564129702400-clip` | 120/120 | 120/120 | **60/120** |
| `session-1792887592588526900-clip` | 120/120 | 120/120 | **119/120** |
| `session-1792887641233734800-clip` **calibration** | 120/120 | 120/120 | **117/120** |
| `session-1792887854167147500-clip` | 47/47 | 47/47 | **46/47** |
| `session-1792888007516281700-clip` **baseline clip** | 120/120 | 120/120 | **91/120** |
| `session-1792905519259413900-manual` | 9/129 | 0/129 | **0/129** |

The dataset has **2,817 logged records, 2,697 PNG-backed records and 1,474 unique
capture timestamps**. Incident clips overlap, so these rows are not independent
samples and must not be pooled into an accuracy claim. The tiny 106x15 manual
crop has nine PNGs and 120 missing PNGs. The editor-covered recording has no
fresh usable name tracking, so its aligned count stays zero even where a dot
later becomes visible.

## Baseline-clip rejection and sensitivity

Of the baseline clip's 120 frames, 101 have a measurable cross-check: **91 agree
and 10 disagree**. The remaining 19 comprise the first frame, 14 frames without
fresh name evidence in both observations, and four without trusted screen-camera
motion. Across the 101 measured pairs, the 95th-percentile residual is 16.46 pixels
horizontally and 29.61 vertically. Disagreement is not automatically attributed to
the minimap: name positioning, camera estimation and marker-update timing can
also contribute.

With the fitted scale fixed, acceptance is **77/120 at 12 pixels**, **87/120 at
16 pixels**, **91/120 at 24 pixels**, and **97/120 at 32 pixels** per axis. The
24-pixel threshold was fixed before the reported pass and was not relaxed to
accept disagreements.

An additional six-motion (seven-frame) displacement check passes **56 of 63 checkable windows**
within 24 pixels. These windows overlap. Name/camera gaps make other windows
uncheckable; this is not a 56/63 accuracy measurement.

## Reproduce and inspect

```powershell
.venv\Scripts\python.exe tools\minimap_probe.py data\recordings `
  --reference data\recordings\session-1792888007516281700-clip\00000511.png `
  --output artifacts\minimap-validation\NEW_OUTPUT_DIRECTORY
```

Measured per-frame decisions, reasons, dot positions, both motion estimates and
residuals are in `artifacts/minimap-validation/run-2/<recording>.jsonl`.
`summary.json` contains the complete counts, scale estimates, reference hash,
calibration overlap and rejection reasons. `sensitivity.json` contains the
additional baseline checks. Tests cover unique and ambiguous markers, yellow
scenery, clipped dots, UI occlusion, resolution mismatch, minimap scrolling,
camera correction, wrong-dot jumps, missing evidence, separate calibration and
unchanged source files.

The evidence supports testing minimap coordinates as the primary localization
signal on these saved views. It does not yet support live arming or replacing
unknown results with extrapolation. A useful next experiment is a calibrated
walk-and-jump transform with explicit map identity and labeled position errors,
using existing recordings before requesting new footage.
