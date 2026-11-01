# Open-source MapleStory bot research: tracking, perception and recovery — 2026-11-01

Scope: source reading only. Each repository was shallow-cloned into its own folder under
`artifacts/oss-bots/` (ignored by Git). None of their code, models or executables was run.
This note extends [movement-bot-research.md](movement-bot-research.md). That note already
covers Auto Maple's `Move`/`Adjust`/`Fall`/`Point` and command books, plus the
MapleStoryAutoLevelUp route, ladder and stuck watchdog code, so those are not repeated here.
No project code was changed.

## Source snapshots and licenses

| Repository | Commit | Language | License | Reuse |
|---|---|---|---|---|
| [tanjeffreyz/auto-maple](https://github.com/tanjeffreyz/auto-maple) | `5d88510e582784d6992ef72e8664e7df88d392ff` | Python | None (no LICENSE file or notice) | All rights reserved: ideas only |
| [MapleStory-Archive/Auto-Maple](https://github.com/MapleStory-Archive/Auto-Maple) | `2e1bc871001ffbccca8add9e34d443437962f4e5` | Python | None | Duplicate (see below) |
| [Jeremyzzzzz/MapleStoryAuto](https://github.com/Jeremyzzzzz/MapleStoryAuto) | `2a2d6c217328f2b32dd4e35b656ea00f32dac12c` | Python | MIT, "Copyright (c) 2025 Ken Yu" ([LICENSE](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/LICENSE#L1-L3)) | Code MIT; the bundled YOLO weights are AGPL-3.0 (see below) |
| [Dashadower/MS-Visionify](https://github.com/Dashadower/MS-Visionify) | `a7e48c71005a577443d998fb1e8c0f4cbdb03ba7` | Python | GPL-3.0 ([LICENCE](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/LICENCE#L1-L2)) | Ideas only; no code in this non-GPL project |
| [angusshire/msbot](https://github.com/angusshire/msbot) | `5d111b1330756fd72121ed39c60abb2757ab6f92` | C++ | GPL-3.0 ([README](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/README.md#L22-L23)) | Ideas only |

**Duplicate check.** GitHub lists MapleStory-Archive/Auto-Maple as a fork of
tanjeffreyz/auto-maple, last pushed 2021-11-04. Comparing its HEAD with upstream gives
`behind_by: 0, ahead_by: 203`: its HEAD is an ancestor of upstream `5d88510`, with no commits
of its own. It was cloned for this check but not researched separately. Everything below for
Auto Maple uses the upstream snapshot.

**Jeremyzzzzz/MapleStoryAuto weights.** Three `training_runs/*/weights/best.pt` Ultralytics
checkpoints are trained from `yolo11n.pt`/`yolo26n.pt`
([trainer](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/train_small_yolo.py#L12)).
Ultralytics and its base weights are AGPL-3.0 unless an enterprise license is held. The
repository does not mention this. Its `src/engine/MapleStoryAutoLevelUp.py` is the upstream
KenYu910645 engine, the same lineage as the LinPolly fork in the movement note. The live bot
is `tools/auto_combat.py` (9150 lines) with detectors in `tools/yolo_monster_viewer.py`. Most
comments are in Chinese and cite 2026-09 user requests; they are the author's claims, not
measurements.

## Findings by topic

### Player localization and identity

- **Auto Maple uses only the minimap.** Each frame, a 10×10 grayscale player template is
  matched inside the minimap crop (`TM_CCOEFF_NORMED` ≥ 0.8). It takes the *first* point over
  the threshold in `np.where` order, not the best score
  ([capture.py#L119-L125](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/capture.py#L119-L125),
  [utils.py#L91-L111](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/common/utils.py#L91-L111)).
  Both axes are normalized by minimap width
  ([utils.py#L114-L141](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/common/utils.py#L114-L141)).
  The character on the main screen is never located. Other-player red dots feed only an alert
  ([notifier.py#L21-L26](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/notifier.py#L21-L26)).
- **MS-Visionify also uses only the minimap.** It accepts BGR (68,221,255) ±1, and keeps a
  pixel only if 10–13 matching pixels lie within 3 px of it (the dot has 12 pixels). This is
  an O(n²) Python loop
  ([screen_processor.py#L193-L237](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/screen_processor.py#L193-L237)).
- **MapleStoryAuto locates the on-screen player without YOLO**, despite a `player_yolo_model`
  config key that no code reads. The live chain is: an OCR-seeded anchor, then a blue title-strip
  "color anchor", then a short hold, then name-tag templates
  ([yolo_monster_viewer.py#L2180-L2241](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2180-L2241)).
  The strip is HSV (90,80,50)–(135,255,255). A 21×3 horizontal close bridges cuts made by a
  pet or rope, and a red-fraction check of at least 0.02 in the inferred body rejects blue UI
  ([L1358-L1410](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1358-L1410)).
  To tell its own character from others, it keeps name-glyph candidates within 0.02 of the best
  raw score, falling back to a radius around the prediction
  ([L1620-L1677](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1620-L1677)).
  It also vetoes screen-x zones implied by other players' red minimap dots
  ([auto_combat.py#L6807-L6911](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L6807-L6911)).
- **msbot never locates its own character.** It scans for exact red (238) other-player dots to
  change channel
  ([MSBot.cpp#L713-L727](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L713-L727)).

### Occlusion and missed detections

- **Auto Maple** keeps `config.player_pos` silently when the template misses, with no age or
  stale flag ([capture.py#L122-L125](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/capture.py#L122-L125)).
  The minimap is a UI overlay, so monsters never cover it.
- **MS-Visionify** does the same: a missed dot keeps the previous x,y
  ([player_controller.py#L100-L116](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/player_controller.py#L100-L116)).
  A walk is capped at ceil(distance/15) seconds, so a lost marker cannot hold a key forever
  ([L245-L260](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/player_controller.py#L245-L260)).
- **MapleStoryAuto** has three layers:
  1. A 6-frame color-anchor hold
     ([L2229-L2236](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2229-L2236)).
  2. A constant-velocity `DetectionTracker`. Each missed frame multiplies velocity by 0.80 and
     confidence by 0.90, and the track expires after `max_missed`
     ([L1008-L1022](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1008-L1022)).
     The player uses 40 frames and smoothing 0.55
     ([auto_combat.py#L6712-L6713](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L6712-L6713)).
  3. **Minimap-anchored dead reckoning.** On real detections it fits screen ≈ k·minimap + b by
     least squares over the last 30 samples, on each axis
     ([L7078-L7100](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7078-L7100)).
     On a hold or miss, it moves the box to the screen position mapped from the current
     minimap dot. Without a fit, it uses Δminimap × frame size × 1.2
     ([L7153-L7177](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7153-L7177)).
  The estimated box is presented like a detection. A teleport-reject gate exists but is off by
  default; the author's comment says it locked onto a wrong estimate
  ([L7051](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7051)).
  A Kalman filter is not present.
- **msbot** has no tracking. A missing minimap leaves the stale rectangle in use
  ([MSBot.cpp#L709-L710](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L709-L710)).

### Minimap and camera

- **Auto Maple** locates the minimap once at calibration, using two corner templates with
  unnormalized `TM_CCOEFF` and no threshold, so it always returns *some* location
  ([capture.py#L90-L107](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/capture.py#L90-L107)).
  It recalibrates only when the bot is enabled or the routine is reloaded, not when the map
  changes ([listener.py#L70-L103](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/listener.py#L70-L103)).
  It has no screen↔minimap mapping and no camera model.
- **MS-Visionify** finds the largest Canny contour in a fixed area and caches it for the whole
  run ([screen_processor.py#L117-L184](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/screen_processor.py#L117-L184)).
  It has no camera model.
- **MapleStoryAuto** fits a piecewise camera model per map: a linear segment near each map
  edge, where the camera clamps, and a middle band where the player stays near screen centre
  ([auto_combat.py#L6123-L6202](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L6123-L6202),
  [config#L286-L310](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/config/config_shanda_legacy.yaml#L286-L310)).
  It estimates world width from |Δscreen|/|Δminimap| over still frames
  ([L7111-L7150](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7111-L7150)).
  Minimap dots are connected components of 3–24 px, and red dots must be confirmed over 2
  frames ([yolo_monster_viewer.py#L314-L373](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L314-L373),
  [L469-L523](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L469-L523)).
- **msbot** re-finds the minimap on every tick from its header, world button and bottom
  templates, and caches nothing
  ([MSBot.cpp#L688-L752](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L688-L752)).

### Monster detection and attack positioning

- **Auto Maple, MS-Visionify and msbot all attack blind.** Auto Maple runs routine commands at
  each `Point`
  ([components.py#L77-L88](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/components.py#L77-L88)).
  MS-Visionify sweeps the platform, casting every ~26 minimap px with random skills
  ([player_controller.py#L140-L243](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/player_controller.py#L140-L243)).
  msbot posts CTRL every loop
  ([MSBot.cpp#L276-L278](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L276-L278)).
  The only "enemy" vision in Auto Maple is an elite-boss alarm template
  ([notifier.py#L73-L77](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/notifier.py#L73-L77)).
- **MapleStoryAuto** uses Ultralytics YOLO at imgsz 640 on the GPU, with confidence 0.07
  ([yolo_monster_viewer.py#L2544-L2622](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L2544-L2622),
  [config#L395](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/config/config_shanda_legacy.yaml#L395)).
  A track counts after 2 hits or confidence ≥ 0.75
  ([auto_combat.py#L7261-L7263](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7261-L7263)).
  Targets must be in front of the player; it picks the nearest by Euclidean distance, prefers
  monsters with an HP bar, and turns after 1.2 s with nothing in front
  ([live_perception_viewer.py#L833-L880](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/live_perception_viewer.py#L833-L880)).
  Ranges are set per profile (horizontal/vertical/keep-distance, for example 135/70/60), and
  it does not attack while player confidence is below 0.9
  ([config#L426-L464](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/config/config_shanda_legacy.yaml#L426-L464),
  [auto_combat.py#L251-L252](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L251-L252)).
  Monster tracks reuse the same decaying `DetectionTracker` as the player.

### Platform, ladder and rope navigation (new material only)

- **Auto Maple layout.** A quadtree stores positions actually stood on during `Move`, skipping
  points within 0.05 of an existing one
  ([layout.py#L64-L108](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/layout.py#L64-L108)).
  An A*-like search with no stored edges pushes the best candidate in a horizontal window and
  a vertical window, and stops within 0.1 of the target
  ([layout.py#L141-L236](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/layout.py#L141-L236)).
  Reachability is inferred from distance alone, which suits teleport and flash-jump classes.
  It has no rope or ladder semantics.
- **MS-Visionify platform graph.** The operator walks each platform while recording
  ([platform_data_creator.py#L191-L210](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/platform_data_creator.py#L191-L210)).
  Edges are generated from geometry: drop where x overlaps, half or full double jump for rises
  of 20 or 31 px or less, and side jump for endpoints within 16 px
  ([terrain_analyzer.py#L370-L427](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/terrain_analyzer.py#L370-L427)).
  The double-jump Up timing comes from a fitted line, t = (41.5 − Δy)/76 clamped to 0.15–0.45 s
  ([L629-L644](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/terrain_analyzer.py#L629-L644)).
  Ladders are detected while recording but never saved, and climbing is not implemented
  ([L352-L366](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/terrain_analyzer.py#L352-L366)).
  Landing is not confirmed: the next loop matches the platform by exact y with ±3 px x slack
  ([macro_script.py#L94-L123](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/macro_script.py#L94-L123)).
- **MapleStoryAuto** replays recorded waypoints (`{action, nx, ny}` in normalized minimap
  coordinates). It has no planner.
  - Landing counts after 4 frames stable within 0.01, with up to 6 retries, then a restart
    from the first waypoint
    ([auto_combat.py#L4031-L4065](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L4031-L4065)).
  - A climb aligns x, holds Up or Down, and arrives when dx and dy are both inside tolerance
    and stable for 0.3 s
    ([L4068-L4098](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L4068-L4098)).
  - It detects knockback as a velocity sign flip beyond ±40 px/s, excluding 0.6 s after edge
    turns and jumps
    ([L632-L646](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L632-L646)).

### Recovery when the position is uncertain

| Bot | Behaviour | Keys released? |
|---|---|---|
| Auto Maple | No stuck or lost-position handling. A 20 Hz notifier alarms and disables the bot on a black screen, an elite boss, or a rune unsolved for over 270 s ([notifier.py#L58-L122](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/notifier.py#L58-L122)) | Bot disabled on alarm |
| MS-Visionify | After 10 loops off any platform it runs a scripted `unstick()` jump. After 5 failures it returns −2, which the caller ignores ([macro_script.py#L247-L266](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/macro_script.py#L247-L266), [main.py#L59-L66](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/main.py#L59-L66)) | No |
| MapleStoryAuto | 40 s budget per segment, then restart ([L3875-L3879](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L3875-L3879)). With no monster, no minimap dot and no player for 8 s it only beeps ([L8661-L8689](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L8661-L8689)) | No |
| msbot | Window re-find and Alt+Enter only ([MSBot.cpp#L32-L44](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L32-L44)). It never sends `WM_KEYUP` | No |

None of them pauses input on lost identity, requires the same player before resuming, or
bounds recovery with a deadline that ends in a safe stop. On those points our
[reacquisition.py](../src/maplebot/reacquisition.py#L79-L132) is stricter than all four.

### Capture performance

| Bot | Capture | Loop | Notable cost |
|---|---|---|---|
| Auto Maple | `mss`, full window each iteration, `sleep(0.001)` ([capture.py#L109-L146](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/modules/capture.py#L109-L146)) | Close to a busy loop | Full-window grab; only a small minimap match per frame |
| MS-Visionify | PIL `ImageGrab` of the window ([screen_processor.py#L53-L69](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/screen_processor.py#L53-L69)) | Every poll runs `SetForegroundWindow` and a 0.1 s sleep | O(n²) dot filter |
| MapleStoryAuto | `windows-capture` (Windows Graphics Capture), capped at 15 fps ([GameWindowCapturor.py#L57-L106](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/src/input/GameWindowCapturor.py#L57-L106)) | 10 fps default, clamped to 2–30 ([L7612](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7612)) | YOLO on a background thread, results reused for 1.2 s ([L5034-L5095](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L5034-L5095)). The author says OCR "pegs the CPU at 1500%+" ([L6636-L6638](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L6636-L6638)) |
| msbot | GDI `BitBlt` of 800×600, written to a BMP on disk and loaded back every tick ([MSBot.cpp#L361-L438](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/MSBot.cpp#L361-L438)) | `Sleep(100)` | Disk round-trip of 1.4 MB per tick |

Ours: `mss` window grab ([capture.py#L65-L73](../src/maplebot/capture.py#L65-L73)), with
recognition, not capture, limiting the rate to about 3 fps. Windows Graphics Capture is the
only capture-side technique here that differs from ours. It does not address recognition cost.

## Comparison with this project

| Area | Ours (HEAD `198cb8f`) | Best OSS counterpart | Gap or lesson |
|---|---|---|---|
| Prediction | [`_predict`](../src/maplebot/perception.py#L1131-L1143) shifts the last box by phase-correlated/feature camera shift ([`CameraTracker`](../src/maplebot/perception.py#L243-L272)) plus a learned world step clipped to 40 px ([`_learn_motion`](../src/maplebot/perception.py#L1145-L1158)). Below camera response 0.35 the step is cleared | MapleStoryAuto constant velocity with ×0.8 decay per miss | Ours is camera-aware; theirs is not. Ours drops the world step to zero when [`_follow`](../src/maplebot/perception.py#L1399-L1441) starts coasting, instead of decaying it |
| Search window | [`_observe_window`](../src/maplebot/perception.py#L1206-L1240): a 700×420 ROI around the track, a full scan on every 4th miss, and a full-frame or minimap [strip](../src/maplebot/navigation_runtime.py#L406-L420) fallback | None of the OSS bots uses an ROI on the main screen | The minimap strip is used only during navigation `EdgeStep`. Combat coasting stays centred on the stale prediction |
| Weak-evidence chaining | `_follow`: a radius of 12 + 240 px/s up to 80 px, a 1 s gap and a 5 s chain limit; it refuses ambiguous near candidates and fuses a partial name tag | MapleStoryAuto 6-frame hold; the others hold silently | Ours is stricter. Nobody else bounds the chain or refuses ambiguity |
| Identity | [`_resolve`](../src/maplebot/perception.py#L996-L1017) margin 0.04, look-alike detection, name-tag fusion; [`ConfirmedSprites`](../src/maplebot/reacquisition.py#L17-L68) carries the name through sprite frames | MapleStoryAuto glyph margin 0.02 plus other-player dot vetoes | **Lesson:** the other-player red dots on the minimap are a cheap negative prior. We do not use them |
| Reacquisition | [`Reacquisition`](../src/maplebot/reacquisition.py#L79-L132): pause, 2 fresh agreeing frames ≥ 0.15 s apart, a 4 s deadline, then stop | None | Ours is stricter. Keep it |
| Enemy occlusion | [`EnemyTracker`](../src/maplebot/enemy_tracking.py#L90-L196): ground-clamped velocity, growing uncertainty, an `occluded` state only when covered, 4 s occlusion and 0.5 s lost limits. [`_uncover`](../src/maplebot/perception.py#L920-L982) rescores partly covered sprites | MapleStoryAuto decaying tracker, with 2-hit confirmation | Ours is stronger; nothing to adopt |
| Hidden-target attack | [`_hidden_target`](../src/maplebot/decision.py#L343-L381): only the current track, ≤ 1 s, in range, same platform, never stepping toward it | MapleStoryAuto refuses to attack below player confidence 0.9 | Equivalent intent |
| Minimap ↔ screen | [`LivePosition.update`](../src/maplebot/live_position.py#L165-L275) registers the marker against fresh player feet at camera confidence ≥ 0.60 and projects area coordinates to screen only on a confirmed platform. [`MinimapDetector`](../src/maplebot/minimap.py#L34-L68) requires one unique 6×6 dot | MapleStoryAuto per-map piecewise camera fit, used to place a hidden player | **Main lesson:** we already have the transform but do not feed it back into the player search while the player is hidden |
| Navigation under dropout | [`Navigator`](../src/maplebot/navigation_executor.py#L99-L200): name-tag dropout releases keys, marker-only frames never confirm settling, 2 replans, a 60 s / 8-edge budget | MapleStoryAuto: 4 stable frames to land, 6 retries, a 40 s segment budget | Ours is stricter. The OSS budgets agree in scale with ours |

## Top 5 techniques for tracking under occlusion at low CPU cost

Ranked by expected gain for our failure mode (the name tag and sprite hidden by grass,
monsters or effects at about 3 fps) divided by CPU cost. All must be reimplemented from the
idea; no code is copied. None may make a frame "fresh": [Reacquisition](../src/maplebot/reacquisition.py#L79-L132)
still needs real name-tag or sprite evidence.

1. **Minimap-marker search prior while coasting.**
   Source: MapleStoryAuto
   [L7078-L7177](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L7078-L7177).
   When `_follow` coasts or misses and the marker is unique, centre the ROI on the screen x
   that our existing area→screen projection gives for the marker, instead of the stale box.
   Clamp at the map ends, where the camera stops scrolling. Cost: about 0.1 ms, because the
   minimap is already read every frame. Gain: the next confident match lands inside the small
   window, which avoids the 5× full-frame scan and keeps recovery frames fresh.
2. **Marker-consistency gate on reacquisition candidates.**
   Source: MapleStoryAuto allowed zones and other-player vetoes
   [L6807-L6911](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/auto_combat.py#L6807-L6911).
   Reject a player candidate whose x disagrees with the marker projection beyond its
   uncertainty, and lower trust in x zones near other players' red dots. Cost: microseconds.
   Gain: fewer look-alike resumes, at no extra matching cost. It only refuses; it never
   accepts.
3. **Horizontal close before scoring a partly hidden name tag.**
   Source: MapleStoryAuto color anchor
   [L1358-L1410](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1358-L1410).
   A 1-row-tall horizontal close inside the tag search area bridges a pet, rope or grass cut
   before [`_partial_nametag`](../src/maplebot/perception.py#L1443-L1459) and
   [`_occluded_tag_score`](../src/maplebot/perception.py#L1550-L1569) score it. Cost: well
   under 1 ms inside the 350×240 movement window. Gain: more frames keep the named chain.
   Thresholds must be re-validated on recordings, because closing can also merge a
   neighbour's tag.
4. **Decay the world step instead of zeroing it.**
   Source: MapleStoryAuto `DetectionTracker`
   [L1008-L1022](https://github.com/Jeremyzzzzz/MapleStoryAuto/blob/2a2d6c217328f2b32dd4e35b656ea00f32dac12c/tools/yolo_monster_viewer.py#L1008-L1022).
   Multiply `world_step` by a factor per missed frame (about 0.5 at 3 fps, because keys are
   released and the character decelerates) rather than clearing it at the coasting boundary.
   Cost: negligible. Gain: small, mainly after knockback in flight. The factor must come from
   recorded deceleration, not from their 0.8 at 10 fps.
5. **Verify the predicted box first, with early exit.**
   Sources: msbot early-exit SSD
   [Image.cpp#L31-L49](https://github.com/angusshire/msbot/blob/5d111b1330756fd72121ed39c60abb2757ab6f92/Image.cpp#L31-L49)
   and MS-Visionify neighbour-count shape filter
   [screen_processor.py#L218-L228](https://github.com/Dashadower/MS-Visionify/blob/a7e48c71005a577443d998fb1e8c0f4cbdb03ba7/src/screen_processor.py#L218-L228).
   Before the ROI template sweep, score the last confirmed sprite at the predicted position
   and ±a few px. Run the full ROI search only if that fails. Cost: about 0.1 ms on a hit.
   Gain: CPU headroom, not robustness; we already use masked color prefilters
   ([`_color_where_possible`](../src/maplebot/perception.py#L900-L918)). This is worth
   measuring only if profiling shows the ROI sweep dominating.

Rejected: an Auto Maple–style minimap-only position, because it cannot see attack range or
on-screen geometry. Silent last-known holds (Auto Maple, MS-Visionify) are unsafe. YOLO is
AGPL-encumbered, GPU-bound, and adds cost at 3 fps. OCR identity costs too much CPU per the
author's own note.

## Implication

Techniques 1 and 2 reuse state we already compute (minimap marker, area→screen projection,
camera shift). They are the cheapest path to faster, safer reacquisition under occlusion.
They change only where perception searches and what it may refuse, never when input may
resume. This note does not implement them.
