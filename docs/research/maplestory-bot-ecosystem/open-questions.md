# Open questions and research limits

Research date: 2026-11-01. See the [index](README.md), [catalog](repositories.md) and [ranked backlog](improvement-backlog.md). Questions below are deliberately unresolved; source access does not establish native gameplay reliability.

## Evidence we do not have

| Question | Current evidence | What would resolve it |
| --- | --- | --- |
| How often does player identity recover correctly behind bridges, grass, ropes or another player? | [perception tests](../../../tests/test_perception.py) cover partial glyphs, conflicting sprites and lookalikes. [tracking_benchmark.py](../../../tools/tracking_benchmark.py), `load/interpolate`, uses detector-confirmed anchors and interpolated positions. | Independently labelled held-out sequences with identity, visibility class and uncertainty. Interpolated hidden boxes are model assumptions, not native ground truth. |
| Can minimap coordinates constrain reacquisition without circular dependence? | [LivePosition.update](../../../src/maplebot/live_position.py) fuses fresh player feet with marker/camera information; [PositionInterval.update](../../../src/maplebot/map_alignment.py) bounds quantization and systematic bias. | Identify precisely which transform terms remain independent when the player disappears. Expire stale transforms and compare search recall with/without the prior. |
| Does the native client use the reference client's marker origin and integer projection? | [Prior position research](../../position-evidence-research.md) derives a reference-client formula but records asset-origin and coordinate-convention uncertainty. | Compatible source asset metadata and independently registered screenshots. Repeated readings cannot average away systematic origin bias. |
| Are other-player minimap dots a reliable negative identity prior? | [MapleStoryAuto](https://github.com/Jeremyzzzzz/MapleStoryAuto) has inspected allowed-zone logic; see [player tracking](player-tracking.md). | Offline crowd sequences with dot merging, vertical separation, camera clamp and stale-marker conditions. A veto must not become an acceptance signal. |
| Does global monster assignment beat the current greedy matching? | [EnemyTracker.update](../../../src/maplebot/enemy_tracking.py) and external [tracking comparisons](computer-vision.md). | Same labelled crossing/overlap sequences, fixed detections, ID switches, false merges and runtime. More complex tracking is unjustified if ambiguity is irreducible from pixels. |
| Can damage be attributed to our particular attack? | [CombatEvidence.snapshot](../../../src/maplebot/combat_evidence.py) explicitly reports null hit confirmation. Range compatibility is only eligibility. | Isolated temporal feedback with confounders: other players, multi-hit skills, damage text overlap, projectile delay, despawn and camera exits. No generic tracker supplies causal damage evidence. |
| Is capture the actual bottleneck? | [Application._run/_process](../../../src/maplebot/runtime.py) already records capture/perception/position/publication timing. | A current controlled replay and input-free capture profile, including tail latency, frame age, scene density and machine/build metadata. This audit runs neither. |
| Does a neural detector improve Classic enough to justify deployment cost? | [MapleStoryAuto](https://github.com/Jeremyzzzzz/MapleStoryAuto) and [TinForge/MS-ML-Bot](https://github.com/TinForge/MS-ML-Bot) contain integrations; see [monster detection](monster-detection.md). | Matching client artwork, an independent dataset, CPU and optional GPU measurements, and checked licenses for code, weights and training assets. GPU necessity and advantage are unproven here. |
| Are saved route proofs portable across movement implementation or physics changes? | [MoveProofs](../../../src/maplebot/move_proofs.py) binds saved move IDs to map hash and timestamp; [NavigationRuntime](../../../src/maplebot/navigation_runtime.py) loads these proofs. | Audit provenance of executor version, input mapping and physics assumptions separately from the existing map/profile hash. Do not invalidate user evidence casually. |
| Are failure clips complete under disk errors/backpressure? | [SessionRecorder._write/_frame](../../../src/maplebot/recorder.py) bounds frame jobs; non-frame write errors do not increment dropped-frame count. | Fault-injected disk-full/write-denied tests and explicit completeness manifests; preserve all old recordings. |

## Unverified external claims

Readme videos, popularity, names containing “AI,” configurable FPS and training scripts do not demonstrate reliable Classic gameplay. None of the reviewed bots was executed. Latest default-branch commit time is a maintenance signal, not proof of active support; unarchived does not mean maintained. Inactive projects are labelled as such rather than declared abandoned without evidence.

External tracker papers and benchmark tables use different data, detectors and hardware. We do not transfer their accuracy, FPS or latency to this engine. Source-level defects or missing checks are bounded to the inspected revision and path, not allegations about every version.

The archive Auto-Maple fork is a separate repository identity but not independent evidence of an algorithm's success. Dependencies and model assets need their own license checks. A public repository without a license is inspectable, not automatically reusable. No external implementation was copied into the application.

## Preserved research requiring caution

[oss-bot-research.md](../../oss-bot-research.md) and [movement-bot-research.md](../../movement-bot-research.md) are retained. The former includes numeric cost estimates such as “0.1 ms,” “microseconds,” and a “5×” search comparison without a reproducible measurement attached to those recommendations. This audit does **not** adopt those estimates. Its blanket GPU-bound characterization of YOLO is also not established: runtime and feasibility depend on model/backend/device. Its older local revision must not override current source behavior, including the bounded hidden-target attack path described in [combat](combat.md).

## Search limitations and exclusions

Broad discovery covered MapleStory, Classic, Artale, v62/v83, private-server bots, minimap/pathfinding, screenshot automation, multi-object tracking, capture and behavior trees. Searches of GitLab, Codeberg and a self-hosted Gitea result yielded irrelevant screenshot-service/colorbot or weakly evidenced candidates; none is counted simply to meet a quota. Private-server simulators and memory-reading/client-modifying bots do not answer the screenshot-only question. Rune solvers are assessed only as bounded visual pipelines, not as a recommendation to automate protection challenges.

Search is not exhaustive. Default-branch metadata can change after this date; pinned source findings remain tied to their recorded SHA. No dependencies were installed, external code executed, binaries/models downloaded, gameplay settings changed, engine restarted or native batch run. Static tests were inspected, not rerun as evidence of application correctness.

## Bounded experiments after the selected milestone

The only recommended next milestone is the offline benchmark in the [backlog](improvement-backlog.md#one-next-implementation-milestone). Later experiments should change one variable: minimap search prior, negative identity veto, assignment strategy, timestamp-aware velocity, then optionally a lightweight detector. Keep identical inputs and splits; compare wrong-identity acceptance, reacquisition latency, abstention, ID switches and processing tails. A failed experiment is useful evidence, not a reason to loosen safety gates.
