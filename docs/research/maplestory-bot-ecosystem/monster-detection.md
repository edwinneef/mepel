# Monster recognition, tracking, and target evidence

Research date: 2026-11-01. This is source inspection, not a gameplay or detector benchmark. See [source audit](evidence-maple-perception.md), [combat](combat.md), [computer vision](computer-vision.md), and [backlog](improvement-backlog.md).

## Current implementation

The project already has animation-aware template recognition and persistent enemy IDs. Preserve these abstractions before evaluating alternatives.

- [`TemplateDetector`](../../../src/maplebot/perception.py) loads foreground-masked sprite references and variants; map filtering limits active species. `_sprite_signature`, `_sprite_batch`, and `_color_where_possible` reduce candidate work before detailed comparison. `_uncover` handles supported overlap cases; `_suppress` deduplicates candidate boxes.
- [`EnemyTracker.prepare`](../../../src/maplebot/enemy_tracking.py) compensates camera translation, advances position using elapsed time, expands uncertainty, and expires old tracks. `_predict_ground` clamps horizontal prediction to known platform boundaries without pretending to observe a reversal.
- [`EnemyTracker.update`](../../../src/maplebot/enemy_tracking.py) gates associations by species and uncertain ground position, sorts candidate costs, enforces one-to-one assignment, and refuses near-tie crossings instead of guessing identity. Full matches and partial observations have different freshness semantics.
- [`partial_enemies`](../../../src/maplebot/enemy_tracking.py) searches exposed sprite pixels only for an already known track in a registered occlusion region. It bounds variants/search radius, rejects insufficient/spatially narrow evidence, validates foreground colors and score, and rejects ambiguous assignment to another same-species track.
- [`EnemyTrack`](../../../src/maplebot/enemy_tracking.py) exposes visible bounds, ground/predicted position, confidence, uncertainty, observation age and `visible`/`partially_occluded`/`occluded`/`lost` state. Predicted or partial tracks do not become fresh attack evidence.

[`test_enemy_tracking.py`](../../../tests/test_enemy_tracking.py) covers hidden reversals, finite retention, timestamp reset, camera compensation, platform boundaries, multi-enemy ambiguity, and prediction not creating a newly acquired attack target. [`test_perception.py`](../../../tests/test_perception.py) covers masked references on changed backgrounds, partly covered signature pixels, weapon overlap, and stacked sprites. Existing recorded-artwork fixtures are valuable; they do not prove every native overlap/animation case.

## External evidence

### Actual monster detector: MapleStoryAuto

[`YoloMonsterDetector.detect`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2575) crops gameplay, calls Ultralytics prediction, converts box tensors to CPU arrays, filters configured classes, rejects a specific bottom-clipped stump case, and deduplicates detections. Its constructor verifies model files and required classes. This is a working implementation path, not proof of accuracy for our maps or monsters.

[`DetectionTracker.update`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L917) associates same-class boxes using overlap, normalized center distance and box-size gates, then smooths position/confidence. Unmatched tracks advance and decay until missed-frame expiry. It can confirm after repeated hits or a high-confidence observation. It is greedy association, not Hungarian assignment, Kalman filtering or learned re-identification.

[`train_small_yolo.py`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/train_small_yolo.py#L7) records training settings and per-class metrics. These are useful tooling patterns. Training metrics, bundled weights and author comments alone do not establish held-out performance on our native client; no model was downloaded or executed during this audit.

### Bots that do not provide monster recognition evidence

Auto Maple executes commands at routine points; its [routine `Point`](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/components.py#L77) is not monster detection. MS-Visionify's [player controller](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/player_controller.py#L140) combines movement with attacks. msbot's [`characterSpotted`](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L713) identifies other-player minimap dots. Do not cite any of these as a solution for monster boxes, monster identity, hit confirmation, or death recognition.

## Comparison and limitations

| Technique | Expected reliability/accuracy | Cost and complexity | Fit and maturity | Adoption judgment |
| --- | --- | --- | --- | --- |
| Existing masked animation templates | Strong when sprite catalog, resolution and rendered appearance match; brittle to unsupported poses/effects | CPU candidate/template cost grows with active variants; existing optimization and tests | Already integrated and inspectable; native breadth still needs labels | Keep as baseline; measure missed animation coverage |
| Shape/color proposals before template verification | Can reject much background cheaply; color alone confuses props/NPCs | Low-to-moderate CPU; threshold maintenance | Already partly implemented | Tune only using false-positive/negative evidence |
| Existing partial-template track continuation | Useful for known enemies behind mapped foreground occluders | Bounded local matching; depends on registered geometry | Implemented with conservative ambiguity gates | Expand corpus/geometry coverage before adding new search paths |
| YOLO detector plus temporal association | May generalize over poses and partial cover represented in training; unseen species/scenes can fail | Training/annotation/export dependencies; CPU/GPU cost must be measured | External code exists; no verified Classic transfer | Optional offline experiment after dataset and licensing review |
| Global assignment instead of greedy matching | Can improve crowded crossing assignment when cost is informative; identical sprites may remain unidentifiable | More association complexity; usually less expensive than detection for few enemies | Generic trackers provide references; current conservative rejection is deliberate | Compare on crowded clips; do not force an ID under genuine ambiguity |
| Appearance re-identification | Potentially useful for different skins/species; near-identical mobs carry little distinct identity | Feature model and training burden | No useful Maple-specific implementation verified here | Low priority until identity errors affect a measured decision |

Costs and benefits above are estimates, not benchmark numbers. Licensing is a separate decision: current templates require their own asset provenance; MapleStoryAuto's MIT source does not license Ultralytics or its weights. See [source audit](evidence-maple-perception.md).

## Bounding boxes, classification, overlaps, and death

A rendered box, visible-pixel box, sprite origin/feet anchor, and collision or attack hitbox are distinct objects. Preserve them separately. Different animation frames can change visible extents while ground position remains stable. Map-conditioned allowed species reduces false positives but an incomplete spawn source can suppress a real enemy; retain the existing explicit map/catalog error state rather than silently classifying an empty scene as clear.

Our `_suppress` uses a monster IoU threshold of 0.5 and does not require equal species before suppressing. **Inference:** differently sized overlapping enemies can be lost at this stage, before the tracker can help. Existing stacked-monster tests reduce but do not eliminate the risk. Evaluate species-aware or evidence-aware suppression on labeled overlaps; simply lowering all thresholds may create duplicate targets.

Our enemy association refuses near ties and does not claim a unique ID for a merged group. That is appropriate where identical monsters are visually indistinguishable. Global assignment cannot manufacture missing identity evidence. Group occupancy/count uncertainty may be more useful than forced individual IDs for multi-target attacks.

A lost detection can mean occlusion, movement out of view, map change, animation mismatch, or death. No reviewed perception path establishes death from disappearance alone. Keep disappearance separate from combat feedback and target lifecycle; see [combat](combat.md). Likewise, target ranking should use only currently permitted evidence: range/facing/platform plausibility, freshness and threat/skill priorities. A prediction does not create a fresh target. The existing [`Agent._hidden_target` / `_attack_hidden`](../../../src/maplebot/decision.py) nevertheless permits bounded attacks on a previously acquired, briefly hidden target under age, matching track ID, ground-height, range and attempt constraints; it can face but does not pursue it. `_hidden_target` does not directly check the track's confidence or uncertainty interval. Evaluate that omission on labeled cases, especially near range boundaries, without assuming a demonstrated failure. Preserve the distinction: “not fresh evidence” does not mean “never consumed by any combat decision.”

## Verification priorities

1. Label scenes by species, pose, visible fraction, player/NPC/prop negatives, same/different-species overlap, camera regime and map transition. Split by recording/session rather than adjacent frames to avoid train/test leakage.
2. Measure per-species precision/recall and foot-position error; separately measure track switches, fragment retention, recovery time, and stale/predicted evidence accepted by policy. Include negative clips without monsters.
3. Compare current suppression and association with narrowly scoped alternatives; require no increase in false attack permission, not merely prettier overlay continuity.
4. If templates still miss meaningful cases, compare a small detector on the same frozen corpus and hardware, including capture-to-decision age, crowded-scene tail latency, memory and dependency costs. Do not adopt YOLO from a visually convincing demo alone.

These are research-backed opportunities. The ranked backlog selects implementation order; no detector, tracker, configuration, or gameplay behavior was modified by this audit.
