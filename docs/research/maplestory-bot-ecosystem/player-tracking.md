# Player detection, identity, and localization

Research date: 2026-11-01. Source-verified findings describe implementation, not measured gameplay success. Repository snapshots, maintenance and licensing: [source audit](evidence-maple-perception.md). Related: [navigation](navigation.md), [computer vision](computer-vision.md), [backlog](improvement-backlog.md).

## Current implementation assessed first

Our bot already has persistent player state; it is not a frame-independent template matcher.

| Existing capability | Actual source and evidence | Limit |
| --- | --- | --- |
| Sprite foreground/anchor matching, mirrored variants, color prefilter and batch candidate scoring | [`TemplateDetector._variants`, `_sprite_signature`, `_sprite_batch`](../../../src/maplebot/perception.py) | Outfit/pose/template coverage matters; an arbitrary fragment is not identity |
| Named identity from glyphs plus independently located body | [`_fuse_nametag`, `_occluded_tag_score`](../../../src/maplebot/perception.py) | Occluded-name confirmation requires a fresh sprite and evidence across both halves of the name |
| Partial tags near a prior named position | [`_follow`, `_partial_nametag`](../../../src/maplebot/perception.py) | Bounded elapsed time and gap; returned `tracked=True`, not fresh identity |
| Clean-tag-driven outfit template refresh | [`_refresh_sprite`](../../../src/maplebot/perception.py) | Nearby monsters veto template refresh to limit contamination |
| Camera and player-motion prediction | [`CameraTracker`, `_predict`, `_learn_motion`](../../../src/maplebot/perception.py), [`feature_translation`](../../../src/maplebot/camera_motion.py) | Prediction guides search; unknown camera motion disables motion extrapolation |
| Named sprite continuity and bounded reacquisition | [`ConfirmedSprites`, `Reacquisition.step`](../../../src/maplebot/reacquisition.py) | A fresh matching sprite can carry recently confirmed identity; lost identity pauses input and must reacquire the same player |
| Minimap marker and world/surface fusion | [`AreaMinimap`](../../../src/maplebot/minimap_reader.py), [`MinimapTracker.update`](../../../src/maplebot/localization.py) | Requires unique geometry and agreeing evidence; a marker is not exact feet/contact proof |
| ROI search with full-frame fallback and overlays | [`_observe_window`, `_tracking_snapshot`](../../../src/maplebot/perception.py) | Search prior and diagnostic box must remain distinct from accepted observation |

[`test_perception.py`](../../../tests/test_perception.py) covers background changes, gear changes, lookalikes, tag/sprite disagreement, partial names, chained tracking expiry, search fallback and prediction freshness. [`test_occluded_name_requires_a_fresh_matching_sprite_and_glyphs_across_the_name`](../../../tests/test_perception.py) is an important preservation case. These tests show intended safeguards; they do not establish real-scene success rates.

## What external bots actually implement

| Approach | Verified implementation | Transfer judgment |
| --- | --- | --- |
| Minimap template matching | Auto Maple [`Capture._main`](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/capture.py#L119), [`multi_match`](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/common/utils.py#L91): normalized correlation; first threshold crossing; retain old position on miss | Foreground occluders do not cover a separate minimap UI, but our current reader already exploits that. Do not copy stale-state semantics |
| Color/shape minimap marker | MS-Visionify [`find_player_minimap_marker`](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/screen_processor.py#L193): BGR range and local neighbor count | Narrow color assumptions and quadratic Python work are inferior to a tested connected-component reader |
| Title strip + glyph/body cues | MapleStoryAuto [`_find_color_anchor`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1358): HSV blue mask, removal of small components, row-strip proposals, horizontal closing, body-color checks | Useful lesson: multiple spatially independent cues. Blue title and red body assumptions are character-specific and not universal Classic features |
| Constant-velocity box tracks | MapleStoryAuto [`DetectionTracker.update`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L917): class/size/IoU/distance gates; sorted greedy assignment; smoothed box/velocity; confidence decay and missed-frame expiry | Actual persistent state, but not Kalman filtering or appearance re-identification. Our identity gate should remain authoritative |
| Minimap-guided screen estimate during loss | MapleStoryAuto [regression/fallback](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7078): recent screen/minimap pairs fit each axis; fallback applies minimap displacement | Demonstrates complementary sensors, not exact world coordinates. Camera clamp/scroll regimes and poor sample span can invalidate the linear fit |

No inspected Maple bot in this group establishes a general-purpose head/torso recognizer, arbitrary sprite-fragment re-identification, or reliable identity through unlimited full occlusion. A field named `player_yolo_model` or a training script does not prove the live player detector uses it; the inspected MapleStoryAuto player `detect` path explicitly prioritizes OCR anchor, title color, hold, then template candidates. [Actual dispatch](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2180).

## Occlusion policy by evidence state

| Situation | Appropriate use of evidence | Do not infer |
| --- | --- | --- |
| Bridge covers feet; name/head remain visible | Match known glyph/body cues; retain a feet-offset interval and platform candidates | Visible head box equals verified physical feet |
| Rope/pet covers part of name | Require distributed glyph agreement plus fresh independent sprite or bounded continuation of known identity | A shared name prefix proves identity |
| Another player overlaps our sprite | Preserve ambiguity; require full-name or independent identity recovery | Nearest box is necessarily our player |
| Body and name fully hidden, minimap remains | Use timestamped minimap/camera evidence for a search region or permitted bounded navigation feedback | Prediction is a new visual detection, safe attack evidence, or landing proof |
| Minimap also missing, stale, or contradicted | Release/pause through existing recovery gates; bounded search and operator handback on expiry | Continuous position from the last successful match |

This policy is a recommended interpretation of our existing safeguards, not a claim that external bots already implement it. Current `MinimapTracker` checks marker displacement against camera-corrected tag displacement and rejects ambiguous surfaces. Retain that cross-check instead of adopting an unconstrained screen/minimap regression.

## Motion models and uncertainty

Our player `_learn_motion` stores a displacement per observed frame and `_predict` reapplies it. Unlike the enemy tracker, it does not represent velocity in pixels/second with elapsed-time integration. **Inference:** varying capture cadence or dropped frames can mis-size the search prior. This is a focused evaluation opportunity, not evidence of a measured failure rate.

Compare three candidates on the same annotated replay: existing bounded displacement, timestamped alpha-beta position/velocity, and a small constant-velocity Kalman filter. A Kalman covariance is meaningful only if measurement/process noise is calibrated and camera uncertainty is included. For jumps, knockback and camera clamp transitions, increase uncertainty or reset the model rather than smoothing away a genuine state change. Start with elapsed-time normalization; do not add a tracker dependency solely because it is more sophisticated. Generic implementations are compared in [computer vision](computer-vision.md).

Minimap observations are quantized and mapped through separately validated transforms. Preserve coordinate labels: capture pixels, minimap pixels, reference-map/world coordinates, and camera offset. [Position evidence research](../../position-evidence-research.md) already documents why reference-client projection is not proof of our native client's exact rounding and why quantization prevents exact world reconstruction.

## Recommended incremental work

1. **Build independent occlusion labels before changing gates.** Extend the existing replay corpus with identity, visible fraction, body/nametag visibility, camera regime and ambiguous-player labels. Existing [`tracking_benchmark.py`](../../../tools/tracking_benchmark.py) says its truth comes from previously confirmed name boxes and interpolated hidden positions; useful regression evidence, but not independent ground truth during real occlusion.
2. **Compare timestamped prediction in the search layer.** Preserve `tracked`, confidence age, and `Reacquisition` semantics. Verification should include identical trajectories sampled at different cadences, jumps, reversals, missing frames and camera motion.
3. **Add cue-specific confidence calibration.** Measure false accepted identities separately for full name, partial name+fresh sprite, and carried sprite identity. A template score is not a calibrated probability.
4. **Evaluate fragment/head cues only where failure clips justify them.** A registered upper-body mask or separated sprite parts may recover covered feet, but generic fragment matches risk confusing other players or decorations. Require independent named identity, spatial spread and expiration.

Expected costs are estimates: elapsed-time prediction and evidence bookkeeping are small compared with template matching; new part searches add matching work and maintenance. No latency or accuracy improvement is claimed without a paired benchmark. Final priority and the single recommended milestone are owned by [the backlog](improvement-backlog.md).
