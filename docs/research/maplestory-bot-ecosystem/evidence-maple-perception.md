# Maple perception source audit

Research date: 2026-11-01. Scope: public source and existing local source snapshots; no external code, model, executable, or gameplay run. See [repository catalog](repositories.md), [player tracking](player-tracking.md), and [monster detection](monster-detection.md).

## Acquisition and evidence rules

The five repositories below exist. GitHub repository metadata and the latest commit on each default branch were queried during this audit. Existing ignored checkouts in `artifacts/oss-bots/` have matching HEADs and clean working trees. Reading those files avoids downloading their bundled binaries/models. Dates below are default-branch commit timestamps, not push dates. Activity labels describe observed recency, not a maintainer's promise.

Four independent implementations were inspected deeply; the historical Auto-Maple fork received a focused source comparison and is not a fifth independent technique. Search queries included `github MapleStory bot nametag tracking occlusion Jeremyzzzzz` and `github MS Visionify auto maple computer vision`; related projects surfaced but were not counted here without source inspection. The broader catalog records other researchers' independently inspected projects.

## Verified snapshots and catalog entries

### tanjeffreyz/auto-maple

- URL: <https://github.com/tanjeffreyz/auto-maple>.
- Snapshot: [`5d88510e582784d6992ef72e8664e7df88d392ff`](https://github.com/tanjeffreyz/auto-maple/commit/5d88510e582784d6992ef72e8664e7df88d392ff), **2025-03-19T17:06:29Z**, `main`; GitHub archived=false. Latest commit edits README; quiet relative to this audit date.
- Stack/dependencies: Python, OpenCV, NumPy, MSS, keyboard, PyWin32, Tkinter GUI, TensorFlow for a separate rune subsystem; [requirements.txt](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/requirements.txt). Unpinned dependency set increases reproduction risk.
- License: no repository license file or general license grant found in the inspected tree/README. Public availability alone does not grant code-reuse permission. Study ideas; obtain permission before copying.
- Verified files/functions: [`Capture._main`](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/capture.py#L73), [`single_match`, `multi_match`, coordinate conversions](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/common/utils.py#L74). Corner templates calibrate minimap; player template threshold updates one shared position. A miss retains the previous position without an age flag.
- Strengths: small understandable minimap pipeline, separate capture thread, modular routine/command architecture.
- Weaknesses: minimap corner match has no acceptance threshold; player picks first threshold crossing, not best candidate; no full-screen sprite identity or occlusion tracker in the inspected path. README demonstration links were not replayed or independently validated.
- Relevance: good baseline illustrating the value of minimap independence from foreground occlusion; weaker uncertainty handling than our current bot. No reason to replace our existing localization with it.

### Jeremyzzzzz/MapleStoryAuto

- URL: <https://github.com/Jeremyzzzzz/MapleStoryAuto>.
- Snapshot: [`2a2d6c217328f2b32dd4e35b656ea00f32dac12c`](https://github.com/Jeremyzzzzz/MapleStoryAuto/commit/2a2d6c217328f2b32dd4e35b656ea00f32dac12c), **2026-09-12T11:46:37Z**, `main`; archived=false. Recent development, with extensive author-reported tuning comments. Those are not independent reliability measurements.
- Stack: Python/OpenCV/NumPy, Windows Graphics Capture, PySide6, PyAutoGUI/pynput, YAML, Ultralytics YOLO, optional OCR. [Base requirements](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/requirements.txt) do not list Ultralytics although the inspected detector imports it. The base file alone is not a complete environment specification.
- License: repository [MIT license](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/LICENSE); preserve its notice for permitted code reuse. This does not settle the separate rights for dependencies, base weights, fine-tuned models, or game artwork. [Trainer](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/train_small_yolo.py#L7) defaults to `yolo11n.pt`. [Ultralytics' published terms](https://www.ultralytics.com/license) offer AGPL-3.0 and enterprise licensing; resolve the intended use and model provenance before adoption. No blanket claim of MIT-covered weights is justified.
- Verified files/functions: [`DetectionTracker`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L780), [`_find_color_anchor`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1358), [player `detect`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2180), [`YoloMonsterDetector`](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2544), [screen/minimap regression and fallback](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7078).
- Strengths: actual full-screen player/monster implementation, identity-aware candidate selection, explicit tracking association, minimap bridging, classes/box filtering, custom training and evaluation scripts.
- Weaknesses: large tightly coupled scripts, many outfit/map-specific constants, frame-count expiry and per-frame velocity, approximate minimap regression across camera regimes, held estimates can be returned as detection dictionaries. No held-out Classic accuracy or latency was measured here.
- Relevance: strongest Maple-specific perception comparison in this group. Adopt evidence ideas selectively; do not transplant its color assumptions, long hold, or control permission semantics.

### Dashadower/MS-Visionify

- URL: <https://github.com/Dashadower/MS-Visionify>.
- Snapshot: [`a7e48c71005a577443d998fb1e8c0f4cbdb03ba7`](https://github.com/Dashadower/MS-Visionify/commit/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7), **2019-08-30T16:41:58Z**, `master`; **archived=true**.
- Stack: Python, PIL ImageGrab, OpenCV, NumPy, PyWin32, old TensorFlow/Keras; [requirements](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/requirements.txt) pin a 2019-era environment.
- License: [GPL v3 text, `LICENCE`](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/LICENCE). Adaptation/distribution must respect applicable GPL obligations; no source copied by this audit.
- Verified source: [`get_minimap_rect`, `find_player_minimap_marker`](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/screen_processor.py#L156), [`PlayerController.update`](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/player_controller.py#L100). Largest acceptable contour defines the minimap; narrow BGR mask and pairwise pixel-neighbor counting define marker position. Missing marker reuses old position.
- Strengths: explicit inspectable minimap geometry and operator-authored terrain approach.
- Weaknesses: fixed-color/scale assumptions, quadratic loop over marker-colored pixels, stale position reuse, old dependencies. Modern double-jump movement assumptions do not transfer directly to Classic.
- Relevance: historical comparison, particularly what to avoid; our connected-component marker extraction and bounded freshness are already preferable foundations.

### MapleStory-Archive/Auto-Maple

- URL: <https://github.com/MapleStory-Archive/Auto-Maple>.
- Snapshot: [`2e1bc871001ffbccca8add9e34d443437962f4e5`](https://github.com/MapleStory-Archive/Auto-Maple/commit/2e1bc871001ffbccca8add9e34d443437962f4e5), **2021-10-14T18:23:33Z**, `version-2`; archived=false despite the organization name. Historical fork; not an actively maintained independent algorithm.
- Stack: Python, MSS, NumPy, OpenCV, threading, TensorFlow elsewhere in tree. No requirements file in this old snapshot; imports were read in [`capture.py`](https://github.com/MapleStory-Archive/Auto-Maple/blob/2e1bc871001ffbccca8add9e34d443437962f4e5/capture.py#L1).
- License: no license grant found; do not assume the fork adds reuse permission.
- Focused source verification: [`Capture._main`](https://github.com/MapleStory-Archive/Auto-Maple/blob/2e1bc871001ffbccca8add9e34d443437962f4e5/capture.py#L35) grabs a configured monitor, calibrates a minimap corner, holds last player coordinates on miss, and draws route/position overlays. Source lives at repository root, **not** upstream's later `src/modules/` path.
- Strength: inspectable historical visualization and minimap baseline. Weakness: same stale-state problem, older assumptions, no independent occlusion evidence. Relevance: lineage only; not counted as a second corroborating solution.

### angusshire/msbot

- URL: <https://github.com/angusshire/msbot>.
- Snapshot: [`5d111b1330756fd72121ed39c60abb2757ab6f92`](https://github.com/angusshire/msbot/commit/5d111b1330756fd72121ed39c60abb2757ab6f92), **2015-03-26T19:08:31Z**, `master`; archived=false. Long inactive.
- Stack: C++, Win32/GDI bitmap access, custom `Image`/`Pixel` classes; no OpenCV in inspected recognition path. [`Image.h`](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/Image.h), [`MSBot.h`](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.h).
- License: [GPL v3, `LICENSE.txt`](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/LICENSE.txt), also explicit file headers.
- Verified source: [`initializeMinimapFields`, `characterSpotted`, dimensions](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L685). Nested full-image scans match minimap UI; exact red pixels identify other-player presence. That is **not** self-character detection, monster detection, or persistent tracking.
- Strength: transparent minimal pixel implementation. Weakness: brittle exact colors/UI imagery, repeated scans, no identity/confidence model. Relevance: low; useful negative baseline and reminder not to infer advanced perception from a bot label.

## Relationship to earlier research

[Existing OSS notes](../../oss-bot-research.md) remain unchanged. This audit verifies matching source snapshots and adds latest commit/archival details, narrower evidence classifications, and current-code comparisons. It avoids treating the historical fork as independent corroboration, avoids treating README demonstrations as measured validation, and separates a repository's license from model/dependency terms.

For recommendations in this directory, this audit supersedes unmeasured microsecond, `0.1 ms`, or multiplicative speed estimates in that older note. No external implementation was benchmarked here. YOLO supports different devices; whether this workload is GPU-bound, CPU-bound, or faster than the existing detector must be measured. The MIT notice and Ultralytics' separate published terms are recorded above; they do not justify an automatic conclusion about every bundled artifact or a particular distribution's legal compatibility.
