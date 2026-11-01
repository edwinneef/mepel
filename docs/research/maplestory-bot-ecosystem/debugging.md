# Debugging, replay and development tools

Research date: 2026-11-01. This document proposes additions to existing tooling; no recording, test batch, gameplay input or benchmark was run.

[Index](README.md) · [performance](performance.md) · [player tracking](player-tracking.md) · [backlog](improvement-backlog.md) · [source audit](evidence-general-systems.md)

## What already works at the source level

| Capability | Local evidence | Boundary |
| --- | --- | --- |
| Detection/tracking overlays | [perception.py](../../../src/maplebot/perception.py): `annotate`, `_tracking_snapshot` expose observed/predicted boxes, confidence and search region | Displaying a prediction does not confirm the player is there |
| Incident capture | [recorder.py](../../../src/maplebot/recorder.py): `SessionRecorder.observe/trigger` retain pre-roll and decision/event logs; manual/full recording also exists | Missing/dropped frames must remain visible to evaluators |
| Offline screenshot replay | [replay.py](../../../src/maplebot/replay.py): `run_replay` uses raw frames and optional labels, writes observations/decisions and `input_sent: false` | No live capture/focus/input/hit proof |
| Policy replay | `run_policy_replay/write_policy_diff` in the same module | Compares saved decision inputs, not perception correctness |
| Stage profiling | [perception_benchmark.py](../../../tools/perception_benchmark.py): per-stage timings, semantic output comparison, crowded synthetic scenes | Reference-equivalence is not accuracy; synthetic density is not natural overlap |
| Occlusion scenarios | [tracking_benchmark.py](../../../tools/tracking_benchmark.py): `cover/erase/place/scenarios/metrics` | Existing truth derivation is partly detector-based |
| Input timeline | [keyboard.py](../../../src/maplebot/keyboard.py): event sequence, clocks, history ID, dropped-history count | Submission timestamps do not establish native action effects |
| Focused test infrastructure | [capture](../../../tests/test_capture.py), [camera](../../../tests/test_camera_motion.py), [recording](../../../tests/test_recorder.py), [scheduler](../../../tests/test_scheduler.py), [replay](../../../tests/test_replay.py) | Sources inspected; not rerun for documentation changes |

Preserve existing recordings and maps. The current recorder deliberately avoids automatic deletion. Dataset organization must use manifests and derived outputs without rewriting originals.

## Most important evidence weakness

[tracking_benchmark.py](../../../tools/tracking_benchmark.py) calls recorded confirmed player boxes anchors; `interpolate` fills gaps between those boxes using linear interpolation up to its configured gap limit. `metrics` then computes localization error and a distance-based hijack count against that derived truth.

This is valuable for deterministic synthetic-regression comparisons, but it cannot independently establish correctness through a real jump, ladder crossing, bridge occlusion or camera transition. A detector that was wrong in the anchor frames can make the labels wrong; interpolation assumes a trajectory that may not be physically real. Distance-based hijack counts also do not identify which visible character was chosen.

The existing [run_replay](../../../src/maplebot/replay.py) already accepts a labels file. Extend evaluation around that seam rather than replacing the replay engine. Independently labeled held-out sequences are the prerequisite for ranking alternative filters or detectors honestly.

## External reporting pattern

Airtest's [LogToHtml._analyse/_translate_step](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/report/report.py#L100) joins nested step logs, screenshots, code, assertions and traceback. Its [loop_find](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/core/cv.py#L40) records an image when a search times out.

The useful adaptation is a compact visual evidence bundle per failure:

- Raw frame and annotated frame, with frame ID/capture time.
- Measured player evidence versus predicted state, visible fragments and search ROI.
- Track IDs and last confirmed times; ambiguous associations shown explicitly.
- Camera shift/support and minimap/world-projection uncertainty.
- Selected action/ticket and subsequent observed consequences.
- Stop/recovery reason, deadline, missing-frame/history indicators.
- Source/config/template/map fingerprints and label provenance.

This can use existing recorder/replay output and React components. Importing Airtest would duplicate tools and conflict with our current NumPy/OpenCV dependency ranges. Its report code is Apache-2.0; application adaptation is optional and was not performed.

## Held-out dataset contract

A practical manifest should record, per sequence:

| Field | Purpose |
| --- | --- |
| Original recording path and content hash | Reproducibility without copying/replacing originals |
| Source/build and capture/layout metadata | Avoid mixing incompatible assets or coordinate frames |
| Scenario tags | Bridge, rope, foreground decoration, another player, monster crowd, camera scroll, full disappearance |
| Label provenance | Human observation, public geometry with version, synthetic exact transform, or weak/interpolated label |
| Actor identity | Prevent a nearby-player box from counting as correct localization |
| Visible regions | Full body, head/torso fragment, tag fragment, minimap only, none |
| Position uncertainty | Label box/feet when visible; interval/unknown when unobservable |
| Expected decision restriction | Pause/search/stop rather than implied permission to act |
| Split membership | Tune on training clips; assess once on held-out sessions |
| Timing/missing frames | Preserve actual intervals; do not silently regularize dropped frames |

Split whole sessions/maps where possible. Adjacent frames from the same clip in both tuning and evaluation leak appearance and motion context. Synthetic paste/inpaint cases remain useful, but report them separately from native occlusion.

## Metrics for the next evaluation milestone

Use definitions and denominators that future agents can reproduce:

- Detection precision/recall on independently visible labels.
- Correct own-player identity rate and identity-switch events.
- Confirmed-position error only where the label is independently observable.
- False-confirmed and false-resume frames during ambiguous/full occlusion.
- Time from independently visible reappearance to stable correct reacquisition.
- Stop/pause behavior and maximum interval of unsupported continued action intent in replay.
- Camera-estimation error or consistency where an independent reference exists.
- Processing latency and actual frame gaps, stratified by scenario.

A safe pause is not functional tracking success. A smooth predicted path is not accurate localization. A detector that achieves higher recall by confirming another player is a regression even if average box error improves.

Thresholds and acceptance limits should be chosen before trying alternatives, using the current baseline and project safety expectations. This audit does not fabricate a pass rate.

## Diagnostics improvements supported by current code

**Recording integrity:** `SessionRecorder._write` catches OSError; only frame failures increment its drop counter. Expose non-frame persistence errors and queue/backlog status in a later scoped change. Inject write failures in offline tests, and verify the report marks evidence incomplete. Keep stop/release independent of storage.

**Comparative report:** show baseline/candidate overlays side by side for the same frame IDs and clock domain; list changed identity, confidence class, recovery state and action intent. Airtest demonstrates report assembly, while current replay supplies the needed records.

**Uncertainty visibility:** differentiate measured, partial, coasted and lost states through labels/line styles as well as color. Show prediction age and camera uncertainty; never make a coasted track look like a fresh confirmed observation.

**Dataset collection:** select existing first-failure clips first. Request another live recording only for a specific missing condition after offline work identifies the gap. This respects the project's operator-presence and bounded-first-failure rules.

## Validation in this research task

Documentation/source inspection only. No application tests were needed to validate runtime behavior because none was changed. The parent research pass validates Markdown coverage, local links and documentation-only scope. Historical test names above identify useful future checks, not results claimed for this audit.

