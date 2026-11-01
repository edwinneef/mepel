# Ranked improvement backlog

Research date: 2026-11-01. Recommendations only; no implementation authorized by this report. Read [architecture](architecture.md) for existing systems and [repositories](repositories.md) for pinned source and licenses. Numbers indicate proposed implementation order, not proof of benefit.

Effort estimates are engineering judgement for one engineer familiar with this repository: **S** ≈ 1–2 focused days, **M** ≈ 3–7, **L** ≈ 2–3 weeks, excluding new native evidence collection. These are estimates, not commitments. Performance impacts are qualitative; none was measured in this audit. Confidence concerns the recommendation's rationale, not its eventual success rate. “Quick win” does not mean bypassing existing verification.

## Ranked overview

| Rank | Improvement | Category | Expected impact | Effort | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Independent occlusion/reacquisition benchmark | Quick win / evidence | Detect false identity and circular evaluation before tuning | S–M | High |
| 2 | Minimap-guided player search ROI | Medium | Faster recovery after screen occlusion without claiming fresh position | M | Medium-high |
| 3 | Marker/other-player consistency veto | Medium | Reduce lookalike identity acceptance | M | Medium |
| 4 | Calibrated confidence and ambiguity reporting | Medium | Make thresholds and abstention evidence-based | M | High |
| 5 | Whole-pipeline tail-latency profiling | Quick win | Identify actual expensive stages before optimization | S | High |
| 6 | Recording completeness and write-error reporting | Quick win | Make replay evidence trustworthy under failures | S | High |
| 7 | Two-stage monster association experiment | Medium | Preserve existing identities with weak partial detections | M | Medium |
| 8 | Global assignment for crowded monster tracks | Medium | Reduce greedy association conflicts/ID switches | M | Medium |
| 9 | Timestamp-aware bounded motion model | Experimental | Improve search prediction under variable frame gaps | M | Medium |
| 10 | Partial nametag morphology ablation | Experimental | Recover fragmented tags without broadening identity acceptance | S–M | Medium-low |
| 11 | Prediction-first local template verification | Quick win after profiling | Reduce full ROI sweeps on stable frames | S–M | Medium |
| 12 | Explicit observation-age contracts across consumers | Architectural, incremental | Prevent stale async results masquerading as current evidence | M | High |
| 13 | Combat feedback evidence ladder | Medium | Separate eligible attack, dispatch, visual feedback and attributable hit | M–L | Medium |
| 14 | Matched-map projection/quantization corpus | Medium | Expose systematic world-coordinate errors | M | High |
| 15 | Navigation failure taxonomy and replay coverage | Medium | Distinguish localization, grip, trajectory and timeout failures | M | High |
| 16 | Movement-proof provenance audit/extension | Architectural, incremental | Avoid treating obsolete motion assumptions as current proof | M | Medium-high |
| 17 | Multi-rate perception scheduling experiment | Architectural, incremental | Preserve player freshness in crowded scenes | M–L | Medium |
| 18 | Alternate capture backend A/B evaluation | Experimental | Reduce capture cost only if profiling identifies it | M | Low until #5 |
| 19 | Lightweight learned monster detector experiment | Experimental | Potentially handle unseen animation/appearance variation | L | Low until labelled evidence |
| 20 | Extract small interruptible action primitives | Architectural, conditional | Improve readability if orchestration grows | M | Low unless complexity increases |

## Detailed proposals

### 1. Independent occlusion/reacquisition benchmark

- **Problem and technique:** `tracking_benchmark.load/interpolate` labels from detector anchors and linear interpolation. Extend existing offline tooling with independently annotated identity/visibility intervals and uncertainty-aware scoring; keep synthetic cases separate. Evidence: [local debugging assessment](debugging.md), [Norfair](https://github.com/tryolabs/norfair) and [ByteTrack](https://github.com/FoundationVision/ByteTrack) for explicit track lifecycle/evaluation concepts, not transferable accuracy.
- **Benefit, cost and integration:** high decision value, no gameplay runtime cost, S–M effort; low integration using current recorder/replay. Dependencies: existing recordings, frozen detector/config hashes and annotation conventions. Risk: insufficient independent labels or leaking held-out clips into tuning.
- **Verification:** report evaluable/unknown frames separately, false identity acceptances, missed visible detections, time to fresh same-identity recovery, and abstention. Compare unchanged baseline reproducibly. Confidence high. This is the single selected milestone below.

### 2. Minimap-guided player search ROI

- **Problem and technique:** the search window can remain near a stale screen prediction during occlusion. Use a fresh unique minimap marker plus valid independent camera/view registration to constrain search, inspired by [MapleStoryAuto's minimap zones](player-tracking.md). Preserve full-frame fallback and existing freshness rules.
- **Benefit, cost and integration:** expected recovery/CPU benefit, M effort; small arithmetic plus existing matching, actual cost unknown. Medium integration across `LivePosition` and `TemplateDetector`; depends on #1 and a clearly non-circular transform.
- **Risks/verification:** camera clamp, quantization, marker ambiguity and registration age. Compare ROI recall, recovery delay and p95 processing on the same clips; reject a prior that excludes the true player. A projected box never grants input. Confidence medium-high.

### 3. Marker/other-player consistency veto

- **Problem and technique:** similar players and nametags can be ambiguous. Use minimap agreement and other-player dot zones only to reject inconsistent identity candidates; [MapleStoryAuto](player-tracking.md) supplies a concrete allowed-zone implementation.
- **Benefit, cost and integration:** fewer identity swaps; M effort, low expected arithmetic cost but uncertain additional dot-recognition cost. Medium integration; depends on #1/#2 and identity-aware labels.
- **Risks/verification:** merging dots, party/marker colors, stale maps, overlapping X on different floors. Negative priors must fail open to existing conservative identity rules when unavailable, never manufacture confidence. Measure false vetoes and wrong-player resumes in crowded clips. Confidence medium.

### 4. Calibrated confidence and ambiguity reporting

- **Problem and technique:** template correlation, partial evidence, camera agreement and model confidence are different scores, not probabilities. Preserve their provenance and fit per-evidence threshold curves on development data; compare on held-out data. Sources: [Norfair distance gates, ByteTrack score tiers](computer-vision.md), [current player fusion](player-tracking.md).
- **Benefit, cost and integration:** justified abstention and fewer arbitrary threshold changes; M effort, little expected online overhead. Medium integration; depends on #1 and stable feature logging.
- **Risks/verification:** overfitting, tiny positive-only sets, collapsing different evidence types. Publish precision/recall and abstention by visibility class; prediction remains distinct from observation. Confidence high in evaluation need, unknown improvement magnitude.

Include the concrete `Agent._hidden_target` boundary case: the existing bounded attack uses a point estimate without directly checking the track uncertainty interval/confidence. Compare a conservative interval-aware eligibility rule on offline range-boundary cases before changing policy; no observed failure or benefit is claimed yet.

### 5. Whole-pipeline tail-latency profiling

- **Problem and technique:** configured FPS and old timing anecdotes do not identify today's bottleneck. Aggregate existing stage timings and source age by scene density, including encoding/publication and dropped work. Compare capture-only and replay components separately. Sources: [MSS/DXcam](performance.md) and `Application._run/_process`.
- **Benefit, cost and integration:** avoid expensive backend/model changes with no end-to-end gain; S effort, low integration, optional diagnostic overhead. Depends on reproducible inputs/hardware metadata, not new gameplay.
- **Risks/verification:** warmed caches, background apps and async work excluded from timers. Report p50/p95/max, frame age, skipped jobs and wall-clock runtime; avoid converting a faster isolated stage into a claimed overall speedup. Confidence high.

### 6. Recording completeness and write-error reporting

- **Problem and technique:** `SessionRecorder._write` counts frame-write failures but silently consumes non-frame `OSError`; frame limits do not bound all queue jobs. Add explicit completeness/error counters and a durable manifest concept. [Airtest's recording/reporting path](debugging.md) is an observability reference, not a safety blueprint.
- **Benefit, cost and integration:** reliable diagnostics; S effort, low runtime cost, low–medium integration in recorder/debugger. Depends on preserving file format compatibility and all saved data.
- **Risks/verification:** blocking the capture loop or losing the original error. Fault-inject missing directory, full disk, line-write failure and slow writer; incomplete evidence must be visibly incomplete while Stop/release still works. Confidence high.

### 7. Two-stage monster association experiment

- **Problem and technique:** low-score partial detections may continue an established track but should not create new targets. [ByteTrack's high/low association passes](computer-vision.md) offer a pattern; local `partial_enemies` already covers part of it, so first measure the residual gap.
- **Benefit, cost and integration:** fewer identity breaks; M effort, modest extra association work; medium integration in `EnemyTracker.update`. Depends on #1/#4 and monster-labelled sequences.
- **Risks/verification:** noise refreshing a false track indefinitely. Retain expiry, camera confidence and per-species/platform checks. Measure wrong associations, survival under true occlusion and false-track lifetime; no weak observation becomes new attack authority. Confidence medium.

### 8. Global assignment for crowded monster tracks

- **Problem and technique:** greedy per-detection association may choose locally convenient matches that conflict globally. Compare current behavior against gated bipartite assignment with species, ground position, elapsed time and optional appearance cost. Sources: [SORT, Deep SORT, ByteTrack](computer-vision.md).
- **Benefit, cost and integration:** fewer ID switches in crossings; M effort, cost grows with track count; medium integration and possibly a new dependency (justify separately, none installed now). Depends on #7's fixed detection corpus.
- **Risks/verification:** globally optimal costs can still be semantically wrong for identical overlapping sprites. Require clear gains at actual scene counts; retain unknown/ambiguous outcomes and no-pursuit hidden-target policy. Confidence medium.

First audit detector-side loss: `_suppress` can suppress overlapping different-species boxes before association. Compare species/evidence-aware suppression on the same corpus; assignment cannot recover a candidate that never reaches it. Keep duplicate-template negatives so a more permissive suppression rule does not inflate counts.

### 9. Timestamp-aware bounded motion model

- **Problem and technique:** frame-based prediction may behave differently under dropped/slow frames. Compare current bounded world-step logic against alpha-beta or Kalman state with actual elapsed time, camera compensation and stop-aware velocity decay. Sources: [SORT/Norfair filters](computer-vision.md), [MapleStoryAuto decay](player-tracking.md).
- **Benefit, cost and integration:** better search placement, not full-occlusion truth; M effort, low expected arithmetic cost, medium integration. Depends on #1/#5 and motion-labelled clips.
- **Risks/verification:** knockback, acceleration, floor/rope transitions and uncertain camera. Sweep irregular timestamps and long gaps; prediction error must improve without more false fresh identities. Fit decay from evidence, not another bot's per-frame constant. Confidence medium.

### 10. Partial nametag morphology ablation

- **Problem and technique:** small interruptions can break visual anchors. [MapleStoryAuto's HSV strip morphology](player-tracking.md) supports testing a small closing operation; it does not prove closing white nametag glyphs is beneficial.
- **Benefit, cost and integration:** possible fragment recovery; S–M effort, small ROI cost to measure, low code integration after #1. No new dependency needed.
- **Risks/verification:** merging adjacent names, creating false strokes or matching only a shared prefix. Require held-out lookalike negatives, preserve distributed glyph support and fresh sprite corroboration. Reject the change if false acceptance rises. Confidence medium-low because transfer to our glyph representation is speculative.

### 11. Prediction-first local template verification

- **Problem and technique:** a stable frame may not require the full ROI template sweep. Test last-confirmed template at a small predicted neighbourhood, followed by the unchanged search on failure. [msbot early-exit matching](computer-vision.md) is an efficiency idea; current color/signature batching already optimizes matching.
- **Benefit, cost and integration:** potential CPU reduction; S–M effort, low–medium integration. Depends on #5 demonstrating matching cost and #1 detecting identity regressions.
- **Risks/verification:** first acceptable match hiding a stronger competing identity, stale template or animation change. Preserve ambiguity comparisons where needed; measure end-to-end tail latency and detection equivalence, not just fast-path time. Confidence medium.

### 12. Explicit observation-age contracts across consumers

- **Problem and technique:** asynchronous OCR, preview, camera registration and future detector workers have distinct generations/ages. Preserve current IDs and add narrow typed evidence envelopes only where fields are missing: capture time, source/view generation, observation/prediction kind, uncertainty and expiry. Sources: [DXcam latest-frame buffering, Airtest polling](performance.md).
- **Benefit, cost and integration:** easier stale-result rejection; M effort, low metadata cost, medium integration. Depends on an audit of current contracts so existing safeguards are not duplicated.
- **Risks/verification:** mixing wall clock and monotonic time, breaking replay compatibility, broad refactor. Reject delayed/out-of-order old-generation results in focused offline tests; leave one runtime input owner. Confidence high for explicit evidence, not for a wholesale architecture change.

### 13. Combat feedback evidence ladder

- **Problem and technique:** range eligibility and input tickets cannot establish hits. Keep separate states for requested, dispatched, animation/projectile observed, damage candidate and causally attributable outcome. External [MapleController/Classic bot attack paths](combat.md) mostly demonstrate dispatch, underscoring the missing evidence rather than supplying a ready solution.
- **Benefit, cost and integration:** more useful combat diagnostics and less false success; M–L effort, potentially significant ROI/OCR work; medium–high integration, observation-only first. Depends on target tracks, timestamps and isolated annotated combat clips.
- **Risks/verification:** other players' damage, multi-target effects, despawn and projectile delay. Include explicit unknown outcomes and negative controls; never equate disappearing detections with kills. Confidence medium; final causal attribution may remain unavailable screenshot-only.

### 14. Matched-map projection/quantization corpus

- **Problem and technique:** minimap scale/origin and native/source alignment have systematic uncertainty. Preserve [existing position research](../../position-evidence-research.md); compare quantized intervals against independent geometry labels and matching source builds. [Auto Maple/MS-Visionify minimap methods](navigation.md) illustrate why marker precision alone is insufficient.
- **Benefit, cost and integration:** fewer false surface assignments; M effort, offline cost only initially, medium integration. Depends on compatible public assets and non-circular landmarks; do not consume held-out maps during tuning.
- **Risks/verification:** mismatched clients, image-corner versus map-origin coordinates, nonunique portals. Validate at least three independent non-collinear anchors where available and report uncertainty coverage; incompatible maps remain excluded. Confidence high.

### 15. Navigation failure taxonomy and replay coverage

- **Problem and technique:** “timeout” can combine wrong localization, missed grip, infeasible trajectory or delayed input. Retain bounded phases and attach structured phase/progress evidence to failures. Sources: [Auto Maple class commands and MapleStoryAutoLevelUp route logic](navigation.md), compared with current `Navigator` and harness.
- **Benefit, cost and integration:** smaller repair/retest scope; M effort, low logging overhead, medium integration. Depends on existing clips and physics evidence.
- **Risks/verification:** inferred contact mislabelled as verified grip, synthetic success presented as native proof. Replay separate camera-loss, rope-miss, stale-feedback and edge-deadline scenarios; no increased retries or changed gate thresholds. Confidence high.

### 16. Movement-proof provenance audit/extension

- **Problem and technique:** `MoveProofs` persists map hash/move ID/time; verify whether movement-code or control/physics changes can leave old proof applicable. Add an explicit provenance version only if that gap is confirmed end-to-end. Sources: local [architecture](architecture.md) and map/class-specific external movement assumptions in [navigation](navigation.md).
- **Benefit, cost and integration:** honest reuse of evidence; M effort, trivial expected hash/storage cost but medium–high compatibility work. Depends on a precise invalidation policy and safe migration preserving old records.
- **Risks/verification:** gratuitously invalidating working evidence or letting old proof grant new capabilities. Test unchanged reuse, map change, movement-model change and legacy records; archive rather than delete historical proof. Confidence medium-high.

### 17. Multi-rate perception scheduling experiment

- **Problem and technique:** crowded-scene matching may delay player freshness. Runtime already skips monster work during navigation; extend only if #5 identifies a gap. Sources: [MapleStoryAuto async detection](monster-detection.md), [DXcam buffering](performance.md).
- **Benefit, cost and integration:** potentially steadier localization; M–L effort, uncertain CPU benefit and extra synchronization cost; medium–high integration. Depends on #12, age limits, profiling and deterministic replay.
- **Risks/verification:** stale combat targets, queue growth and nondeterministic state. Use bounded latest-work semantics and compare frame age/target freshness under overload. Never reuse stale targets merely to maintain display FPS. Confidence medium.

### 18. Alternate capture backend A/B evaluation

- **Problem and technique:** if MSS capture dominates measured latency, compare [DXcam](https://github.com/ra1nty/DXcam) or Windows Graphics Capture patterns in [performance](performance.md) behind the existing capture interface.
- **Benefit, cost and integration:** conditional capture reduction; M effort, backend/device-dependent CPU/GPU/memory cost, medium Windows-specific integration. Depends on #5; no dependency installation in this audit.
- **Risks/verification:** window bounds, DPI, moved windows, stale frame duplication and color order. Preserve `Capture.window` pre/post validations and ownership; compare frame correctness and end-to-end age on identical conditions. Confidence low until bottleneck evidence exists.

### 19. Lightweight learned monster detector experiment

- **Problem and technique:** evaluate a small detector only if animation/partial-occlusion failures remain after simpler methods. Sources: [MapleStoryAuto and TinForge](monster-detection.md); use existing [Detector protocol](../../../src/maplebot/perception.py).
- **Benefit, cost and integration:** possible appearance generalization; L effort, potentially high CPU/inference cost and optional GPU operational burden, high data/model maintenance. Depends on labelled positive/negative maps, license review of weights/assets and an inference budget.
- **Risks/verification:** Artale-to-Classic domain mismatch, sprite/NPC confusion, dataset leakage and distribution obligations. Compare precision/recall by species and occlusion, tail latency and memory against templates on held-out scenes. CPU feasibility must be measured. Confidence low pending evidence.

### 20. Extract small interruptible action primitives

- **Problem and technique:** if runtime orchestration becomes harder to reason about, extract a few cancel-aware action objects; [py_trees stop/terminate lifecycle](input-and-automation.md) is a reference. Do not install a behavior-tree framework merely to replace the current bounded state machine.
- **Benefit, cost and integration:** conditional maintainability; M effort, minimal expected computational change, medium–high lifecycle risk. Depends on a concrete complexity problem and existing scheduler outcomes.
- **Risks/verification:** a second input owner, canceled actions dispatching late, failures swallowed by generic statuses. Preserve release/stop/expiry tests and demonstrate clearer ownership before adopting. Confidence low absent growth pressure.

## One next implementation milestone

**Build an independent offline occlusion and reacquisition benchmark using the existing saved clips and replay tools.** No detector or gameplay-policy change belongs in this milestone.

Deliver a frozen manifest with frame/config/source hashes; label player identity and visible-body/nametag support independently of detector output; separate real sequences from synthetic occluder fixtures; identify development versus held-out material before tuning. Include clean control, partial body, partial nametag, full occlusion, lookalike/crowd, camera scrolling and irregular-frame-gap cases where existing footage supports them. Missing cases are reported as coverage gaps, not invented labels or a request for immediate new recording.

Acceptance: unchanged baseline runs without capture/input authority; repeated results agree except measured timing; ambiguous/full-hidden frames are unknown or interval-labelled; false fresh identity and reacquisition delay are scored on evaluable frames; per-case and aggregate coverage are reported; timing separates replay compute from setup/annotation/report overhead. Existing release and fresh-identity requirements remain untouched. The output establishes which of #2–#4 is actually worth implementing next; it does not claim native gameplay acceptance.
