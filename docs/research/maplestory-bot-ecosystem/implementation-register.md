# Research implementation register

Source baseline: 630d7ad0c3ab30f0fb7042710f8817792c45ec46. Created 2026-11-01. [Research index](README.md). Machine-readable authoritative rows, source hashes, original phase criteria and combat history: [implementation-register.json](implementation-register.json).

## Ownership and evidence

All 16 original reports and the dirty AGENTS.md/CLAUDE.md pointers are preserved byte-for-byte and excluded from new commits. No research source is rewritten to make a recommendation appear implemented. New code uses focused offline checks; all live work needs a separate explicit authorization. Each entry retains source, code seam, dependency, acceptance, risks, evidence and deferral fields in JSON. A deferral is not an implementation success.

## Coverage

| ID | Finding | Phase | Disposition | Source |
| --- | --- | --- | --- | --- |
| B01 | Independent occlusion/reacquisition benchmark | p2 | implemented_offline | [source](improvement-backlog.md#1-independent-occlusionreacquisition-benchmark) |
| B02 | Minimap-guided player search ROI | p5 | planned | [source](improvement-backlog.md#2-minimap-guided-player-search-roi) |
| B03 | Marker/other-player consistency veto | p5 | planned | [source](improvement-backlog.md#3-markerother-player-consistency-veto) |
| B04 | Calibrated confidence and ambiguity reporting | p5 | planned | [source](improvement-backlog.md#4-calibrated-confidence-and-ambiguity-reporting) |
| B05 | Whole-pipeline tail-latency profiling | p3 | partial | [source](improvement-backlog.md#5-whole-pipeline-tail-latency-profiling) |
| B06 | Recording completeness and write-error reporting | p3 | implemented_offline | [source](improvement-backlog.md#6-recording-completeness-and-write-error-reporting) |
| B07 | Two-stage monster association experiment | p6 | experimented_not_promoted | [source](improvement-backlog.md#7-two-stage-monster-association-experiment) |
| B08 | Global assignment for crowded monster tracks | p6 | experimented_not_promoted | [source](improvement-backlog.md#8-global-assignment-for-crowded-monster-tracks) |
| B09 | Timestamp-aware bounded motion model | p5 | planned | [source](improvement-backlog.md#9-timestamp-aware-bounded-motion-model) |
| B10 | Partial nametag morphology ablation | p5 | planned | [source](improvement-backlog.md#10-partial-nametag-morphology-ablation) |
| B11 | Prediction-first local template verification | p5 | planned | [source](improvement-backlog.md#11-prediction-first-local-template-verification) |
| B12 | Explicit observation-age contracts across consumers | p3 | partial | [source](improvement-backlog.md#12-explicit-observation-age-contracts-across-consumers) |
| B13 | Combat feedback evidence ladder | p6 | planned | [source](improvement-backlog.md#13-combat-feedback-evidence-ladder) |
| B14 | Matched-map projection/quantization corpus | p4 | partial | [source](improvement-backlog.md#14-matched-map-projectionquantization-corpus) |
| B15 | Navigation failure taxonomy and replay coverage | p7 | planned | [source](improvement-backlog.md#15-navigation-failure-taxonomy-and-replay-coverage) |
| B16 | Movement-proof provenance audit/extension | p4 | audited_deferred_migration | [source](improvement-backlog.md#16-movement-proof-provenance-auditextension) |
| B17 | Multi-rate perception scheduling experiment | p8 | planned | [source](improvement-backlog.md#17-multi-rate-perception-scheduling-experiment) |
| B18 | Alternate capture backend A/B evaluation | p8 | planned | [source](improvement-backlog.md#18-alternate-capture-backend-ab-evaluation) |
| B19 | Lightweight learned monster detector experiment | p8 | planned | [source](improvement-backlog.md#19-lightweight-learned-monster-detector-experiment) |
| B20 | Extract small interruptible action primitives | p8 | planned | [source](improvement-backlog.md#20-extract-small-interruptible-action-primitives) |
| X01 | Species/evidence-aware overlap suppression | p6 | planned | [source](monster-detection.md#bounding-boxes-classification-overlaps-and-death) |
| X02 | Hidden-target uncertainty and combat/track identity | p6 | planned | [source](monster-detection.md#bounding-boxes-classification-overlaps-and-death) |
| X03 | HP bars, facing, animation/range, projectiles and AOE | p6 | planned | [source](combat.md#ranked-local-opportunities) |
| X04 | Body fragments, masked points and appearance reidentification | p5 | planned | [source](player-tracking.md#recommended-incremental-work) |
| X05 | Marker shapes, minimap motion, reset and stitching | p4 | planned | [source](navigation.md#minimap-versus-full-screen-localization) |
| X06 | Route teaching/compression, physics, landing and boundaries | p7 | planned | [source](navigation.md#physics-boundaries-and-geometry) |
| X07 | Paired visual evidence reports and uncertainty overlays | p2 | implemented_offline | [source](debugging.md#external-reporting-pattern) |
| X08 | Cancellation contracts, ticket timeline and recovery reasons | p3 | partial | [source](input-and-automation.md#practical-improvements-and-verification) |
| X09 | Template caches, buffer ownership, worker counts and cadence | p8 | planned | [source](performance.md#optimization-comparison) |
| X10 | Scale/features/differencing/background/OCR alternatives | p8 | planned | [source](computer-vision.md#recognition-choices) |
| X11 | Code, model, data and dependency provenance | p8 | planned | [source](repositories.md#licensing-and-maturity-interpretation) |
| X12 | Reconcile stale claims and research unknowns | p8 | planned | [source](open-questions.md#preserved-research-requiring-caution) |
| L01 | Preserved club combat native acceptance | p9 | blocked | [source](combat.md#current-behavior-and-demonstrated-limits) |

## Phase acceptance

### p1

Preserve research; create R/implementation-register.md. Depends on: none.

- Inventory/hash 16 reports; preserve existing research/dirty instructions. Create implementation-register.md with B01-B20,X01-X12,L01; append extra IDs, never renumber.
- Rows: source section/permalink, code seam, phase/dependencies, disposition, acceptance, evidence, risks, deferral reason/revisit trigger. Map every actionable passage; alias duplicates; retain rejected/already-covered findings. Validate zero orphan IDs/links. Preserve combat decisions/evidence as L01.

### p2

B01/X07 independent occlusion baseline. Depends on: p1.

- Sources debugging.md; X07=paired reports/uncertainty overlays.
- Extend replay/benchmark: freeze hashes/session splits, independent identity/visibility labels, hidden=unknown/interval, separate real/synthetic, explicit gaps. Deterministic unchanged baseline; false identity/resume, recall, recovery, abstention, timing; no capture/input/tuning.

### p3

B05/B06/B12/X08 evidence and timing. Depends on: p2.

- X08=input-and-automation.md: cancellation/tickets/recovery reasons; performance.md for profiling.
- Recorder fault injection exposes errors/backlog. Reject stale/out-of-order generations; Stop/release retained. Stage tails/frame age measured with offline/native timing distinguished.

### p4

B14/B16/X05 localization/proofs. Depends on: p2, p3.

- X05=navigation.md: marker shapes, terrain-motion challenger, resets/stitching.
- Independent matched-build anchors/quantization; no circular labels. Audit code/control/physics proof provenance; migrate only if needed, preserve records. Incompatible maps/unknowns explicit; open-questions.md.

### p5

B02-B04/B09-B11/X04 player recovery. Depends on: p3, p4.

- X04=player-tracking.md: fragments/masked body points; re-ID alternatives in computer-vision.md.
- Paired ROI/veto/confidence/elapsed-time/morphology/local-check ablations. Ambiguous/stale cues retain fallback; no false fresh identity/resume. Promote measured gains only; otherwise reason+revisit trigger.

### p6

B07/B08/B13/X01-X03 monster/combat evidence. Depends on: p3, p5.

- X01=monster-detection.md: suppression. X02=same plus combat.md: hidden uncertainty/identity consistency.
- X03=combat.md HPbar/facing/range/animation/projectile/AOE cues. Fixed-detection crossings/range negatives; no weak new target/hidden pursuit. Dispatch/disappearance != hit/kill. Retain unknown; log changes to L01 choices for p9.

### p7

B15/X06 navigation replay. Depends on: p4, p5.

- X06=navigation.md: route compression/teaching,physics/landing,boundaries.
- Action-aligned held-out replay distinguishes localization/grip/trajectory/input failures; no false arrival/extra retries. Proposed/simulated/proven separate; unidentified physics explicit.

### p8

B17-B20/X09-X12 conditional experiments. Depends on: p3, p5, p6, p7.

- X09=performance.md caches/buffers/workers; X10=computer-vision.md scale/features/differencing/OCR; X11=repositories.md+3 evidence audits licenses/deps/assets; X12=open-questions.md stale claims.
- Scheduling/capture/ML only for measured residual gap; action primitives only for demonstrated complexity. Check code/model/data rights/dependencies before reuse; no untrusted execution. Each ID gets adopt/defer/reject evidence+trigger; adopted changes pass paired quality/tail-latency checks.

### p9

L01 preserved combat/native acceptance. Depends on: p1.

- L01: go_minute.py rope5 descent +60s potion rotation; inspect current script/setup/prior failure; affected offline checks and safe install first.
- Record HPmin,waits/attacks,stops,result/clip paths for preserved less-damage outcome. Old engine/map state unverified. Research changes need separate native acceptance when applicable.
- Required operator input: Fresh explicit authorization for each bounded batch, operator present; plan/next is not approval.

### p10

Coverage/handoff audit. Depends on: p8.

- Reconcile all16 reports: every B/X/L has source/disposition/dependencies/evidence/remaining acceptance. Update index/continuity; implemented/offline/live/deferred distinct. p9 pending keeps goal active.

## Evidence log

- p1: Created 33 stable entries (20 backlog, 12 supplementary groups, one unfinished combat outcome); all 16 reports mapped. Original report/instruction hashes recorded; acceptance source text retained. No app changes or live runs.

- p2/p3/p4/p6 offline evidence and remaining limits: [implementation-evidence.md](implementation-evidence.md). P3 contracts and later ready phases continue; no live authorization.
