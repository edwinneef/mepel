# Combat geometry, targeting and outcome evidence

Research date: 2026-11-01. Actual source inspected; no game actions or external code execution. Repository metadata and licensing are recorded in [navigation/combat source evidence](evidence-maple-navigation.md). Recognition and association details belong in [monster detection](monster-detection.md).

## Current behavior and demonstrated limits

[decision.py](../../../src/maplebot/decision.py) already implements SEARCH, APPROACH, ATTACK and VERIFY. `Agent.step_input` filters confident, same-height fresh detections, acquires the nearest target, matches species-compatible candidates with camera compensation, rejects close association ties, retargets to a nearer enemy, waits for an approaching monster, applies facing input and schedules an observation interval after attacking. Skill/basic selection uses MP hysteresis. Failed approach progress and repeated attacks are bounded. This is a substantial combat state machine, not a missing architecture.

An important current-source distinction: `_hidden_target` and `_attack_hidden` already allow a **recently seen tracked target within the configured range** to be attacked in place during brief occlusion. They require the prior `track_id`, same-height proximity and a bounded recent-sighting interval. They can issue facing input but do not chase the hidden target. Do not repeat the older blanket statement that every attack always requires a fresh visible monster. This path needs dedicated false-association/expiry evidence; it should not be expanded merely because another tracker coasts longer.

[attack_ranges.py](../../../src/maplebot/attack_ranges.py) contains conservative Classic weapon operating bands. Their comments explicitly distinguish center-distance bands from published animation reach and unknown internal enemy hitboxes. The comparison in [combat_readiness.py](../../../src/maplebot/combat_readiness.py) exposes distances without claiming hits. [CombatEvidence.snapshot](../../../src/maplebot/combat_evidence.py) returns `hit_confirmed: None`; it records intent/input outcomes and associated observation context. [hit_check.py](../../../src/maplebot/hit_check.py) captures frame-paired, operator-labelled evidence without sending attacks.

The preserved [single-platform evidence](../../single-platform-combat.md) records an accepted approach/Ctrl hit and a later sequence with frequent target loss. Its pixel replay repaired a specific proposal-pruning failure, but cannot establish the changed policy's live movement or attack success. Basic fallback, repeated-loop behavior and some recovery acceptance remain explicitly pending in that historical note. This research did not reassess native acceptance or replay those clips.

## What external implementations actually do

| Implementation | Verified decision rule | Useful property | Limitation / adaptation decision |
| --- | --- | --- | --- |
| [LinPolly `update_cmd_by_mob_detection`](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L1480) | Searches attack-sized ROI; directional target selection or AOE; elapsed cooldown check | Explicit directional/AOE configuration | Search rectangle is not native hitbox; no hit confirmation in this path; retain ours |
| [MapleController `attack/use_uncooldowned_skills`](https://github.com/tomerh2001/MapleController/blob/e0dbdca616cd56fcf242bcd1f6390b77de1f45e5/Controller/Controllers/PlayerController.py#L60) | Repeated configured key taps, sleeps and cooldown bookkeeping | Separate skill configuration | No per-target observed hit result; does not justify faster repetitions |
| [TinForge `BotThread.calculate`](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/process/bot.py#L35) | Distance/height bands choose move, attack or jump attack | Concrete detector-to-control integration | Too-close branch follows broader `< max_range`, making minimum-range retreat unreachable under usual ranges; do not copy |
| [sychen `_in_attack_box`, `_attack_stalled`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/brain/fsm.py) | Box overlap margin, timed immobility heuristic and typed intent | Pure decision boundary and bounded stalls | Stationary killing and persistent false target can look alike; immobility is not miss confirmation |
| [sychen `find_hp_bars`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/vision/mob_hpbar.py#L36) | Color/shape components produce monster proposals below HP bars | Independent auxiliary evidence cue | Does not read damage, track health fraction or prove our attack caused a change |

These implementations demonstrate source-level mechanisms, not measured compatibility with our Classic client. Most external combat loops are weaker than our existing separation of requested input and observed effect.

## Attack geometry: what can be predicted

Relative positions, facing, conservative range, platform membership and movement state can predict **attack plausibility**. They cannot establish that the server accepted the action or that damage occurred. Animation-specific reach, sprite anchor offsets, minimum range, airborne restrictions, cooldown readiness, obstructions and an enemy moving during input latency all matter.

For melee, retain per-weapon conservative bands and include anchor/box uncertainty. Animation-independent detector boxes can change center or feet even while the monster's world origin is constant. A large visual effect must not enlarge the inferred vulnerable body. For ranged attacks, distinguish firing eligibility, projectile launch and eventual impact; a visible projectile does not prove target damage. No inspected screenshot-only implementation supplied a validated Classic projectile-flight/hitbox model.

Suggested experiment, not implementation: annotate attack attempt time, player/target anchors, facing, movement, weapon/skill, closest geometric separation and independent visible result. Evaluate a conservative interval of plausible contact rather than a hard exact hitbox inferred from a template. Keep range tuning separate from the detector threshold so poor detection is not hidden by widening range.

Native sprite artwork/animation extents and server or replacement-client rules are not interchangeable evidence. The existing [bowman research](../../bowman-range-research.md) and [warrior ranges](../../warrior-ranges.md) remain the project-specific starting points; this audit does not replace their accepted observations.

## Target persistence, occlusion and death

Our enemy tracker and combat target association are separate layers. Current combat fresh-candidate reassociation uses species/proximity while hidden attack uses `track_id`; review identity consistency on crossings, overlapping same-species monsters and camera changes before extending persistence. A full-screen tracker may maintain an identity while observation confidence drops; that is useful for reacquisition, not a guarantee that the same vulnerable target remains in range.

[TinForge `DetectionThread.process`](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/process/detection.py#L32) can assign multiple detections to the same nearest tracker in one frame. Its [Tracker extrapolation](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/data/trackers.py#L67) is effectively inactive for its bounded history. These are warnings against equating a method name with implemented motion prediction.

Our VERIFY state explicitly reports that disappearance after an attack leaves the kill unconfirmed. Preserve this: disappearance can mean occlusion, leaving the crop, wrong animation, camera scrolling or detection failure. A single missing monster, dropped item or floating number is insufficient causal evidence in a crowded scene.

Potential multi-cue confirmation combines a target-associated HP decrease, damage glyphs near the same track, death animation and subsequent absence after a bounded observation interval. Each cue needs its own calibration and provenance. Other players, damage-over-time and overlapping monsters can cause the same visual changes. The appropriate initial result vocabulary is observed support / contradiction / unknown, not a fabricated Boolean hit for every dispatch.

## Timing, skills and multi-target attacks

External cooldowns usually mean time since a requested keypress. Our scheduler outcome and control history offer stronger timing provenance, but still cannot prove in-game cooldown readiness. If later adding skill selection, keep readiness as explicitly observed, configured, inferred or unknown; avoid treating a completed ticket as accepted skill activation.

Facing currently derives from issued movement and action outcomes. A facing-animation detector could corroborate it, but attacks/effects/occlusion may hide the sprite. Evaluate against accepted controls before adding another hard gate. Short movement pulses also have position side effects, so measure their impact near edges and crowded targets.

For multi-target/AOE selection, scoring the number of overlapping detector boxes is cheap but vulnerable to duplicates and species/body-box errors. Associate/merge detections first, preserve range/terrain constraints, and prefer a stable safe target over maximizing uncertain count. None of the inspected bots establishes an authoritative multi-target hit-count estimator for our client. Projectile interception and animation recognition should remain experiments until labelled evidence shows a concrete benefit.

## Ranked local opportunities

1. **Occlusion and reacquisition evaluation:** extend the existing replay corpus with same-species crossings, bridge occlusion, effects, crop exits and full disappearance. Track identity switches, false hidden attacks and time to fresh reacquisition. This supports the central milestone in [README](README.md).
2. **Attack evidence taxonomy:** annotate existing saved attempts as dispatched, animation observed, damage support, disappearance or unknown, retaining frame/time/track references. Reuse `CombatEvidence` and `hit_check`; no input change required.
3. **Association consistency:** after the corpus exposes failures, compare combat matching against tracker identities and one-to-one association. Preserve rejection under ambiguity and the short hidden-target expiry.
4. **Auxiliary HP-bar proposals:** only if screenshots actually expose stable monster health bars. Evaluate species/track association and false positives offline. This is an independent cue, not proof of damage.
5. **Animation-aware range study:** use held-out manual outcomes to test whether sprite-anchor intervals improve predictions over existing conservative center bands. Do not tune ranges from unlabelled misses.

The central [backlog](improvement-backlog.md) owns cross-subsystem priorities, effort and the single next milestone. These are research opportunities rather than authorization to implement.

## Verification criteria

Separate the three questions: did the policy choose a reasonable attack, did the scheduler deliver its input request, and did the game visibly produce the intended effect? Offline decision replay answers only the first. Fake-input tests cover scheduler contracts. Existing recordings can provide observed effects where readable and independently labelled; new native testing is outside this task.

Include close/far boundary cases, opposite facing, target crossing sides between decision and dispatch, approaching targets, minimum-range violations, MP hysteresis, low frame rate, camera shift, same-species overlap and track expiry. Report results per failure category with unknown labels retained. For any future confirmation detector, measure false confirmed hits/kills separately from recall; a confident false success is especially harmful to recovery decisions.

Read [input and automation](input-and-automation.md) for interruption contracts, [performance](performance.md) for latency measurement and [open questions](open-questions.md) for unresolved native evidence.
