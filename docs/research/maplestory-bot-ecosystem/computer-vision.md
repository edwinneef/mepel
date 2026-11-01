# Computer vision: implementation comparison

Research date: 2026-11-01. Baseline: local source at `630d7ad0c3ab30f0fb7042710f8817792c45ec46`. Source reading establishes algorithms, not native-game accuracy. No benchmark was run for this audit.

[Index](README.md) · [player tracking](player-tracking.md) · [monster detection](monster-detection.md) · [performance](performance.md) · [source snapshots and licenses](evidence-general-systems.md)

## Existing pipeline to preserve

The project is a Python/NumPy/OpenCV screenshot engine with a React/TypeScript interface. [TemplateDetector](../../../src/maplebot/perception.py) already has grayscale/color template scoring, masked sprite signatures, grouped candidate processing, nametag/text overlap, local search followed by expanded/full search, partial nametag evidence, camera prediction, and a persistent [EnemyTracker](../../../src/maplebot/enemy_tracking.py). Template identity and confirmed/tracked status are different concepts.

[CameraTracker.update](../../../src/maplebot/perception.py) uses half-size phase correlation; [feature_translation](../../../src/maplebot/camera_motion.py) verifies sparse forward/backward optical flow, rejects poorly distributed motion, masks HUD regions, and accepts translation only with substantial agreeing support. [tests/test_camera_motion.py](../../../tests/test_camera_motion.py) covers unrelated images, flat scenes, a single moving actor, large low-frame-rate scroll, and stationary drift. This functionality is implemented; it is not an external feature gap.

[TemplateDetector.detect](../../../src/maplebot/perception.py) already filters active templates by map, supports player-only detection, and uses a thread pool. A proposal merely to add ROI, threading, camera compensation, or tracking would duplicate existing functionality.

## Recognition choices

Costs below are **qualitative estimates**, conditional on resolution, template count, ROI area and hardware. Accuracy is a failure-mode assessment, not a measured ranking.

| Technique | Source evidence / local status | Reliability and accuracy boundary | Cost and complexity | Recommendation |
| --- | --- | --- | --- | --- |
| Normalized grayscale correlation | Local `_template_candidates`; Airtest `_get_template_result_matrix` uses TM_CCOEFF_NORMED | Good for known rendering/scale; background resemblance, animation and lost pixels can break a high score | CPU; work grows with search area and templates; low operational complexity | Keep as baseline; calibrate scores per evidence type |
| Color verification / HSV masks | Local `_color_where_possible`, sprite color signatures; Maple examples in [player tracking](player-tracking.md) | Useful cheap candidate rejection; lighting, transparency, cosmetics and similar UI colors can confuse it | CPU, inexpensive per pixel; thresholds require versioned fixtures | Combine with geometry/identity; avoid global color-only identity |
| Alpha/masked template fragments | Local `masked_score`, `_occluded_tag_score`, `partial_enemies` | Helps partial visibility; fewer pixels also make accidental matches more likely | CPU; candidate-local evaluation preferred | Require minimum visible support and association to an established identity |
| Multi-scale matching | Airtest `Template._cv_match` dispatches configured multi-scale matchers and supplies recorded resolution | Useful for genuine scale changes; cannot make an unknown animation equivalent | More candidate evaluations and more false-positive opportunities | Current size/DPI calibration remains primary; only test bounded scales when evidence demands it |
| Local keypoint matching | Airtest matcher dispatch and predicted-area helper; local LK camera tracker | Useful on textured terrain; tiny repeated sprites may supply too few distinctive features | Medium CPU/complexity; matcher dependencies vary | Prefer for terrain/camera validation, not blanket sprite replacement |
| Edge/contour geometry | Local map/structure work, discussed in [navigation](navigation.md) | Can identify bars/ropes/platform-looking boundaries; decorative edges are not collision surfaces | Low–medium CPU; labeling/geometry validation required | Candidate evidence only; compare against imported map geometry |
| Frame differencing / background subtraction | Candidate research technique, **no selected external implementation was deep-inspected here** | Camera motion, blinking HUD, particles and attack effects confound foreground masks | Low CPU for differences, higher if registration required | Use for change-triggered expensive work or debug proposals; not actor identity |
| Learned object detector | MapleStoryAuto source inspection in [monster detection](monster-detection.md); ByteTrack integrates detector outputs | Can cover animation variation if training data is representative; partial/overlapping sprites remain dataset-dependent | Model/training/model-license burden; CPU/GPU cost must be measured | Experimental alternative after held-out labels, with current templates as baseline |
| OCR | Current WinRT OCR dependency and existing map/title/nametag context | Text resolution and occlusion constrain recognition; OCR output can jump between similar names | Separate cadence/ROI desirable; actual cost unmeasured | Seed identity or classify stable labels; avoid full-frame OCR per action |

Airtest's inspected [template matcher](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/aircv/template_matching.py#L35) chooses correlation peaks and optionally recalculates color confidence. Its [strategy dispatcher](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/core/cv.py#L167) confirms a staged-matcher pattern, not proof that every configured technique improves Maple screenshots.

## Temporal trackers are complementary to detectors

A tracker needs measurements. It cannot prove the position or identity of an actor hidden by an opaque bridge indefinitely.

| Approach | Inspected control flow | Strength | Failure / integration cost | Maturity and license |
| --- | --- | --- | --- | --- |
| Existing heuristic prediction | `TemplateDetector._predict/_learn_motion`; `EnemyTracker.prepare/update` | Already integrated with geometry and evidence gates | Evaluate uncertainty and crossing/occlusion cases before changing model | Local code and tests; native acceptance separate |
| Alpha-beta filter | Candidate mathematical baseline; **not claimed as an inspected external implementation** | Small state, elapsed-time velocity smoothing, easy ablation | Requires tuned gains; no automatic identity/recovery semantics or covariance | Experiment only, independently implemented if selected |
| SORT | [KalmanBoxTracker and association](https://github.com/abewley/sort/blob/2236dff5019565958b84df7d871d41cc1db58ac7/sort.py#L94) | Explicit constant-velocity state, IoU assignment and track age | Per-frame model, box-size changes and camera scroll; no appearance re-ID | Established source reference; GPL-3.0 |
| Norfair | [TrackedObject.hit](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/tracker.py#L615), [optimized filter](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/filter.py#L148) | Independently observed points, configurable distance and re-ID, optimized covariance representation | Greedy association; points must mean stable body anchors; NumPy dependency conflict if imported wholesale | Mature generic library; BSD-3-Clause |
| ByteTrack-style two-stage association | [BYTETracker.update](https://github.com/FoundationVision/ByteTrack/blob/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/yolox/tracker/byte_tracker.py#L159) | Uses weak boxes to maintain existing tracks without creating weak new tracks | Neural confidence thresholds cannot transfer to template scores; same-species overlap ambiguity | Established reference implementation; MIT |
| Deep SORT appearance cascade | [Tracker._match](https://github.com/nwojke/deep_sort/blob/f08cf1dc470eeb1cd2add1cbf077d95ac6c48aab/deep_sort/tracker.py#L93) | Appearance plus uncertainty gating, recency-aware association | Needs game-specific features/model validation; identical animated sprites may be indistinguishable | Established reference; GPL-3.0; model terms separate |

**Important distinctions:** Norfair uses greedy minimum-distance association, not Hungarian assignment. SORT retains stale internal tracks but normally returns only tracks updated in the present frame. ByteTrack's second stage uses remaining currently tracked objects and low-score boxes; it does not create a new target for every weak detection. Preserve these distinctions when designing a local experiment.

## Camera and coordinate frames

Norfair's [sparse-flow implementation](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/camera_motion.py#L262) uses goodFeaturesToTrack and Lucas–Kanade flow. The project's own flow check additionally requires reverse-flow agreement and spatial spread. Copying the library's routine would discard safeguards without measured benefit.

Keep three quantities separate: screen displacement, estimated camera translation, and world displacement. Add camera uncertainty to motion/association uncertainty instead of treating a low-confidence camera estimate as exact compensation. Minimap displacement can cross-check a hypothesis; it does not resolve pixel-exact player feet at coarse marker quantization. See [player tracking](player-tracking.md) and [navigation](navigation.md).

A full homography is more general than translation but usually adds unnecessary freedom for a scrolling 2D game. Compare translation residuals on recorded scenes before adopting it. Camera cuts, map transitions and layout changes should invalidate track history rather than fit a flexible transform to unrelated scenes.

## Confidence calibration and uncertainty

Current thresholds encode engineering decisions; a correlation of 0.9 is not a 90% probability of correct identity. Separate full-sprite, partial-sprite, nametag, minimap, and coasted-position outcomes in evaluation.

A proposed calibration dataset should contain independent identity/box labels, visibility flags, map and camera state, and false-positive distractors. Split by recording/session rather than adjacent random frames. For each evidence class report false confirmations, missed detections, identity switches, false resumes, position error where labelable, and time to recover. Explicitly label unobservable full-occlusion positions as intervals/unknown instead of deriving truth from the tracker being evaluated.

Low-confidence detections can help *association* while remaining insufficient for *gameplay authorization*. This is the strongest transferable ByteTrack lesson. Lowering the global detection threshold would merge those distinct decisions and increase false-action risk.

## Practical sequence

1. Extend existing replay evaluation with held-out independent labels and evidence-stratified results; see the single selected milestone in [backlog](improvement-backlog.md).
2. Compare current prediction with one elapsed-time filter and current association with one two-stage association variant, changing only one variable per experiment.
3. Keep map geometry, camera validation, freshness checks and action gates identical across comparisons.
4. Consider a small learned detector only if labeled failures show animation coverage that templates cannot handle within the latency budget.

No external repository supplies evidence sufficient to replace the local detector, tracker, camera estimator, or input controller as a complete system.

