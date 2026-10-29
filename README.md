# Maple External

An independent Python application for Windows 11 and Python 3.12+. It reads visible screenshot pixels and can send ordinary, bounded keyboard input. The game client is never modified. No memory, game APIs, save files, NX assets, networking to the game, or debugging interfaces are used.

## Install and launch

Dependencies are already installed in this workspace's `.venv`. From this directory:

```powershell
.\run.ps1
```

The native overlay opens over the game. **F6** toggles the selected activity On/Off,
**F7** opens settings, **F8** stops, and **F9** toggles drawings. The overlay is
click-through during play. Opening settings stops input; closing settings never
resumes it. Select combat, potions, a navigation destination or a bounded probe
in settings, then close settings and press F6 with the game focused. The indicator
reports the engine state, including Off, Starting, On and Blocked.

With F7 settings open, drag the status, saved-terrain or settings heading to move
that panel anywhere on the desktop, including outside the game. Positions are
remembered; **Reset positions** returns them beside the game. Detection boxes stay
anchored to the game. F6 also works from settings and reports why a start stops or
is blocked. The default decision preview sends no gameplay keys.

Live boxes show existing player/enemy detection. The separate saved-terrain inset
shows learned geometry and fresh localization; it is not live terrain detection.
Stale detections disappear. The engine stops if the overlay stops responding.
Windows capture exclusion keeps the overlay out of screenshots; ordinary game
focus, occlusion, capture and keyboard checks remain active.

The launcher defaults to **capture-only**: keyboard output is locked for the entire session, control probes and combat are unavailable, and no OS keyboard backend is constructed. Screenshot capture, calibration, recognition, saving, recording and dry-run decisions remain available. Installation requires Node/npm for the React/Electron shell as well as Python. To install on another machine:

```powershell
.\install.ps1
# Or, without the helper:
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The helpers only install this application in its local virtual environment. They do not install, change, or launch the game. Existing screenshots/templates are preserved. Replaced calibration files receive timestamped backups.

The React workspace puts the game preview first and opens one focused tool at a
time. Settings contains connection and control setup; Diagnostics contains the
technical details. The previous debugger remains available at
**http://127.0.0.1:8765/legacy**. See [the workspace review](docs/workbench-review.md)
for the review steps and UI rebuild commands. Python serves the shipped UI;
Node is not required when running it.

For temporary MapleStory recognition testing, use the default launcher and play manually. Attach the visible game window, confirm the correct crop, then inspect boxes or save screenshots. Enemy matching needs native 1x pixels. Saved screenshots and recordings can be replayed offline.

Dry runs and armed runs are recorded automatically to `data/recordings/session-*`. Every decision goes to `decisions.jsonl`. Frames are kept in memory for the last 10 seconds and written to disk only when the agent stops, when player detection becomes uncertain (plus 2 seconds afterwards), or when you click **Save last clip**, which also works outside a run. One context frame per second is saved as well. Each incident is logged to `events.jsonl`. **Start / stop full recording** saves every frame. Old sessions are deleted beyond 7 days or 2 GB in total. Adjust this under `[recording]` in `config.toml`. Capture-only cannot be unlocked from the debugger.

When returning to an offline or explicitly permitted automation environment, `./run.ps1 -EnableGameplayInput` starts a separate input-capable session. Capture and control verification are still required before any input. Equivalent direct commands are `python -m maplebot debug --capture-only` and `python -m maplebot debug`.

### Elevated input sessions

The MapleStory client runs as administrator. Windows (UIPI) silently drops keys that a
non-elevated program sends to it, while `SendInput` still reports success, so probes appear
to do nothing. The engine detects this and refuses probes with that reason. Register an
elevated task once (one UAC approval):

```powershell
.\tools\install_elevated_task.ps1          # register the MapleBot task
.\tools\install_elevated_task.ps1 -Uninstall
```

Afterwards `.\run.ps1 -EnableGameplayInput` and `tools/restart_engine.ps1 -EnableGameplayInput`
start the `MapleBot` task, which runs the input-capable engine with highest privileges and no
prompt. Its window closes when the engine stops. Plain `.\run.ps1` stays capture-only and
non-elevated. The elevated engine still binds only `127.0.0.1` and requires the per-session
token, and all input keeps the focus, calibration, probe, watchdog and F8 gates.

### Restarting the engine

Restart a running engine with `tools/restart_engine.ps1` (add `-EnableGameplayInput`
for an input-capable session). It stops the engine through its own API, waits for the
port to close, closes `run.ps1` windows that no longer host it, and opens one new
window. Do not restart by starting `run.ps1` again from a script: each launcher window
stays open (`-NoExit`) after its engine stops, so repeated restarts pile up empty
terminals.

## Prepare MapleUnity

The public [MapleUnity README](https://github.com/ilia810/MapleUnity#run-the-local-scene) documents Unity **2023.2.20f1**, **MapleUnity → Play Hunting Ground**, and a **Scale 1x** Game view. MapleUnity documents 1024 × 768; this bot is set up for **1366 × 768** at 1x. Use the existing, locally configured game project. An executable build is unnecessary.

Select the Game tab and keep it unobscured. The documented attack defaults are **Z / Left Ctrl**; bindings may have been reassigned. This bot defaults to **Left / Right**, **Z**, **Space** and verifies each through a bounded probe. Change `[input]` in `config.toml` if the observed controls differ; supported names are `left`, `right`, `a`, `d`, `z`, `ctrl`, `space`. Restart after changing config, and repeat verification. F8 is the emergency stop.

## Calibration: capture first

1. Start the debugger. Use **Refresh windows**, select the window titled **MapleStory** (`capture.window_title`), and **Attach**. No gameplay input is sent.
2. Use **Reset crop** if a previous crop exists. **Freeze for selection**, then drag a rectangle tightly around the rendered Game view, excluding tabs, toolbars and letterboxing. **Apply selected crop**.
3. Inspect the live pixels. They should show the actual running game at the expected size and detail. Check **I see the correct, unscaled live Game view**, then **Confirm capture**. An evidence screenshot is saved.
4. To select a screen region without attaching a window, expand **Manual desktop region** and enter physical x, y, width and height. Negative coordinates support monitors to the left/top. This mode is observation only and cannot arm input.

Window coordinates and screenshots use physical pixels with per-thread Per Monitor V2 DPI awareness. Moving a window updates the crop's screen origin. Changing its client size, DPI or title invalidates calibration and stops input. Changing the Game tab layout, Game-view scale, resolution or scene inside an unchanged Editor window requires manual recalibration; Win32 window geometry cannot identify those changes.

If the window moves during a screenshot, that frame is discarded. An alarm is
raised only after five consecutive failed captures, half a second apart. Position-only
movement keeps the saved calibration and controls. The preview holds the last
good image with a stale label, so brief capture gaps do not collapse the page.
Live input releases immediately and requires an explicit restart; observation
and potion preview recover when stable capture returns.

At startup the debugger automatically reconnects when exactly one visible window matches the saved title, dimensions, DPI and crop. The **Game connection** panel verifies the matching saved view automatically when a fresh, unobscured frame confidently recognizes the player or a calibrated HP/MP bar. Cached player tracking does not qualify. Window selection, manual regions, crop editing and manual confirmation are under **Advanced setup**. If the game was opened later, use **Reconnect**. Ambiguous or changed windows require explicit setup. No input starts automatically.

Successful control probes are saved in `data/confirmed-probes.json`. Reattaching the same game title, crop, dimensions and DPI restores matching confirmations. Changing a key invalidates only that control; changing a potion HUD reference invalidates that potion. Starting another probe revokes its previous confirmation until the new test succeeds. Capture verification resets on restart and is restored by confident recognition (or explicit manual confirmation); combat/live potions always start stopped. During a freeze/selection, input is stopped; **Return to live view** before probing or arming.

## Teach and inspect detection

The default enemy catalog starts with **12 classic ground-monster species**. It can also import every available non-boss reference through a chosen level. All usable standing, moving, jumping and hit-reaction frames are retained. Those enemies are detected automatically; no manual enemy selection or vision-model installation is needed. The debugger lists the loaded species, and boxes show the matched species and confidence. The player still uses your screenshot examples.

Public reference images are downloaded **only during setup**, then read from `data/templates/catalog` while playing. To install or extend the catalog:

```powershell
.venv\Scripts\python.exe -m maplebot catalog
# Optional: import specific public database monster IDs.
.venv\Scripts\python.exe -m maplebot catalog --ids 100100 100101 130101
# Import every API-listed non-boss monster at levels 1 through 50.
.venv\Scripts\python.exe -m maplebot catalog --max-level 50
```

The importer uses the public [Dream MS image API](https://api.dreamms.gg/) for monster names and transparent stand/move animation images. Level selection additionally reads the public monster index's level and boss flags during setup; event/quest variants may be included, and entries without known levels are excluded. It saves frame hashes and source URLs in `data/templates/catalog/manifest.json`, caches downloads for repeatable offline use, and preserves manual templates. Sprites belong to Nexon; they are local reference files, not bundled with this repository. No internal game files are used. The API supplies its current assets, so these sprites still need verification against the actual game version. Larger catalogs can reduce processing FPS.

`--max-level` also caches public map titles and their monster IDs in `data/templates/catalog/maps.json`; positions and navigation data are not retained. Windows OCR reads the top-left map title in a background worker, then detection searches only that map's catalog species. Player and manual monster examples remain active. The complete library stays installed. Unreadable, changed or unknown titles use the full catalog until a map is recognized. Identically named maps use the union of their species. All recognition remains offline. Missing Windows English OCR also falls back to the complete catalog; the status reports `active_map`, `active_variants` and `map_filter_error`.

Matching uses a color index to find native-pixel candidate positions, then checks the full opaque foreground using color and structural similarity. Reference transparency excludes scenery. Both directions and several animation poses are included. A few obstructed sample pixels are tolerated when proposing candidates; full foreground verification still applies the unchanged confidence threshold. The input gates remain unchanged. Use **1x game pixels**: scaling, major tint changes, occlusion, unsupported poses or a missing catalog type can cause no detection. A matching sprite is appearance evidence; visually identical friendly entities still require context checks. Unknown types are not guessed to be enemies.

Manual enemy examples remain available for types outside the installed catalog:

1. After capture verification, freeze a screenshot and draw a tight box around the player, including the feet; click **Add player**.
2. For an enemy missing from the catalog, draw a tight box around it, including the feet; click **Add monster**. Avoid labels, damage numbers and neighboring sprites. Skip this step for catalogued types.
3. Collect a few examples of different animation poses/backgrounds. Both horizontal orientations are generated automatically. All templates come from your screenshots. Original screenshots and selection metadata are retained alongside them for audit.
4. Freeze a frame where your name tag (the dark box with your name under your feet) is fully visible, draw a tight box around it and click **Add name tag**. The tag stays the same when you change gear or climb a rope. Matching uses only its white text, because the box behind it is translucent. Other copies of your name in that frame, such as the HUD status bar, are recorded and ignored. The tag and the player sprite cross-check each other; if they are found in different places, the player is treated as missing. While the tag is clearly readable, the sprite above it is snapshotted in memory every few seconds, so after a gear change the player is still recognised when grass or another player covers the tag. Snapshots are not saved and reset on restart. If both are hidden, weaker evidence (such as a half-covered tag) is accepted only near the last tracked position. Each such frame extends tracking, which ends after `perception.track_seconds` (1 s) without evidence or `perception.track_max_seconds` (5 s) since the last confirmed frame; such frames are marked `tracked` and also trigger a recording clip. Arming still requires a confirmed player.
5. **Return to live view**, then **Dry run**. Inspect player/monster boxes, confidence, selected target, intended direction, failures and decision history. This produces decisions without keyboard input. A stop is latched; correct the reason and start again.

The first detector combines color template similarity and grayscale structural correlation, suppresses overlapping matches, and rejects ambiguous player identities. Player examples automatically derive a foreground mask around a stable upper-body component, so scenery, labels and animated legs need not match. Fast grayscale proposals are verified against those masked pixels; the original selected box is retained for tracking. If a reliable mask cannot be derived, the full-example matcher is used. Transparent enemy references use their opaque pixels; ordinary manual monster examples use their full rectangle. Scores are similarity scores, **not calibrated probabilities**. Global phase correlation estimates camera translation; target tracking associates detections after that translation. Only confident targets whose sprite feet lie approximately level with the player's feet are eligible. This is a platform heuristic, not terrain recognition. Five approach steps without observed progress stop the agent so it cannot walk indefinitely against a wall or an inactive Game view.

Thresholds, attack range, platform tolerance, short movement durations and capture FPS are in `config.toml`. The configured capture FPS is an upper bound; processing may reduce actual FPS. Keep confidence conservative. Save troublesome frames and improve examples before lowering it.

Distant approaches renew a horizontal hold on each fresh confident target observation, avoiding repeated key presses between frames. Each renewal expires after `max_action_seconds` (250 ms by default); the total hold can span multiple observations. Near attack range, movement uses short steps. Target loss, potions and attacks release the approach hold. Combat commands do not accumulate behind an active combat key. When a potion defers an attack, the policy retains its attack attempt and checks the target again on the next observation before retrying.

Template matching was chosen as the first inspectable, training-free implementation. GrabCut foreground segmentation is used to derive the player mask once when templates load; no game assets are read. Segmentation can still fail when sprite/background colors blend or the player is off-center in a loose selection; feature matching is often weak on tiny animated pixel sprites. No neural model is included. Replace the `Detector` protocol implementation to experiment later.

## Maps for navigation

Platforms, ropes and movement links come from public map data, not from walking the map. Save the area once from **Navigation → Setup → Advanced: draw by hand** with a reference view, stop the engine, then import its public map:

```powershell
.\.venv\Scripts\python.exe -m maplebot import-map "<map name>" --dry-run
.\.venv\Scripts\python.exe -m maplebot import-map "<map name>"
```

Use `--map-id` when the saved name does not match a public map title. Restart the engine, track the map under **Setup**, and run walk calibration once so the minimap marker lines up with the saved map. Navigation refuses maps that have not been imported.

## Verify keyboard control, then combat

1. Verify capture and recognition first. Keep the player on one ground platform with one nearby visible monster. Combat is required only for the attack-effect probe and combat run, not capture calibration.
2. Click **Left** under **Verify controls**, then click inside the game window during the three-second countdown. Observe a short leftward movement. Repeat **Right**, **Attack**, and **Jump** separately. An accepted SendInput call does not prove the game responded; visually inspect each effect.
3. If a probe has no effect, stop. Check Game-tab focus and actual bindings; adjust config and restart. No alternative injection mechanism is used; the only privilege step is the elevated task above, which matches the client's own elevation.
4. After observing all four effects, check the acknowledgement and **Confirm controls**. This records your observation, not an automatically inferred success.
5. Click **Arm combat**, then focus the Game view during the three-second countdown. The agent selects a confident same-platform monster, moves in short steps, faces it, attacks, releases input, and checks later screenshots. Initially stop after one visible approach/attack attempt and inspect the saved evidence. **F8** stops immediately; the debugger's **STOP** also releases keys.

The browser never steals focus automatically. Probe/arm commands do not focus Unity. Input is limited to the selected handle with the configured window-title match and verified geometry. A watchdog checks focus, geometry, sampled occlusion and F8 every 5 ms. Holds are capped at 250 ms by default, with release on stop, normal exit and caught errors. Observation processing over 500 ms stops input. Uncertain player detection stops the agent. Losing an enemy releases and cancels combat inputs while combat stays On, waiting without movement for a fresh confident same-platform target. Configured potions remain active. Focus loss and F8 still turn the bot Off; it does not blindly search by walking.

Ordinary SendInput has an unavoidable small race between checking foreground focus and delivering an event; Windows cannot atomically target these events to a Game tab. Releases of the bot's held keys still occur on focus loss. A forced process kill, OS crash or blocked OS input cannot guarantee cleanup. Use the normal stop/exit path.

## Input realism and competition rules

All input is software-only. The competition permits automated input; timing realism models plausible keyboard behavior independently of input-origin detection. This project does not try to conceal input origin or bypass third-party anti-cheat systems, and requires no external hardware.

The `[timing]` section of `config.toml` controls bounded hold-duration variation, reaction delay, pauses between actions, and staggering between key-down events. Defaults vary holds by up to 20%, add 25–85 ms before a sequence and 20–65 ms after it, and stagger key-down events by at least 12 ms. These are tunable heuristics, not a measured human-behavior model. OS scheduling is best effort. Set `enabled = false` for exact configured timings or set `seed` for reproducible timing experiments. Replay continues to generate deterministic decisions without constructing an input backend.

Compatible holds can overlap within the existing maximum-action-duration budget. Opposite movement directions and overlapping duplicate physical keys are rejected. Every held key has its own release deadline; focus loss, emergency stop and errors still release all keys. Stops also interrupt reaction delays and pauses. The current single-platform decision logic is unchanged and continues to issue one bounded action at a time.

For an agent that intentionally requests overlapping inputs, use the controller API after the normal focus/calibration gates:

```python
from maplebot.input_timing import KeyHold

controller.execute_sequence([
    KeyHold("right", seconds=0.18),
    KeyHold("jump", seconds=0.06, start_seconds=0.04),
])
controller.release("jump")  # Release just this action if currently held.
controller.release_all()
```

`execute_sequence` blocks until the bounded sequence finishes or is interrupted. `release`/`release_all` can release currently held keys from another thread; `stop` also cancels future events. Holds are limited individually and as a sequence by `input.max_action_seconds`; reaction/rest delays are outside that key-hold budget. Actual remaining hold time can be shortened when OS scheduling is late, and expired key-down events cancel the sequence rather than being delivered in a burst.

`InputBackend` is a protocol with `send(key: str, down: bool) -> None`. Supply an adapter through `Application(config, input_backend=my_backend)` or directly to `KeyboardController`. An adapter must deliver an ordinary key-down/up or raise on failure. Timing, logical key mapping, safety checks and decision logic remain outside the adapter. `Win32Input` remains the default software backend. Planned timings, delivered backend events and interruption status are available through `controller.timing_snapshot()` and the debugger/recording `input_timing` field. Backend acceptance does not prove a gameplay effect.

## HP/MP autopotter

The browser's **Autopotter** panel reads the visible red HP and blue MP bars and shows percentages/confidence. **Start potion preview** reports decisions without sending keys. **Start live potions** sends the configured HP/MP keys in an input-capable session. Replay and capture-only sessions remain input-free.

Defaults are **50% HP**, **30% MP**, and a shared **1.5-second cooldown**. Two consecutive confident readings at or below the threshold are required, HP has priority, and a threshold of zero disables that resource. A missing or uncertain HUD pauses potion input for up to five seconds, covering short portal/loading transitions. Recovery requires two consecutive confident readings before a potion can be sent. A HUD missing for five seconds stops live mode with an alarm. Empty HP, changed capture size, obscured game view and stale observations still stop immediately. STOP/F8, loss of game focus, calibration, and saved threshold changes stop live input. It starts stopped after a restart.

1. Attach and verify the game crop. Play manually until the bar to calibrate is full.
2. Freeze, select the **entire bar including all four pale borders**, excluding the HP/MP text and numbers, and click **Calibrate HP bar** or **Calibrate MP bar**. Repeat for the other bar.
3. Return to live view, set/save thresholds, and click **Start potion preview**. Read the percentages and reason in the panel; saving thresholds stops the preview so you can review the change before starting again.
4. For live use, verify **HP potion** and **MP potion** under **Verify controls** for each resource with a nonzero threshold. Click **Start live potions**, then focus the actual game within three seconds. Live potions operate independently of combat; combat remains stopped. Each dose is one bounded key press, followed by the shared cooldown. Completion of a key press does not itself confirm a potion effect. **Stop potions** releases input and stops monitoring.

New references for the existing 1023×766 saved crop are installed in `data/autopotter.json`, derived only from your three saved screenshots. Recalibrate for a different HUD/crop; earlier calibration/settings receive timestamped backups. No player/enemy templates or game files are changed.

To include potion decisions in screenshot replay:

```powershell
.venv\Scripts\python.exe -m maplebot replay YOUR_FRAME_FOLDER `
  --autopotter data\autopotter.json --output artifacts\potion-replay --annotated
```

Replay logs include HP/MP readings, reasons and hypothetical potion counts with `input_sent: false`. The current saved real frames all show full bars. Low-resource and cooldown behavior has been tested on generated and explicitly simulated frames, not on live damaged/recovered characters. Potion bindings, real key presses, inventory detection and visual effect verification remain future work for an appropriate automation test environment.

## Screenshots, diagnostic recordings and replay

**Save screenshot** saves raw and annotated PNGs under `data/screenshots`. **Start / stop recording** saves a sequence of raw/annotated PNGs plus `decisions.jsonl`, including timestamps, state, detections, intended direction and last action. This is a diagnostic image sequence, not a video codec. Recording is optional and can use substantial disk space.

Replay never constructs a Win32 input backend and works without a running game:

```powershell
.venv\Scripts\python.exe -m maplebot replay data\recordings\session-REPLACE `
  --templates data\templates --output artifacts\my-replay --annotated
```

The output contains annotated frames, a decisions log and `metrics.json`. Recorded timestamps drive VERIFY timing; plain PNG directories use the configured FPS. Use a separate output directory. Replay preserves stops rather than silently restarting uncertain behavior.

For labeled detection precision/recall at IoU ≥ 0.5, pass `--labels labels.json`. Boxes are `[x, y, width, height]` in screenshot pixels; every labeled frame should list all visible examples of the classes under evaluation, including empty arrays for negatives:

```json
{
  "00000000.png": {
    "player": [[100, 580, 24, 28]],
    "monster": [[800, 580, 24, 28]]
  }
}
```

Unlabeled frames are excluded from accuracy metrics. Without labels, accuracy is `null`. Processing FPS excludes disk reads, annotation, logging and waits. Decision latency is measured separately. Acquisition rate is acquisitions divided by SEARCH attempts; an attempt without a suitable monster counts as unsuccessful. Target disappearance is reported as **kill unconfirmed**, never as a successful kill. No real gameplay success metric is supplied.

## Tests and reproducible checks

For the usual edit/check loop, use `./tools/dev_cycle.ps1`. It runs focused
navigation tests and lint without requiring the game. Choose test files with
`-PythonTests`, or use `-Scope ui -UiTests client.test.ts` for a focused UI check.
`-Scope all -BuildUi` checks both sides and builds the installed UI, backing up
the previous assets first. Add `-Restart` only when the running engine needs the
change (`-EnableGameplayInput` explicitly selects an input-capable restart).
`-DryRun` lists the steps without running them. A failed step stops the sequence;
timings and build backups go to `artifacts/dev-cycle/<timestamp>/`.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check src tests tools
.venv\Scripts\python.exe -m maplebot doctor
.venv\Scripts\python.exe tools\capture_smoke.py
.venv\Scripts\python.exe tools\input_smoke.py
.venv\Scripts\python.exe tools\synthetic_benchmark.py
.venv\Scripts\python.exe tools\benchmark_catalog.py
```

The two native smoke tools create and close their own temporary windows. Input smoke sends keys only while its own window is foreground. The synthetic benchmark creates its own generated sprite images, labels and metrics under `artifacts/synthetic`; these are **not MapleUnity accuracy results**. The catalog benchmark composites every cached pose in both directions; optional `--negatives path1.png path2.png` evaluates screenshots you explicitly identify as containing no enemies. Its results under `artifacts/catalog-benchmark` measure reference self-consistency, not native gameplay accuracy. `tools/debugger_smoke.py` starts a temporary synthetic capture/debugger on port 8766 after generating that dataset; it never arms game input.

## Files and boundaries

- `capture.py`, `windows.py`: MSS pixels, physical window geometry, focus and DPI.
- `perception.py`: replaceable screenshot detector, confidence and camera estimation.
- `catalog.py`: setup-only public image import and provenance; no live-game network access.
- `decision.py`: deterministic IDLE → SEARCH → APPROACH → ATTACK → VERIFY state machine.
- `keyboard.py`: isolated, bounded Windows input and watchdog.
- `input_timing.py`: backend-independent timing variation and compatible overlap scheduling.
- `runtime.py`: ordered capture/decision/action loop, calibration and diagnostics.
- `debugger.py`, `static/index.html`: loopback-only visual debugger and ROI selection.
- `replay.py`: input-free replay and measured benchmarks.
- `tests/`: detection, decisions, camera shifts, calibration, focus, emergency stop and key cleanup.

The debugger binds only to `127.0.0.1`; write commands require its per-process browser token. It communicates with this bot, never with game internals. No tournament infrastructure is included.

## Verification status and limitations

See [docs/VERIFICATION.md](docs/VERIFICATION.md) for measured results and exact live-test gaps. A running MapleUnity window was unavailable during development. Real sprite accuracy, Unity Game-view input and a native approach/attack are **not yet verified**. The initial gameplay success criterion remains open.

Animated poses, occlusion, moving scenery, similarly colored sprites and Game-view scaling can defeat templates. Feet alignment does not prove connected terrain or exclude gaps. The first agent has no ladder/path planning, autonomous jump actions, minimap reading, health/revival handling, damage OCR or reliable death classification. Missing targets release combat input and return to stationary target search; a bounded VERIFY window tolerates brief disappearance after an attack without declaring a kill. Six attack attempts without disappearance stop it.

First improvements should use labeled real captures: validate multiple animation poses and hard negatives, measure false positives, compare foreground masks/segmentation, tune the range/platform heuristic and add screenshot-based health/death evidence. Consider learned detectors only after measuring the simple approach on those frames.

Reference documentation: [MSS](https://python-mss.readthedocs.io/stable/), [OpenCV template matching](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html), [Win32 DPI awareness](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext), [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).
