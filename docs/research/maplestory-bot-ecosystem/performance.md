# Performance and optimization

Research date: 2026-11-01. **No performance experiment was run for this audit.** Algorithmic cost, upstream benchmark claims, historical artifacts, and measurements on this bot are different evidence classes.

[Index](README.md) · [computer vision](computer-vision.md) · [debugging](debugging.md) · [source audit](evidence-general-systems.md)

## Existing performance work

| Stage | Inspected local implementation | Implication |
| --- | --- | --- |
| Capture | [Capture.grab/window](../../../src/maplebot/capture.py): MSS region grab, BGR copy, before/after title/size/DPI/window-position checks | A required owned frame and window validity checks already exist; removing copies/checks needs correctness evidence |
| Camera | [CameraTracker](../../../src/maplebot/perception.py) half-resolution correlation plus [verified sparse flow](../../../src/maplebot/camera_motion.py) | Full-frame dense flow is not currently necessary |
| Template selection | `TemplateDetector.detect/_active_templates` selects map species and skips monsters in player-only mode | Active template count matters more than catalog total |
| Recognition | `_window/_observe_window/_observe_full`, batched sprite/color processing and thread pool | ROI/fallback and parallel processing are implemented |
| Recording | [SessionRecorder](../../../src/maplebot/recorder.py) reuses encoded frames, writes on a separate thread, bounds queued frame count | Recording avoids blocking the control path on ordinary frame writes |
| Replay / profiling | [perception_benchmark.py](../../../tools/perception_benchmark.py), [tracking_benchmark.py](../../../tools/tracking_benchmark.py), [replay.py](../../../src/maplebot/replay.py) | Reusable stage timing, percentile and semantic-regression infrastructure already exists |
| Presentation | [CaptureConfig](../../../src/maplebot/config.py) declares separate capture and display cadences | Configured refresh rate is not measured perception rate or gameplay freshness |

The default `CaptureConfig` values are 12 capture FPS and 30 display FPS. They are declarations, not observed throughput; active configuration was not changed or asserted to equal defaults.

## Capture backends: relevant implementation differences

Current upstream [MSSImplGdi.grab](https://github.com/BoboTiG/python-mss/blob/6c00e6e9c735d4e65c8b72f2a732e463078a901e/src/mss/windows/gdi.py#L343) caches DIB storage by dimensions and performs BitBlt/GdiFlush with per-call device-context cleanup. That HEAD is not necessarily our installed `mss>=10,<11` implementation.

DXcam's [capture loop](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/dxcam/core/capture_loop.py#L37) writes into a ring buffer. Its [latest-frame API](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/dxcam/dxcam.py#L621) can return source timestamps. Video mode may copy the prior frame into a new buffer slot; buffer availability therefore does not prove new visual evidence.

[DXCamera.grab](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/dxcam/dxcam.py#L208) documents and implements copy/view ownership. A non-owning view can change under a detector, recorder or encoder if the next capture reuses storage. The local explicit BGR copy is not demonstrably wasteful without a lifetime-safe replacement.

Upstream throughput claims use other machines and display workloads. They cannot establish improvement for this bot's cropped window, capture cadence, detection work, focus conditions or end-to-end control age. **Do not replace MSS before attribution shows capture is material.**

## Optimization comparison

| Option | Expected cost effect (estimate) | Reliability / operational risk | Integration effort | Decision |
| --- | --- | --- | --- | --- |
| Measure stage and observation age together | Small telemetry overhead | Metric definitions must use correct clocks | Low | Highest-value prerequisite |
| Tune existing ROI/full-scan cadence | Less repeated search when stable | Can miss new actors or fail recovery if ROI becomes self-confirming | Low–medium | Preserve periodic/uncertainty-triggered full search; compare held-out clips |
| Cache immutable template preprocessing | Avoid repeat grayscale/mask/signature work | Invalidate on template/map/version changes | Low–medium | Much already cached; profile residual work first |
| Reuse array storage | Lower allocations/copies | Aliasing between threads and delayed recording | Medium | Only with explicit ownership and tests |
| Adaptive expensive detection | Fewer neural/OCR/template passes | Lower detector rate increases prediction age | Medium | Keep capture/freshness and safety monitoring responsive |
| More detector workers | Can help independent native OpenCV work | Oversubscription with OpenCV threads, allocation pressure, nondeterministic completion | Medium | Measure worker counts on identical output corpus |
| DXcam adapter | Potential capture-latency gain | COM/backend recovery, duplicate frames, timestamp conversion, multi-monitor/resize semantics | Medium | Conditional experiment, no assumed gain |
| GPU detector | Potential batched inference acceleration | Model startup, transfer overhead, memory use, weights and license management | High | Only if accuracy gains justify it |
| Latest-only asynchronous expensive worker | Bounds backlog and output age | Result/frame mismatch if timestamp and version are omitted | Medium | Suitable for optional OCR/analysis; never fuse results as current blindly |

These are hypotheses, not benchmark results. A faster stage can leave the whole development/test cycle unchanged if setup, labeling or game preparation dominates.

## Measurement design

Use existing [perception_benchmark.py](../../../tools/perception_benchmark.py) for paired output/timing comparisons. It supports reference outputs, tolerance checks, per-source results, load time and optional detector-stage timing. Its synthetic crowded composites stress workload; they do not prove natural-scene accuracy.

Record:

- Source commit, dependency versions, hardware, resolution, map, template revision, active variants, worker settings and replay manifest.
- Cold initialization separately from warm processing.
- Capture, camera, candidate generation, template scoring, association, decision, encoding and queue timings.
- p50 and a tail percentile per stage, plus **capture-to-dispatch observation age** and frame-gap distribution.
- Frames presented, distinct source frames, dropped/duplicated frames and missing observations.
- Accuracy/identity/recovery metrics from independent labels, not merely matching previous detector outputs.
- Total setup, annotation, execution, analysis and delivery wall time separately.

Use the same recorded inputs and configuration for paired detector comparisons. Run isolated source branches or equivalent import isolation without altering active gameplay settings. Keep external capture experiments separate: offline replay cannot measure capture throughput or native input latency.

## Concrete risks found in source

1. **Evidence derived from the baseline can hide error.** `tracking_benchmark.interpolate` obtains anchors from recorded confirmed player observations, then interpolates gaps. It is useful regression material; it is not independent truth for hidden player motion. This affects performance/accuracy tradeoffs selected using those scores.
2. **Recording backpressure is only partially bounded.** `SessionRecorder._frame` bounds pending frame jobs; decision/event line jobs use the unbounded queue. Slow storage can grow non-frame backlog. This is a source-level possibility, not a measured leak.
3. **Non-frame write failures lack explicit reporting in the writer.** `SessionRecorder._write` catches OSError but increments `dropped` only for frame jobs. A failed line/mkdir write is not represented by that frame-drop counter. This is an observability weakness, not a reason to block research on live reproduction.
4. **Detection thread count is not free throughput.** The current thread pool and OpenCV calls make extra parallelism a measurement question. No finding here establishes a current CPU bottleneck.

Preserve lower-priority visualization, encoding and recording isolation from stop/release paths. Performance changes must retain capture validity, bounded decisions, uncertainty classification and exact input ownership.

