# Research roadmap implementation evidence

Date: 2026-11-01. [Coverage register](implementation-register.md) · [Machine-readable register](implementation-register.json). These are offline implementation results, separate from the original research snapshot and L01 native acceptance.

## p1 — Preservation

All 16 original research reports and both pre-existing dirty agent instruction files retain their recorded hashes. Commit `f30df0a` added 33 stable entries and preserved the full original phase criteria. Existing recordings, calibration, maps, proofs and settings remain untouched.

## p2 — Independent occlusion baseline

[Evaluator](../../../tools/occlusion_evaluation.py), [paired renderer](../../../tools/occlusion_report.py), [frozen corpus](occlusion-corpus.json), [baseline A](../../../artifacts/research-roadmap/p2/baseline-a.json), [baseline B](../../../artifacts/research-roadmap/p2/baseline-b.json), [paired overlays](../../../artifacts/research-roadmap/p2/comparison/index.html).

The labels were written from raw screenshots before detector evaluation. Eleven real frames come from two separate sessions; six synthetic frames form two visible/covered/reappeared sequences. Every image, config, detector source and all 20,533 template-tree files are hashed. Names were read directly from template bitmaps; only the HeneSyphilis token maps to the own-player label. No detector boxes or interpolation supply ground truth.

| Stratum | Frames | Independently identifiable | Correct fresh identity | Wrong fresh | Unknown-label fresh outputs | Abstentions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Real bridge | 6 | 1 | 1 | 0 | 3 | 2 |
| Real ladder | 5 | 2 | 2 | 0 | 3 | 0 |
| Synthetic covers/reappearance | 6 | 4 | 4 | 0 | 0 | 2 |

Both unchanged runs produced identical semantic results. Timing is retained separately; detector initialization took about 38–39 seconds per sequence in run A, whereas the 17 detections totaled about four seconds. This measures this offline run with its machine load, not native latency or expected improvement.

Unknown labels are neither successes nor proven false detections. Partial names remain unknown when independent identity is unclear; covered feet have no exact box. Three real ladder frames have position labels but no independently clear full identity. Body boxes have a declared 12-pixel foot-center tolerance and are not collision hitboxes. Real samples are sparse, so recovery duration is null. Synthetic sequences check abstention/reappearance mechanics only. Runtime resume is explicitly not measured.

The held-out session was already used by the old benchmark; this split is reserved from future tuning, not historically unseen. No threshold promotion or general accuracy/calibration claim is justified by three identifiable real samples. New raw recordings were not requested or made. Synthetic recipes in the manifest reconstruct covers from the protected source frame; output images reside in artifacts.

Reproduce using a NEW output path:
```powershell
.venv\Scripts\python.exe -m tools.occlusion_evaluation --manifest docs/research/maplestory-bot-ecosystem/occlusion-corpus.json --output artifacts/research-roadmap/p2/new-baseline.json
.venv\Scripts\python.exe -m tools.occlusion_report --manifest docs/research/maplestory-bot-ecosystem/occlusion-corpus.json --before artifacts/research-roadmap/p2/baseline-a.json --after artifacts/research-roadmap/p2/new-baseline.json --output artifacts/research-roadmap/p2/new-comparison
```

A changed source/config/template hash requires an explicitly versioned candidate manifest; keep original labels and original baseline. Do not silently repin the frozen baseline. Compare label hashes and identical splits when creating a candidate.

## p3 — Recording and timing

[Recorder](../../../src/maplebot/recorder.py), [fault tests](../../../tests/test_recorder.py), [timing reporter](../../../tools/pipeline_timing_report.py), [271-frame timing artifact](../../../artifacts/research-roadmap/p3/timing.json).

The recorder exposes bounded write-error history, per-kind failures, active/queued work and a sticky incomplete status. An error remains visible after a new recording starts; a later successful write does not erase known loss. Disk-full-style faults in frame, line and mkdir operations were injected. Stop remains nonblocking and subsequent writes can succeed. These are recorder-lifetime diagnostics: complete means requested writes drained without known loss, not fsync durability or complete scene coverage. The last failing write cannot guarantee its own persistence to a failed disk.

The existing recording shows perception p50 165.238 / p95 205.0765 / p99 233.561 / max 239.752 ms; capture p95 50.418 ms; PNG callback p95 111.436 ms. Asynchronous stages overlap and are never summed. Twelve unique tickets and 34 backend events were identified, with no recorded interruptions. These are historical measurements, not new live profiling.

Freshness and cancellation already exist in `Application._process`, `NavigationRuntime` and `KeyboardController._execute_schedule`: 500ms observation guards, source/view generations, cancellation checks and expired key schedules. Remaining telemetry gaps are causal observation-to-ticket identity/deadline, cancellation-request timestamps, and recording/HTTP/UI duration. Worker-start time is not first physical dispatch. Additional contract work is tracked rather than treating missing telemetry as zero latency.

## p4 — Map and proof audit

[Proof auditor](../../../tools/movement_proof_audit.py), [proof report](../../../artifacts/research-implementation/movement-proof-audit-20261101.json), [alignment audit](../../../artifacts/research-implementation/alignment-audit-20261101.json), [existing independent anchor](../../../artifacts/automatic-alignment/southperry-independent-anchor.json).

Four saved proof files contain 16 moves with matching normalized map hashes. All 16 lack historical executable/control/physics provenance; they remain UNKNOWN. The auditor hashes the current context for comparison but never claims it was the historical context. No proof was rewritten, invalidated or promoted. New metadata cannot retroactively establish old facts.

Existing `alignment_corpus.py` already separates generated predictions from withheld independent anchors, models signed quantization, validates asset/build hashes and refuses incompatible bundles. Current audit admits zero reserved maps because compatible raw terrain/render/placement data and aliases are missing. Southperry's separate rope/ladder anchor evidence supports X consistency only; it supplies neither independent Y/contact truth nor other-map acceptance. Existing constructed alignment tests passed; general minimap-to-world promotion remains evidence-gated.

## p6 — Monster assignment experiment

[Experiment](../../../tools/monster_association_experiment.py), [eight-case artifact](../../../artifacts/research-roadmap/p6/association.json).

This uses fixed constructed detections and known construction identities. A bounded exhaustive reference preserves existing species, distance, ambiguity and birth gates; its greedy mirror must agree with the actual EnemyTracker before a comparison is accepted. In one competition case, global assignment gives two correct matches instead of one incorrect match. In a true crossing, both methods switch two identities. Weak/predicted clutter creates no birth, while confident clutter can create an unsupported birth in both.

No runtime association change is promoted. Eight one-transition examples do not establish real multi-frame accuracy, and the global reference was slower in these tiny solver-only measurements. Revisit B07/B08 after independently labelled real crossings/weak positives establish a quality gain; do not lower birth thresholds from this result.

## Validation and authorization

- [First grouped dev cycle](../../../artifacts/dev-cycle/20261101-115031-7046744/result.json): 141 tests passed in 7.35 seconds; affected Ruff checks passed. This runtime excludes investigation, annotation, detector loading and bookkeeping.
- Both full unchanged occlusion evaluations passed; semantic equality and 17 paired overlays saved.
- Auditor subtask: 48 combined proof/alignment tests passed; subsequent focused proof checks passed. These are covered by the grouped run.
- No live batch, focus action, capture, engine restart, deployment, dependency installation or active configuration change was performed. The existing engine has not loaded the new recorder diagnostics; loading them remains part of a separately authorized restart/native batch.
- L01 remains required and pending. The older 38-second partial result is historical evidence, not the requested supervised 60-second outcome.


## Completed contract and experiment increment

The causal observation gap described in the initial p3 audit is now closed for queued gameplay input. [KeyboardController](../../../src/maplebot/keyboard.py) stores immutable capture time/deadline, sequence and source/view generation on each plan and outcome. Before every key-down it rejects an expired original frame, invalid/expired current context, generation change or regressing sequence. A newer frame cannot renew an old action. Key-up/Stop remain unconditional; current-priority potion scheduling retains its existing checks. The runtime callback takes no application lock while the controller lock is held.

Events now retain the originating observation, ticket and capture age. The timing reporter consumes this explicit causal metadata; it never substitutes a newer surrounding frame. Legacy logs still have unknown causal age. Release events may occur after a deadline and are excluded from key-down violations. Remaining unmeasured tails are explicitly retained. No new timing threshold or active setting was introduced.

- [Final legacy timing report](../../../artifacts/research-roadmap/p3/timing-final.json): 271 historical frames; new causal ages correctly remain unavailable.
- [Final proof audit](../../../artifacts/research-roadmap/p4/proof-audit-final.json): all four proof/area file hashes equal the earlier audit; 16 historical provenance records remain unknown despite current code changes.
- [Pure recovery intentions](../../../artifacts/research-roadmap/p2/comparison-policy/recovery-intents.json): zero resume requests in the sparse/short seed sequences, therefore no claimed false-resume accuracy. Tests exercise supported, wrong, hidden and unknown resume-label scoring. This is pure policy replay, not runtime gate or native acceptance.
- [Player experiments](../../../artifacts/research-roadmap/p5/player-experiments.json), [association/suppression](../../../artifacts/research-roadmap/p6/association-suppression.json) and [navigation](../../../artifacts/research-roadmap/p7/harness.json): decisions and explicit deferrals are recorded in [implementation-decisions.md](implementation-decisions.md).
- [Grouped checks](../../../artifacts/dev-cycle/20261101-120512-1859100/result.json): 271 tests passed in 3.58s; initial lint failed on one test-name line length. [Corrected affected check](../../../artifacts/dev-cycle/20261101-120544-2731211/result.json): four tests and all affected lint paths passed. A subsequent hidden-visibility scoring case passed (five report tests in 0.28s); its long test name was shortened and Ruff passed. These were formatting failures, not ignored failures.
- Final controller/runtime/nav/potion/scheduler/timing validation: 268 tests passed in 8.40s, reported by the owning subagent; Ruff/diff checks passed. This includes original-frame expiry during reaction delay, queue delay despite newer frames, invalid current context, sequence regression, source/view changes, chord expiry with release, unconditional key-up, potion priority and Stop. These checks use test backends, not game input.
- X02 owner validation: 151 affected decision/enemy/replay checks passed; decision/combat evidence cases also passed in the grouped run. Current policy preserves the original club/combat choices while restricting uncertainty and known-ID switching.
- Preservation/coverage validator: all33 IDs, all16 original reports, original agent instructions, source headings and code seams pass. The active config and frozen detector-source hashes are unchanged.
- Tracking window: about38 minutes elapsed from the recorded task-start checkpoint to coverage validation; this excludes earlier startup/initial reads. The duration includes annotation, inspection, cold detector loads, experiments and bookkeeping. Individual test runtimes above are not a complete-workflow speed claim.

## p10 — Coverage handoff

Every B01–B20 and X01–X12 entry has evidence and an implementation, retained-system, experiment or explicit deferral disposition; L01 preserves the old outcome and decisions. Original phase criteria and original dependencies remain in JSON. Execution dependencies were narrowed only for independent constructed experiments and decision reviews; real localization promotion still requires p4 evidence, and native acceptance remains separate.

Required remaining acceptance: p4 compatible independent reserved-map bundles; p7 complete action-aligned source footage; p9 explicit live batch authorization/operator presence. No ready evidence-supported runtime promotion is hidden behind these blockers. Candidate detector/tracker/calibration changes remain conditional on their per-ID labels and measurements.

No engine was restarted or gameplay batch run. New runtime code is on disk, not claimed loaded in the existing engine. The project goal remains active.

