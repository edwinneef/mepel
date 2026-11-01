# MapleStory bot ecosystem research

**Research date:** 2026-11-01. **Scope:** screenshot-only computer vision, tracking, navigation, combat, input reliability, performance and development tooling. **Result:** 20 public repositories source-inspected; 17 deep inspections and three focused inspections. All nine requested seeds exist. No application code, dependencies, gameplay settings or active configurations changed; no external code or native gameplay executed.

Local baseline: `630d7ad0c3ab30f0fb7042710f8817792c45ec46`. The actual engine is Python/OpenCV/NumPy/MSS with a React/TypeScript workbench; recommendations reflect that source rather than assuming a Node engine. Existing research, including the initially untracked `docs/oss-bot-research.md`, is preserved.

## Executive findings

1. **Minimap information can guide screen-space reacquisition without pretending the player is visible.** MapleStoryAuto implements minimap/screen relationships and candidate zones. Our current fused localization is stronger in freshness handling; its valid independent information may improve the search ROI. Camera clamping, quantization and circular dependence on fresh player feet must be addressed. [Player tracking](player-tracking.md)
2. **Weak observations can maintain established monster tracks without spawning weak new targets.** ByteTrack's two-pass association supplies a concrete pattern. Our enemy tracker already has partial evidence, expiry and terrain bounds; compare a narrow association change rather than replace it. [Computer vision](computer-vision.md), [monster detection](monster-detection.md)
3. **Explicit track state is more valuable than an indefinitely retained coordinate.** Several Maple bots silently reuse stale minimap locations; some recover with random motion. Our identity recovery, stop/release and bounded navigation are strengths to preserve. Timestamp-aware prediction can be tested separately from authority to act. [Input and automation](input-and-automation.md), [navigation](navigation.md)
4. **Frame age and buffer ownership matter more than configured capture FPS.** DXcam exposes source timestamps/latest-frame buffers; copied versus borrowed images and duplicated frames have different semantics. Our engine already has stage timing and asynchronous publication. Profile end-to-end freshness before replacing MSS or adding threads. [Performance](performance.md)
5. **Independent labels and complete failure evidence are the foundation for useful improvement claims.** Our tracking benchmark partly derives truth from detector anchors/interpolation; Airtest illustrates source-linked visual reports, while our recorder has a concrete non-frame write-error visibility gap. Preserve replay, add honest label provenance and completeness. [Debugging](debugging.md)

## Top five recommendations

1. Freeze an independently labelled offline occlusion/reacquisition corpus and baseline report.
2. Evaluate a minimap-guided search ROI using only valid, fresh, independently supported transforms.
3. Evaluate marker and other-player consistency as negative identity evidence.
4. Calibrate confidence/ambiguity by cue and visibility; examine hidden-target uncertainty at range boundaries.
5. Profile capture-to-decision/dispatch age and tail latency before optimizing a backend or model.

These are ranked hypotheses and evaluation work, not verified improvements. The [20-item backlog](improvement-backlog.md) gives dependencies, effort, performance implications, risks, confidence and acceptance criteria. No measured speedup or Classic accuracy rate is claimed.

## Exactly one next implementation milestone

**Independent offline occlusion and reacquisition benchmark**, built on existing recordings and replay tools. Freeze source/config/frame hashes; annotate identity, visible cues and unknown intervals independently of detector output; separate real footage from synthetic fixtures; report false identity acceptance, recovery delay, missed visible detections and abstention with coverage. Existing footage gaps remain explicit. Do not alter detector behavior, input gates or gameplay policy in this milestone. [Full scope and acceptance](improvement-backlog.md#one-next-implementation-milestone)

## Read by task

Load this index and only the relevant topic; the evidence audits are for checking exact source claims, dates or licenses.

| Document | Use it for |
| --- | --- |
| [repositories.md](repositories.md) | Complete 20-repository catalog, inspection depth, maintenance, licenses, relevance and pinned entry points |
| [player-tracking.md](player-tracking.md) | Nametags, body fragments, occlusion, identity, prediction and minimap/world localization |
| [monster-detection.md](monster-detection.md) | Animation templates, learned detectors, overlaps, persistent IDs and target evidence |
| [combat.md](combat.md) | Range/facing/timing, melee/ranged behavior, hidden targets and causal hit evidence |
| [navigation.md](navigation.md) | Geometry, route graphs, movement/rope/landing evidence, hybrid localization and recovery |
| [computer-vision.md](computer-vision.md) | Algorithm comparisons, temporal models, confidence and lightweight alternatives |
| [input-and-automation.md](input-and-automation.md) | Scheduling, ownership, state machines, cancellation, key release and stop behavior |
| [performance.md](performance.md) | Capture, ROI, caching, workers, buffer ownership and meaningful profiling |
| [debugging.md](debugging.md) | Overlays, datasets, offline replay, logging, evidence integrity and development workflow |
| [architecture.md](architecture.md) | Current implementation inventory, strengths, concrete weaknesses and integration boundaries |
| [improvement-backlog.md](improvement-backlog.md) | Ranked 20-item backlog and the single selected milestone |
| [open-questions.md](open-questions.md) | Missing evidence, experiments, source/search limitations and old claims not adopted |
| [evidence-maple-perception.md](evidence-maple-perception.md) | Five seed repositories: exact commits, licenses and inspected perception functions |
| [evidence-maple-navigation.md](evidence-maple-navigation.md) | Seven Maple repositories: route/combat/control source audit |
| [evidence-general-systems.md](evidence-general-systems.md) | Eight tracking/capture/automation libraries: source and dependency audit |

## Methodology and evidence levels

1. **Current project first:** inspect relevant source, tests, configuration and preserved research. Record the baseline in [architecture](architecture.md) before assessing replacements. Test definitions were read, not rerun as proof of live success.
2. **Broad discovery:** public searches for MapleStory/Classic/Artale/v62/v83 bots, minimap/platform navigation, screenshot automation, tracking, capture and behavior trees; follow relevant fork/dependency lineages. Non-GitHub search produced no additional sufficiently relevant source-audited entry; exclusions are documented rather than counted.
3. **Source inspection:** query public repository/default-branch commit metadata, inspect trees and relevant source/dependency/license text, reuse verified matching ignored checkouts where present. Do not run external code or download executable/model artifacts. Deep inspection means control flow and algorithm details plus licensing/dependencies; three focused entries cover a historical fork, a narrow controller and a preprocessing project.
4. **Comparison:** distinguish source-verified behavior, README/author claims, expected tradeoffs, measured evidence and unknowns. No foreign FPS/accuracy numbers are transferred to this machine/client. Use SHA-specific external file links and relative local links.
5. **Recommendations:** preserve working abstractions and gates, prefer narrow experiments, rank by evidence/reliability value and operational cost. A public license is checked separately from model/data/dependency rights.
6. **Persistence and validation:** save all topic reports and evidence audits here; check required-file coverage, relative file/heading links, external source-link pinning and documentation-only working-tree changes. Record the final validation result below.

Source verification establishes what code does, not that an entire repository works on our server. Input acceptance, offline replay, screenshots, native movement and confirmed damage remain different evidence levels. None of the external repositories was executed or independently benchmarked.

## Existing research and compatibility

Preserved context: [OSS perception notes](../../oss-bot-research.md), [movement bot research](../../movement-bot-research.md), [position evidence](../../position-evidence-research.md), [offline navigation harness](../../offline-navigation-harness.md), [single-platform combat](../../single-platform-combat.md), [bounded navigation](../../bounded-navigation.md). The newer source findings here take precedence for this baseline, particularly actual hidden-target behavior and the distinction between timing estimates and measurements. See [open questions](open-questions.md#preserved-research-requiring-caution).

Limitations: exact native occlusion accuracy, hit attribution, movement compatibility, model generalization and hardware performance remain unmeasured. No independent universal full-occlusion solution was found. Inactive/unlicensed/incomplete repositories remain useful comparisons but are not turnkey dependencies. Existing application reliability is not newly certified by this documentation audit.

## Validation record

Passed: 16 research documents, all 13 required reports, 284 relative file/heading links, 140 unique commit-pinned GitHub source links, and complete index coverage. Git working-tree scope contains only these research documents and the two agent-instruction pointers. `git diff --check` passed. Link checking verifies local targets and source-link pin syntax; external HTTP availability relies on the source acquisition audit, not a second crawl. No application tests, external programs, capture sessions or gameplay batches ran.
