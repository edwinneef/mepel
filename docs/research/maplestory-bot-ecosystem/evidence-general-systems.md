# General vision, capture and automation: source audit

Research date: 2026-11-01. This audit covers **eight distinct repositories, all inspected beyond their README**. No external code was executed, dependencies installed, models loaded or binaries downloaded. Default-branch commit timestamps below were read from the GitHub commit API, not inferred from repository `updated_at` or `pushed_at`. All eight returned `archived: false`; age alone does not establish abandonment.

Return to [index](README.md), [catalog](repositories.md), [computer vision](computer-vision.md), [input](input-and-automation.md), [performance](performance.md), or [debugging](debugging.md).

## Discovery and evidence standard

Initial current-project reads covered `capture.py`, `camera_motion.py`, `perception.py`, `keyboard.py`, `scheduler.py`, `recorder.py`, `replay.py`, `config.py`, tracking/perception benchmarks, and relevant test definitions. External alternatives were compared only after that baseline.

Public search combined screenshot game automation, tracking, DXcam/MSS, and GitLab/Codeberg screenshot-bot queries. The latter yielded no additional implementation worth prioritizing in this slice; Codeberg access was blocked by robots.txt. A surfaced `shaw-s-yu/realtime-game-vision` README was not deep-inspected or included in the eight-repository count: its performance and model-license statements were not accepted as verified facts. Search rank and README claims are not demonstration.

A **deep inspection** here means inspecting algorithm/control-flow implementation plus dependency and license text. It does not mean testing the repository or establishing native gameplay reliability. Source observations are verified; expected integration benefits remain hypotheses. All code reuse would require retaining the relevant notices and reviewing dependency/model terms. No external code was copied into application code.

## Snapshot table

| Repository | Default branch / exact snapshot | Latest default commit (UTC) | License text inspected | Maintenance assessment |
| --- | --- | --- | --- | --- |
| [Norfair](https://github.com/tryolabs/norfair) | master / `e517b4236f6b67a6ecf342f5df1fccb7788dbc54` | 2025-04-30 17:04:22 | BSD-3-Clause | Unarchived; no newer default-branch commit at check |
| [SORT](https://github.com/abewley/sort) | master / `2236dff5019565958b84df7d871d41cc1db58ac7` | 2023-11-28 07:01:46 | GPL-3.0 | Long-inactive reference implementation |
| [ByteTrack](https://github.com/FoundationVision/ByteTrack) | main / `d1bf0191adff59bc8fcfeaa0b33d3d1642552a99` | 2022-12-11 07:05:00 | MIT | Long-inactive reference implementation; `ifzhang/ByteTrack` redirects here |
| [Deep SORT](https://github.com/nwojke/deep_sort) | master / `f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab` | 2025-03-02 09:54:41 | GPL-3.0 | Unarchived; older reference implementation |
| [python-mss](https://github.com/BoboTiG/python-mss) | main / `6c00e6e9c735d4e65c8b72f2a732e463078a901e` | 2026-10-26 12:51:07 | MIT | Recent default-branch activity |
| [DXcam](https://github.com/ra1nty/DXcam) | main / `1e595ff55e57263c4b5d0414828f74104afa86f4` | 2026-03-18 01:40:01 | MIT | Unarchived; recent-year source revision |
| [py_trees](https://github.com/splintered-reality/py_trees) | devel / `786859dcafc4ec9b78ff7ed0950b106c829d2174` | 2026-10-28 02:19:19 | BSD-3-Clause | Recent development activity; development branch is default |
| [Airtest](https://github.com/AirtestProject/Airtest) | master / `d729c631d2032521be1e2168a249a2a89d79af2a` | 2025-12-04 06:48:04 | Apache-2.0 | Unarchived; default snapshot older than repository push activity |

## Norfair

**Stack/dependencies:** Python; NumPy, SciPy, FilterPy, Rich; optional OpenCV. Its inspected manifest constrains modern Python to NumPy `^1.23.0`, conflicting with our declared NumPy 2 range. This is an integration constraint, not a recommendation to downgrade.

**Read files:** [tracker.py](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/tracker.py), [filter.py](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/filter.py), [camera_motion.py](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/camera_motion.py), [manifest](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/pyproject.toml), [license](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/LICENSE).

**Verified:** `Tracker.update` manages initialized, initializing and temporarily dead tracks; optional re-identification uses a supplied distance function. `TrackedObject.hit` masks unobserved low-score points in its measurement matrix. `OptimizedKalmanFilter` stores per-coordinate variances rather than a general dense state matrix. `match_dets_and_objs` greedily consumes the minimum distance; it is **not Hungarian assignment**. Camera flow uses sparse features and Lucas–Kanade tracking.

**Strength/relevance:** useful model for separately visible nametag/head/feet anchors, bounded track lifetime, and camera-coordinate transforms. **Weakness:** no Maple-specific identity features, occluder geometry or control safety; default filter advances in frame steps, requiring deliberate elapsed-time adaptation. Existing local forward/backward camera checks are stronger than the inspected sparse-flow routine. Mature reusable tracking machinery, no demonstrated Classic performance.

## SORT

**Stack/dependencies:** Python, NumPy, FilterPy, LAP (SciPy fallback in code), plotting/demo dependencies. [Source](https://github.com/abewley/sort/blob/2236dff5019565958b84df7d871d41cc1db58ac7/sort.py), [requirements](https://github.com/abewley/sort/blob/2236dff5019565958b84df7d871d41cc1db58ac7/requirements.txt), [GPL license](https://github.com/abewley/sort/blob/2236dff5019565958b84df7d871d41cc1db58ac7/LICENSE) were read.

**Verified:** `KalmanBoxTracker` has a seven-dimensional constant-velocity state; `associate_detections_to_trackers` gates IoU and solves ambiguous assignment; `Sort.update` ages/removes tracks and emits only freshly updated tracks meeting hit criteria (with startup allowance). It requires an update on empty-detection frames too.

**Strength/relevance:** compact association benchmark for monster IDs. **Weakness:** no appearance identity or camera compensation; shrinking partial boxes and low-FPS movement can defeat IoU. Same-species overlapping monsters remain ambiguous. GPL terms require a deliberate reuse decision; algorithmic comparison does not require importing its implementation. Do not replace existing terrain-constrained enemy tracking wholesale.

## ByteTrack

**Stack/dependencies:** Python tracking plus a PyTorch/YOLOX detector/training environment, NumPy, OpenCV, LAP, FilterPy. [byte_tracker.py](https://github.com/FoundationVision/ByteTrack/blob/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/yolox/tracker/byte_tracker.py), [matching.py](https://github.com/FoundationVision/ByteTrack/blob/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/yolox/tracker/matching.py), [requirements](https://github.com/FoundationVision/ByteTrack/blob/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/requirements.txt), [MIT license](https://github.com/FoundationVision/ByteTrack/blob/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/LICENSE) were read.

**Verified:** `BYTETracker.update` first associates high-score boxes with current/lost tracks; a second IoU stage uses lower-score boxes only for remaining currently tracked objects. Low-score unmatched boxes do not become new tracks. Lost tracks expire, duplicates are removed, and reactivated tracks may retain ID.

**Strength/relevance:** lower-confidence partial detections can preserve existing monster identity without creating low-confidence new targets. **Weakness:** box/score conventions need an adapter; neural confidence thresholds are not calibrated template scores. Per-frame assumptions and matching thresholds are not suitable defaults for irregular screenshot timing. No proof of Classic occlusion performance or safety.

## Deep SORT

**Stack/dependencies:** Python, NumPy, SciPy, OpenCV; appearance extraction requires a separately compatible embedding/model path. [tracker.py](https://github.com/nwojke/deep_sort/blob/f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab/deep_sort/tracker.py), [linear_assignment.py](https://github.com/nwojke/deep_sort/blob/f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab/deep_sort/linear_assignment.py), [nn_matching.py](https://github.com/nwojke/deep_sort/blob/f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab/deep_sort/nn_matching.py), [requirements](https://github.com/nwojke/deep_sort/blob/f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab/requirements.txt), [GPL license](https://github.com/nwojke/deep_sort/blob/f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab/LICENSE) were read.

**Verified:** `Tracker._match` uses appearance distances gated by Kalman distributions, a recency cascade for confirmed tracks, then IoU for unconfirmed/recent unmatched tracks. `NearestNeighborDistanceMetric.partial_fit` retains bounded feature histories for active identities when a budget is supplied.

**Strength/relevance:** explains why spatial proximity alone cannot guarantee identity after crossing. **Weakness:** visually identical sprites give appearance little separating power; pretrained human re-ID is not established for game sprites. Higher data/model maintenance and GPL review make this experimental, not a near-term dependency.

## python-mss

**Stack:** Python/ctypes platform capture, no detector. [GDI implementation](https://github.com/BoboTiG/python-mss/blob/6c00e6e9c735d4e65c8b72f2a732e463078a901e/src/mss/windows/gdi.py), [buffer helpers](https://github.com/BoboTiG/python-mss/blob/6c00e6e9c735d4e65c8b72f2a732e463078a901e/src/mss/buffer.py), [manifest](https://github.com/BoboTiG/python-mss/blob/6c00e6e9c735d4e65c8b72f2a732e463078a901e/pyproject.toml), [MIT license](https://github.com/BoboTiG/python-mss/blob/6c00e6e9c735d4e65c8b72f2a732e463078a901e/LICENSE.txt) were read.

**Verified:** `MSSImplGdi.grab` caches the DIB by dimensions, acquires/releases device contexts within each call, runs BitBlt/GdiFlush, and returns copied pixel data. **Strength/relevance:** same library family already used by our guarded capture wrapper. **Weakness:** current upstream HEAD is not proof of the implementation installed under our `mss>=10,<11` constraint. Display pixels remain subject to window/desktop conditions. Capture throughput cannot establish decision freshness or input effectiveness.

## DXcam

**Stack:** Python, NumPy, COM/DXGI, optional OpenCV/Cython and WinRT capture backend. [dxcam.py](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/dxcam/dxcam.py), [capture_loop.py](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/dxcam/core/capture_loop.py), [manifest](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/pyproject.toml), [MIT license](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/LICENSE) were read.

**Verified:** `CaptureLoopRunner.run_once` reserves/commits ring-buffer slots and retains source frame ticks; video mode may duplicate the previous frame. `DXCamera.get_latest_frame` exposes optional timestamps; `grab` distinguishes caller-owned copies and reused views, with different one-shot versus running-capture semantics.

**Strength/relevance:** latest-frame acquisition, source-age telemetry, explicit buffer ownership. **Weakness:** Windows/backend/display recovery complexity; a borrowed array can be overwritten. README throughput figures are author benchmarks on different hardware/workloads, not our measured performance. Benchmark an adapter only after capture is shown to dominate latency.

## py_trees

**Stack:** Python behaviour trees with pydot visualization dependency. [composites.py](https://github.com/splintered-reality/py_trees/blob/786859dcafc4ec9b78ff7ed0950b106c829d2174/py_trees/composites.py), [behaviour.py](https://github.com/splintered-reality/py_trees/blob/786859dcafc4ec9b78ff7ed0950b106c829d2174/py_trees/behaviour.py), [manifest](https://github.com/splintered-reality/py_trees/blob/786859dcafc4ec9b78ff7ed0950b106c829d2174/pyproject.toml), [license](https://github.com/splintered-reality/py_trees/blob/786859dcafc4ec9b78ff7ed0950b106c829d2174/LICENSE) were read. GitHub's license classifier returned NOASSERTION, but the actual text has the BSD three-clause terms and the manifest declares BSD-3-Clause.

**Verified:** `Selector.tick` invalidates lower-priority children after a priority switch; `Behaviour.stop` calls `terminate`; lifecycle transitions are explicit. **Strength/relevance:** auditable cancellation contracts. **Weakness:** tree invalidation does not physically release a key unless the leaf/controller implements it; a blocking leaf delays reevaluation. Our arbiter/controller already provides a simpler relevant boundary. No tree rewrite justified.

## Airtest

**Stack:** Python image-based UI/game testing; Pillow, NumPy, OpenCV-contrib, Windows pywinauto and platform-specific backends. Its inspected requirements pin NumPy below 2 and OpenCV at or below 4.6.0.66, incompatible with our declared NumPy 2/OpenCV 4.13 ranges.

**Read files:** [template_matching.py](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/aircv/template_matching.py), [core/cv.py](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/core/cv.py), [report.py](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/report/report.py), [requirements](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/requirements.txt), [Apache license](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/LICENSE).

**Verified:** normalized grayscale correlation optionally rechecks color; repeated result extraction suppresses the neighborhood around selected peaks. `Template._cv_match` tries configured matchers until success. `loop_find` has a timeout and logs screenshots. `LogToHtml._translate_step` binds screenshots, code, assertions, logs and traceback into one report record.

**Strength/relevance:** inspectable visual failure reports and staged matching. **Weakness:** this is GUI testing rather than continuous control; blocking polling and template match success do not establish game action effects. Importing the whole framework would duplicate working tools and introduce incompatible dependencies.

