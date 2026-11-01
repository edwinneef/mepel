# Source audit: navigation and combat repositories

Research date: 2026-11-01. Seven public repositories verified through GitHub repository metadata, default-branch commit endpoints, recursive source trees and source-file reads. Five received deep control-flow inspection (easymaple, D4MXD, LinPolly, sychen6192, TinForge); MapleController and rune-breaker received focused source inspection. No external code, tests, weights or binaries were executed or installed. Commit dates below are **default-branch tip committer dates**, not `pushed_at` or star/update dates. Activity is a dated observation, not a promise of support.

## Snapshot register

| Repository | Tip SHA | Tip date UTC | Status | License inspection |
| --- | --- | --- | --- | --- |
| [wanliAlex/easymaple](https://github.com/wanliAlex/easymaple) | `af23f1d44e1e3adfe237c7612464f4dfc99362d3` | 2026-06-28T12:28:09Z | Unarchived; recent 2026 changes | No root license found in tree; `resources/LICENSE` is MIT, scoped to that material rather than assumed to license all source |
| [neiamo/D4MXD](https://github.com/neiamo/D4MXD) | `e50471e95028ba7c87cb4346d21a8c8954b0160f` | 2026-04-09T10:15:57Z | Unarchived; experimental toolkit | No LICENSE/COPYING/NOTICE path found; reuse permission unverified |
| [tomerh2001/MapleController](https://github.com/tomerh2001/MapleController) | `e0dbdca616cd56fcf242bcd1f6390b77de1f45e5` | 2021-02-02T10:44:58Z | Archived, long inactive | No license path found; reuse permission unverified |
| [gbrlfaria/rune-breaker](https://github.com/gbrlfaria/rune-breaker) | `2505556a785632b2ec8699e0433930d21bdfe88a` | 2020-07-24T13:07:03Z | Unarchived; default `revamp` branch long inactive | MIT LICENSE read |
| [LinPolly/MapleStoryAutoLevelUp](https://github.com/LinPolly/MapleStoryAutoLevelUp) | `3e19173f8da5aab8405307bb9c6e3741dd3abd6b` | 2025-12-06T12:02:53Z | Unarchived Artale lineage; no later default tip observed | MIT LICENSE read |
| [sychen6192/maplebot](https://github.com/sychen6192/maplebot) | `320234a21e90c0ee3a811ede71585a1ef627efc9` | 2026-10-12T12:02:33Z | Unarchived; recently changed Classic research bot | No license path found; reuse permission unverified |
| [TinForge/MS-ML-Bot](https://github.com/TinForge/MS-ML-Bot) | `9a3e148b328916d6eff25145b76a49f27135c84e` | 2024-06-18T02:31:56Z | Unarchived; inactive experimental bot | Unlicense text read; YOLO/PyTorch/dependency and weight rights remain separate |

Metadata can be refreshed at `https://api.github.com/repos/OWNER/REPO` and `/commits/DEFAULT_BRANCH`. All source links below pin the inspected snapshot. Absence of a root license is not a grant to copy code; these projects still provide inspectable algorithmic ideas. License observations are engineering reuse triage, not legal clearance.

## easymaple

Python, OpenCV, MSS, NumPy, Tkinter GUI and class command books; the [dependency manifest](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/pyproject.toml) additionally includes PyTorch, torchvision, timm, OCR and several input libraries. Its [resources license](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/resources/LICENSE) is MIT.

Source inspected:

- [layout.py, `Node`, `Layout.add/search/shortest_path`](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/src/easymaple/routine/layout.py): spatial tree of observed points; heap search ranks accumulated Euclidean distance plus target distance. Neighbor selection keeps the closest candidate within directional teleport search regions. Empty fringe breaks, but returned path still includes the requested target. It is not a proof that the target is reachable.
- [components.py, `Move.main`, `Point.main`](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/src/easymaple/routine/components.py): one path computed at command start; subsequent steps use updated player coordinates and an action counter. `Point` invokes its attached commands without an explicit successful-arrival result.
- [capture.py, `Capture._main`](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/src/easymaple/modules/capture.py): minimap crop, template localization, cached window object and rolling capture-FPS timestamps. Missing player matches leave previous global player coordinates unchanged in this loop.

Strength: compact map teaching and per-class command separation. Weakness: teleport-centric topology, global mutable state and stale-location ambiguity. Relevance: useful interface ideas; lower safety than our explicit route/outcome contracts. No native performance or reliability verified here.

## D4MXD

Python/OpenCV/NumPy/Win32 toolkit with MapleStory and Path of Exile 2 folders. The [README](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/README.md) places A* in the **POE2** subsystem; do not attribute it to MapleStory. Its [Maple requirements](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/requirements.txt) list OpenCV-contrib, NumPy and pywin32, while demo imports additionally require Ultralytics.

Source inspected:

- [minimap.py, `find_yellow_dot`](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/minimap.py#L25): HSV masks, morphological opening, contour area/circularity and distance continuity. Last known marker is returned on missing contours when confidence exceeds three; those missing-data branches do not decay the confidence or attach age. `detect_minimap_dynamic` uses Canny/contour rectangle heuristics. `get_nearest_color_code` follows route colors.
- [actions.py, `press_key`, `move_target`](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/actions.py): timed key-down/sleep/key-up; rope sequence returns true after issuing keys, without observed attachment/arrival. No `finally` release around a failing delay or key call.
- [capture.py, `capture_window`](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/capture.py): PrintWindow followed by BitBlt fallback and DC/bitmap cleanup. Capture validity still requires empirical black-frame/staleness checks.
- [demo.py, `keyboard_worker`](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/demo.py): separate HP/attack/misc/movement queues, sentinel closure and randomized weighted non-HP selection. Docstring says 60/20/20, actual weights are 70/20/10. Imports use `final.*` despite this file residing under `maple_v2`; the recursive tree has no matching root `final` package. This is a static integration concern; execution was not attempted.

Strength: transparent small CV routines, marker candidate diagnostics and capture fallback. Weakness: stale evidence retention, timing-only movement acknowledgement and packaging/dependency inconsistencies. Relevance: proposal generation and diagnostics only; no reason to replace our scheduler or gates. README optimization reports were not accepted as measurements.

## MapleController

Python/OpenCV/Pillow/NumPy/keyboard-style automation organized through controller inheritance. [README](https://github.com/tomerh2001/MapleController/blob/e0dbdca616cd56fcf242bcd1f6390b77de1f45e5/README.md) functionality is author-described, not reproduced. No standard top-level dependency lock/manifest or license was found in the inspected source tree.

Inspected [MovementController.py](https://github.com/tomerh2001/MapleController/blob/e0dbdca616cd56fcf242bcd1f6390b77de1f45e5/Controller/Controllers/MovementController.py), [PlayerController.py](https://github.com/tomerh2001/MapleController/blob/e0dbdca616cd56fcf242bcd1f6390b77de1f45e5/Controller/Controllers/PlayerController.py), [BaseController.py](https://github.com/tomerh2001/MapleController/blob/e0dbdca616cd56fcf242bcd1f6390b77de1f45e5/Controller/Controllers/BaseController.py) and [MapleState.py](https://github.com/tomerh2001/MapleController/blob/e0dbdca616cd56fcf242bcd1f6390b77de1f45e5/Controller/MapleState.py).

`get_smart_direction` steers toward a central minimap band, but chooses a random direction when player recognition throws. `PlayerController.attack` repeats configured attacks with sleeps, and `use_uncooldowned_skills` uses cooldown bookkeeping. Rune reaching uses timed axis loops; no general platform graph was established in these paths. Strength: movement/skills/potions separation and frame retention. Weakness: recognition failure can produce movement, inherited shared state, no confirmed damage feedback in inspected attack path. Relevance: historical design comparison, not a controller to adopt.

## rune-breaker

Python image-classification/data-preparation project; **not a navigation or combat bot**. [MIT license](https://github.com/gbrlfaria/rune-breaker/blob/2505556a785632b2ec8699e0433930d21bdfe88a/LICENSE) and [requirements](https://github.com/gbrlfaria/rune-breaker/blob/2505556a785632b2ec8699e0433930d21bdfe88a/requirements.txt) inspected: old Keras/TensorFlow, OpenCV, scikit-image, NumPy, pandas and matplotlib versions.

Inspected [preprocessing/preprocess.py](https://github.com/gbrlfaria/rune-breaker/blob/2505556a785632b2ec8699e0433930d21bdfe88a/preprocessing/preprocess.py) and [common.py](https://github.com/gbrlfaria/rune-breaker/blob/2505556a785632b2ec8699e0433930d21bdfe88a/common.py). `process_arrow` applies Gaussian blur, weighted HSV transform, adaptive threshold, small-object/hole removal and centroid-based crop; `compute_arrow_centroid` scores contours via convex hull/ellipse shape. `common.py` defines separate training/validation/testing directory conventions. No trained model or notebook executed; classification accuracy unverified.

Strength: explicit preprocessing stages and separated dataset partitions. Weakness: arrow-specific shape assumptions and obsolete dependencies; no player/monster tracker or hit model established. Relevance: offline ablation and annotation workflow ideas only. Rune challenge solving itself is outside our recommended scope.

## LinPolly/MapleStoryAutoLevelUp

Python Artale bot using OpenCV, NumPy, PySide6, pynput, capture/input libraries and YAML. [MIT license](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/LICENSE) and [requirements](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/requirements.txt) read. This follows the KenYu910645 Artale lineage; related Jeremyzzzzz code is not independent corroboration.

Inspected [MapleStoryAutoLevelUp.py](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py) and [KeyBoardController.py](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/input/KeyBoardController.py), plus preserved prior [movement audit](../../movement-bot-research.md).

`update_cmd_by_route` merges nearest action-colored route pixels; `is_on_ladder` is inferred from tiny horizontal and nonzero vertical screen displacement. `update_cmd_by_mob_detection` applies directional/AOE search ranges and cooldowns, then requests attack direction. It does not establish damage. `update_cmd_by_random` chooses fallback movement. `run_once` has stage profiling, optional recording and visualization; absent successful localization can leave stored coordinates unchanged. Strength: practical spatial route authoring, integrated profiler and debug views. Weakness: camera-sensitive ladder heuristic, stale-state risk and random recovery. Relevance: route authoring and stage observability; preserve our stronger map/proof/stop contracts.

## sychen6192/maplebot

Python Classic screenshot bot, OpenCV/MSS/NumPy/YAML; optional Ultralytics. [pyproject.toml](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/pyproject.toml) and [requirements](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/requirements.txt) read. No copying without confirmed permission.

Source inspected:

- [brain/fsm.py](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/brain/fsm.py): typed intent classes and `decide`; `_climb` uses observed minimap-y progress, retries and failure limits; `_check_stuck` counts consecutive patrol observations, resetting after an observation gap; `_attack_stalled` uses prolonged immobility as a heuristic, not hit evidence.
- [recording/route.py, `compress`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/recording/route.py): compresses observations at horizontal reversals and settled level transitions, preserving special keys as waypoint annotations.
- [vision/minimap_scroll.py, `MinimapScroll.update`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/vision/minimap_scroll.py): blanks moving dots before Hann-window phase correlation; rejects low response/large shift and resets origin. Reset creates a new coordinate basis, which downstream geometry must recognize.
- [vision/track.py, `PointTracker`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/vision/track.py): nearest plausible point, jump bound, bounded coast count and decay-like confidence; no Kalman model.
- [vision/mob_hpbar.py](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/vision/mob_hpbar.py): colored rectangular connected components infer mob proposals below HP bars; IoU merge avoids some duplicate proposals. It does not measure damage amounts.
- [vision/outline_mobs.py](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/vision/outline_mobs.py): dark masks, morphological closing and component filters. It is class-agnostic and susceptible to foreground/UI/pet/player confusion.

Strength: inspectable small modules, explicit intent types, meaningful retry limits and trace compression. Weakness: route/model assumptions still need map validation; morphology can merge targets; author-comment performance anecdotes lack independently inspected datasets. Relevance: high for offline failure taxonomy, acquisition freshness and route teaching, not a wholesale replacement.

## TinForge/MS-ML-Bot

Python YOLOv5/Torch/Pillow/Tkinter/Win32 experiment. [Unlicense](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/LICENSE) and [requirements](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/requirements.txt) read; requirements include CUDA Torch builds and Ultralytics. Its own license does not settle fetched YOLO code or model provenance.

Inspected [yolov5/model.py](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/yolov5/model.py), [process/detection.py](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/process/detection.py), [data/trackers.py](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/data/trackers.py), [process/calculations.py](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/process/calculations.py) and [process/bot.py](https://github.com/TinForge/MS-ML-Bot/blob/9a3e148b328916d6eff25145b76a49f27135c84e/process/bot.py).

`Model` fetches YOLOv5 through unpinned `torch.hub.load`, selects CUDA if present, and maps detections to Platform/Ladder/Player and five monster species. `DetectionThread.process` associates by class, nearest centroid and relative box area; no one-to-one assignment is enforced. `Tracker` confirms after repeated sightings and expires after missed frames. **Negative finding:** `add` caps history at `cache_size`, while `extrapolated_average` returns the ordinary average whenever length is `<= cache_size`, so its velocity branch is unreachable in normal use. The code that publishes smoothed/extrapolated rectangles is also commented out. Do not call this a functioning predictive tracker.

`BotThread.calculate` attacks by profile distance/height. The minimum-range retreat branch follows the broader `< max_range` branch and cannot handle ordinary `min_range < max_range` too-close targets. Strength: concrete joint player/mob/platform detection and debug overlays. Weakness: incomplete tracking integration, range branching bug, unpinned model fetch and shared mutable state. Relevance: useful negative examples and dataset-class design; no measured improvement over current templates established.

## Discovery boundaries

Searches covered Artale/OpenCV, Classic screenshot bots and v62/v83 screenshot automation. The Artale KenYu upstream, Classic `itechify/minerva` and `boggioMichael/ms`, and v62 `angusshire/msbot` were discovery leads; this slice does not count them as newly source-audited repositories. Server bots and packet/headless vacuum projects surfaced by v62/v83 searches were excluded from recommendations because their observation/action model is outside screenshot-only scope. Availability of source does not establish current gameplay compatibility.

See [navigation](navigation.md), [combat](combat.md), [repository catalog](repositories.md) and [open questions](open-questions.md).
