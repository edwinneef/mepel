# Architecture assessment

Research date: 2026-11-01. Local source baseline: `630d7ad0c3ab30f0fb7042710f8817792c45ec46`. Research only; no application changes or live checks. This baseline was assessed before evaluating external alternatives. Existing untracked `docs/oss-bot-research.md` was read and preserved.

## Actual stack and boundaries

The engine is **Python**, not Node: [pyproject.toml](../../../pyproject.toml) declares Python 3.12+, MSS, NumPy, OpenCV headless and Windows OCR bindings. [ui/package.json](../../../ui/package.json) describes the React/TypeScript/Vite workbench and Electron shell. Recommendations must fit the Python engine and its existing UI contract, rather than introduce a second decision engine in TypeScript.

The current flow is window-bound capture → perception/localization → pure policy/navigation decisions → runtime arbitration → guarded scheduler/keyboard. Preview, recording, display tracking and asynchronous registration are supporting consumers. [runtime.py](../../../src/maplebot/runtime.py) owns `Application._process`, `_arbitrate`, `safe_stop` and command dispatch; [contracts.py](../../../src/maplebot/contracts.py) defines versioned debugger commands. A successful input ticket is not a successful game action.

## Implemented subsystem inventory

| Subsystem | Inspected implementation | Assessment before external comparison |
| --- | --- | --- |
| Capture | [capture.py](../../../src/maplebot/capture.py), `Capture.grab/window`, `Calibration.valid_for/load` | MSS BGR copy; validates visible desktop, title, client bounds, DPI and movement during capture. Session verification resets on load. Preserve these checks if evaluating another backend. |
| Player | [perception.py](../../../src/maplebot/perception.py), `TemplateDetector`, `_follow`, `_partial_nametag`, `_fuse_nametag`; [reacquisition.py](../../../src/maplebot/reacquisition.py), `ConfirmedSprites`, `Reacquisition.step` | Masked sprites, nametag fragments, ROI/full-frame fallback and bounded identity persistence already exist. Recovery releases input and requires fresh agreeing identity. Full occlusion is uncertainty, not fresh evidence. |
| Enemies | [enemy_tracking.py](../../../src/maplebot/enemy_tracking.py), `EnemyTracker.prepare/update`, `partial_enemies` | Persistent species-aware IDs, camera translation, motion prediction, partial evidence and expiry already exist. Investigate association ambiguity rather than propose a tracker from scratch. |
| Camera | [camera_motion.py](../../../src/maplebot/camera_motion.py), `feature_translation`; `CameraTracker.update` in perception | Forward/backward pyramidal Lucas–Kanade, fixed-HUD masks, spatially distributed consensus and phase-correlation hint. A stationary UI or one moving entity must not become world motion. |
| Localization | [localization.py](../../../src/maplebot/localization.py), `ViewTransform`, `MinimapTransform`, `MinimapTracker`; [live_position.py](../../../src/maplebot/live_position.py), `LivePosition.update`; [map_alignment.py](../../../src/maplebot/map_alignment.py), `PositionInterval` | Minimap/screen fusion, public map registration, confidence/staleness checks and interval positioning already exist. View registration uses a single background worker. |
| Map selection | [map_filter.py](../../../src/maplebot/map_filter.py), `MapFilter.match/select` | OCR/title filtering handles Roman numeral confusions, ambiguous map-name unions and missing sprite coverage. Public source geometry must remain versioned and independently aligned. |
| Navigation | [navigation.py](../../../src/maplebot/navigation.py), `RouteMap`; [moves.py](../../../src/maplebot/moves.py); [navigation_executor.py](../../../src/maplebot/navigation_executor.py); [move_proofs.py](../../../src/maplebot/move_proofs.py), `MoveProofs` | Geometry, route planning, bounded execution and saved proof ownership already exist. Computed reachability and recorded successful traversal are distinct. |
| Combat | [decision.py](../../../src/maplebot/decision.py), `Agent.step_input`; [attack_ranges.py](../../../src/maplebot/attack_ranges.py); [hit_check.py](../../../src/maplebot/hit_check.py); [combat_evidence.py](../../../src/maplebot/combat_evidence.py), `CombatEvidence.snapshot` | Range/timing/target policy and evidence are implemented. `hit_confirmed` is deliberately null in run evidence; neither key dispatch nor target disappearance proves damage. |
| Input and recovery | [keyboard.py](../../../src/maplebot/keyboard.py); [scheduler.py](../../../src/maplebot/scheduler.py); runtime `safe_stop`, `_input_block_reason`, `_reacquire` | Keep one input authority, bounded actions, release, stop, freshness and session gates. Research does not authorize restarting or gameplay. |
| Debugging | [recorder.py](../../../src/maplebot/recorder.py), [replay.py](../../../src/maplebot/replay.py), [tools](../../../tools), [tests](../../../tests) | Clips, replay, deterministic policy checks, offline navigation harness and diagnostic overlays already exist. Their evidence levels must remain explicit. |

## Strengths and limits of the evidence

Source and tests establish intentional behavior and regression coverage; they do not establish a live success rate. [Single-platform combat](../../single-platform-combat.md) records offline diagnosis and pending native acceptance. [Bounded navigation](../../bounded-navigation.md) distinguishes simulated anchor routes from collision, grip and arrival evidence. These are historical records, not a fresh report of today's running engine.

The most consequential known gaps are independently labelled positioning/occlusion evidence, ambiguity under similar appearances and crowded targets, and causal combat confirmation. [Position evidence research](../../position-evidence-research.md) explicitly identifies native projection/asset-origin uncertainty, minimap quantization and circular-label risks. Do not replace working localization with an unvalidated reference-client formula.

## Comparison and integration conclusions

External source audits covered [Maple perception](evidence-maple-perception.md), [navigation/combat](evidence-maple-navigation.md) and [general systems](evidence-general-systems.md). Their source-level lessons support incremental changes, not a new bot architecture.

| Alternative | Compared with our implementation | Decision and integration seam |
| --- | --- | --- |
| Auto Maple / MS-Visionify minimap-only global position | Simpler state; misses may retain stale coordinates. We already fuse marker, camera and player evidence. | Preserve `MinimapTracker`; use independent marker information as a search prior, never downgrade freshness requirements. |
| MapleStoryAuto full-screen/YOLO pipeline | Useful minimap candidate zones and full-screen cue fusion; large scripts, character-specific color cues and cached model output. | Experiment through `Detector` and search helpers after held-out evaluation. Preserve our bounded named-identity recovery. |
| Norfair point tracking | Separate point visibility and optimized filters are useful; its greedy assignment is not a global solver. Inspected dependency constraints conflict with our NumPy 2 range. | Borrow measurement-model ideas through a small local adapter if justified. Existing camera flow has stricter bidirectional/spatial checks. |
| SORT / ByteTrack / Deep SORT | Global assignment, staged confidence association and appearance history address different problems; no platform/contact semantics. | Compare association using fixed detections inside `EnemyTracker`, retaining terrain limits and unknown identities. Deep appearance embeddings remain experimental. |
| easymaple / Artale route scripts | Teach routes and attach class commands; some paths imply success from timing or permit stale location/random fallback. | Improve teaching/failure visualization around current `RouteMap`/`Navigator`; preserve bounded acknowledgement and proof ownership. |
| DXcam latest-frame buffering | Makes timestamp/buffer ownership explicit; changing capture does not accelerate expensive recognition automatically. | Profile existing stage timings first; any future adapter retains `Capture.window` validations and stale-frame rejection. |
| py_trees behavior lifecycle | Priority switching and termination are explicit, but leaf invalidation alone does not release physical input. | Retain runtime arbiter/scheduler/keyboard. Small cancel-aware action objects only when a concrete complexity problem emerges. |
| Airtest reporting | Binds screenshots, assertions and errors into understandable evidence; dependency constraints conflict with our environment. | Reuse reporting concepts in existing recorder/replay, not the framework's action loop. |

## Concrete weaknesses and their confidence

1. **Evaluation independence — verified limitation.** `tools/tracking_benchmark.py:load/interpolate` obtains anchors from detector results and interpolates hidden positions. This cannot independently establish native occlusion accuracy. It remains useful for synthetic/regression comparisons.
2. **Cadence-sensitive player prior — verified mechanism, impact unmeasured.** `TemplateDetector._learn_motion/_predict` use per-frame displacement; enemy prediction uses elapsed time. Variable capture gaps are a focused comparison case, not proof that Kalman is needed.
3. **Crowded target evidence — verified mechanisms, failures not measured.** `_suppress` is class-agnostic at monster IoU 0.5. `Agent._hidden_target` checks age, ID, height and point range, but not the track uncertainty interval/confidence. Existing hidden-target attacks are deliberately bounded and do not pursue. Evaluate boundary cases before changing policy.
4. **Diagnostic integrity — verified failure path.** `SessionRecorder._write` consumes non-frame write errors without the frame-drop counter recording them. A successful replay must distinguish complete evidence from missing frames or decision logs.
5. **World-position uncertainty — documented and source-visible.** `align` retains empirical marker-bias uncertainty; `PositionInterval` does not average systematic bias away. `FirstVisitLocator` explicitly starts with `precision_verified=False`. Native exact-coordinate claims are not justified.
6. **Saved movement-proof provenance — open risk.** `MoveProofs` stores map hash, move ID and time. Audit whether executor/physics/control changes need their own provenance before designing migration; map/profile invalidation already exists.

## Cost and maintainability

`Application._run` performs capture followed by `_process` on one worker; `_process` reads the map, performs perception, updates position and decides actions. It deliberately omits monster search during navigation/movement probes. Encoding is published asynchronously with copies. Existing `stage_timing` includes capture interval/cost and processing components. Possible costs include candidate-template work, camera-flow consensus, array copies and recording/preview publication, but **this audit did not measure their ranking**.

The runtime's large coordination surface is a maintenance risk, not sufficient reason to rewrite it. Keep pure policy input/snapshot replay, versioned commands, source/view generation, map fingerprints and exclusive input ownership. If changes require new interfaces, use a narrow timestamped evidence record and leave the runtime as the sole authority that promotes observations into permitted actions. Do not let display tracking, a model worker or a behavior tree dispatch keys independently.

## Recommended architecture decision

No architectural replacement is justified. Preserve perception → evidence → policy → guarded execution, the current React workbench, recorder/replay, stop semantics and saved profiles. The [backlog](improvement-backlog.md) selects exactly one next milestone: independent offline occlusion/reacquisition evaluation. Later implementation choices must demonstrate a benefit on that evidence before changing a working module.
