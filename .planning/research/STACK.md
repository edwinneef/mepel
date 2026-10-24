# Stack Research

**Domain:** Screenshot-driven 2D side-scroller bot (MapleStory client, melee warrior), Windows 11, Python 3.12. Milestone additions: taught platform/rope navigation, multi-platform targeting, skill attack with MP fallback, real potion keys with out-of-potion detection, pet-food timer, in-place recovery, alarm on unrecoverable stop.
**Researched:** 2026-10-24
**Confidence:** HIGH for "no new runtime dependency needed" and for the performance numbers (measured on this PC). MEDIUM for game-behavior techniques (rope state, quickslot icons), which must be checked against recordings from the target client.

> Existing stack (MSS capture, OpenCV template/glyph detection, Win32 SendInput, stdlib HTTP debugger, recorder) is documented in `.planning/codebase/STACK.md` and is not re-researched here.

## Headline Decision

**This milestone needs zero new runtime dependencies.** Every addition fits in the stdlib plus the NumPy/OpenCV already installed:

| Need | Use | New dependency? |
|------|-----|-----------------|
| Platform graph and route planning | `heapq` Dijkstra over a dataclass graph (~40 lines) | No |
| Spot layout persistence | `json` + `dataclasses`, same atomic-write + `.bak` pattern as `Calibration.save` | No |
| Alarm sound | `winsound.PlaySound(..., SND_FILENAME \| SND_ASYNC \| SND_LOOP)` | No (stdlib, Windows-only) |
| Pet-food and potion timers | Injected `now` (`time.perf_counter`), like `Agent.step(observation, now)` | No |
| Up/down, skill, potion, pet keys | Extend `keyboard.KEYS` and the extended-key flag set | No |
| Rope/ladder state | Taught geometry + existing player tracking + optional taught climbing sprite | No |
| HP/MP robustness, out-of-potion | Existing `BarReference` + effect-window check + optional quickslot icon template | No |
| Faster loop | Profile first; move PNG encoding off the worker; ROI-limited search. `dxcam` only if capture still dominates | Maybe later (`dxcam`), dev-only (`pyinstrument`) now |

**Capture is not why the loop runs at ~3 fps.** Measured on this machine with the project venv (OpenCV 4.14.0, MSS 10.2.0):

| Frame size | MSS grab | dxcam 0.3.0 grab | `cv2.imencode(".png")` | JPEG q80 |
|------------|----------|------------------|------------------------|----------|
| 1024x768 | 16.6 ms | 4.9 ms | (not measured) | (not measured) |
| 1366x768 | 17–21 ms | 7.2 ms | 31.8 ms | 3.0 ms |
| 1920x1080 | 33–37 ms | 15.8 ms | 55.4 ms | 5.0 ms |

`Application._run` PNG-encodes **twice per frame** on the worker thread (`raw` and `decorated`, `runtime.py`). At 1366x768 that is ~64 ms, which is 3–4x what switching to dxcam would save (~10–14 ms). `controller.execute()` also runs on the worker, so key holds (`movement_seconds = 0.12` plus reaction and rest jitter) stall capture. Perception takes up most of the rest of the 250–400 ms. Fix the order: profile, then remove per-frame PNG work, then restrict template search to ROIs, and only then think about the capture backend.

## Recommended Stack

### Core Technologies (unchanged, re-verified on PyPI 2026-10-24)

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| CPython | 3.12.10 (venv) | Runtime | Already in use; `enum.StrEnum` and `tomllib` are needed. | HIGH (local) |
| numpy | 2.5.4 (latest, 2026-10-10; requires >=3.12) | Frame arrays, bar math, geometry | Already pinned `>=2,<3`. | HIGH (PyPI JSON) |
| opencv-python-headless | **4.14.0.94** (latest 4.x); keep pin `<5` | Template match, HSV, phase correlation | **OpenCV 5.0.0.93 shipped 2026-07-02.** Do not upgrade mid-milestone. The migration notes say `cv2.<func>` names survive. But 1D NumPy arrays now map to 1D `Mat`, some modules moved to contrib, and nobody has re-baselined the detector thresholds (`confidence = 0.90`, nametag scores) on 5.x. Upgrade in its own phase, with the replay benchmarks as the regression gate. | HIGH (PyPI) / MEDIUM (5.x changes: community migration wiki) |
| mss | 10.2.0 (latest, 2026-04-23) | Screen capture | Keep it. It is 17–21 ms at the likely game sizes, which is under 10% of the frame budget. It already handles DPI, multiple monitors and arbitrary regions inside the `Calibration` model. | HIGH (measured) |
| winsound (stdlib) | Python 3.12 | Alarm sound | No dependency. Async looping playback, a stop call, and system-alias fallback. See the alarm pattern below. | HIGH (stdlib, verified against docs.python.org/3.12) |
| heapq / dataclasses / json (stdlib) | Python 3.12 | Platform graph, Dijkstra, layout file | The graph has fewer than about 20 nodes. You need custom edge semantics (launch zones, per-edge failure penalties), and you'd write those yourself even with a graph library. | HIGH |

### Supporting Libraries

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| dxcam | 0.3.0 (2026-03-12; 0.4.0 dev builds exist; maintainer active again, "Updated 2026") | DXGI Desktop Duplication capture, 2–3x faster than MSS | **Optional, deferred.** Add only if per-stage timing shows capture above ~15% of frame time after the PNG and ROI fixes. Put it behind a `[capture] backend = "mss" \| "dxcam"` switch, and keep MSS as the default and the fallback. Use `output_color="BGRA"` and slice `[:, :, :3]` to avoid its cv2 processor path. Call `grab(region=..., new_frame_only=False)`, because the default returns `None` when the screen hasn't changed. | HIGH (measured) / MEDIUM (maintenance) |
| pyinstrument | 5.1.3 (2026-07-29), **dev extra only** | Sampling profiler for one worker iteration or a replay run | Run it now, before choosing any speed work. `pyinstrument -r html -m maplebot replay <frames>` profiles the same perception and decision code with no game and no input. | HIGH (PyPI) |
| py-spy | 0.4.2 (2026-04-24), optional, not a project dep | Attach to the live `debug` process without restarting it | When the slowdown only shows up live: `py-spy top --pid <pid>` or `py-spy record`. | MEDIUM |

### Development Tools (existing, keep)

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest 9.1.1 | Unit and replay tests | Router, recovery FSM, potion effect-window and timer logic are all pure. Test them with an injected `now` and the fake `InputBackend` already used in `tests/test_keyboard.py`. |
| ruff 0.17.2 | Lint/format | No change. |
| `replay` CLI | Offline regression on recorded frames | Add navigation labels (current platform, on-rope) to recorded sessions so the classifier can be scored offline. |

## Feature-by-Feature Technique Recommendations

### 1. Taught layout and route planning (stdlib)

- **Data model** (`src/maplebot/navigation.py`, pure, no Win32 imports): `Platform(id, y, x1, x2)`, `Rope(id, x, y_top, y_bottom)`, `Link(kind, src, dst, launch_x1, launch_x2, cost_s)` where `kind` is one of `walk | climb_up | climb_down | jump_up | drop_down`. A rope becomes two links (`climb_up`/`climb_down`) between the platforms at its ends, plus an `on_rope` pseudo-location for localization.
- **Planner:** Dijkstra with `heapq`. Cost is the expected seconds of the link plus the walking distance to the link's launch zone divided by walk speed. Keep a per-link failure counter: each failed attempt multiplies that link's cost (or disables it for N seconds). That is how "try another route before stopping" falls out naturally. Re-plan every frame (microseconds for this graph size). Stop when no route with finite cost remains.
- **Multi-platform targeting:** score each confident monster as route cost to its platform plus the in-platform walk. That is the same Dijkstra, run once from the current platform to all nodes.
- **Persistence:** `data/spots/<name>.json`, written atomically with a timestamped `.bak` (copy `Calibration.save`). Store the calibration's client size and DPI alongside, and refuse to load on mismatch. Taught pixel coordinates are only valid at the same game resolution.
- **Teaching UI:** draw on the frozen frame with plain `<canvas>` in `static/index.html` (horizontal segments for platforms, vertical segments for ropes, click-pairs for links). No JS library is needed. That matches the existing no-build UI.

### 2. Localization and rope/ladder state (OpenCV already present)

Classify location from **geometry first, pixels second**:

1. **Geometry (primary):** from the tracked player foot point `(x, y_feet)`:
   - On platform P: `|y_feet - P.y| <= agent.platform_tolerance` (18) and `x` is in `[P.x1, P.x2]`.
   - On rope R: `|x - R.x| <= rope_tolerance` (start around 6–10 px), `R.y_top < y_feet < R.y_bottom`, and on no platform.
   - Otherwise: airborne or unknown.
   Add hysteresis: switch location only after 2 agreeing frames, unless the evidence is strong. At 3 fps that is about 0.7 s.
2. **Motion check (verification):** while `up` or `down` is held on a rope, expect a vertical change (dy) and almost no horizontal change (dx ≈ 0) between frames. Measure the climb speed in px/s from recordings and store it per spot. "Held Up for 1 s, dy ≈ 0" means not on the rope: it is a failed grab, and that link gets a failure.
3. **Pose (optional tie-breaker):** in classic clients the climbing sprite is a back view. Teach one climbing snapshot through the existing template-teaching flow, and match it with masked `cv2.matchTemplate(..., cv2.TM_CCOEFF_NORMED, mask=...)` inside a small ROI around the tracked player. Use it only to break ties, never as the sole signal: gear changes alter it, as they did for walking sprites.
4. **Camera:** if the spot's map is larger than the viewport, the client scrolls the camera, especially vertically while climbing. Then taught screen coordinates drift. Keep the layout in **world coordinates**: screen position plus the cumulative `CameraTracker` (phase-correlation) shift. Also teach one static terrain **anchor patch**, and re-lock with `cv2.matchTemplate` each N frames so the shift error does not accumulate. If the spot fits entirely on screen and the camera never moves, this can be skipped. **Verify on the target spot before building navigation.** This one fact changes the data model.
5. **Optional second position source:** the minimap's player dot is a saturated yellow blob in a fixed HUD region. `cv2.inRange` plus `cv2.connectedComponentsWithStats` gives the position independently of the camera and of grass occlusion. This is not whole-map navigation, which is out of scope, just a cheap cross-check. MEDIUM: confirm the client shows it.

Do not auto-detect ropes with Hough lines or edge detection. Terrain auto-detection is explicitly out of scope, and the taught layout is more reliable.

### 3. Input additions (Win32 SendInput already present)

- **Add to `KEYS`:** `up` 0x26, `down` 0x28, `alt` 0xA4 (VK_LMENU), `shift` 0xA0, `insert` 0x2D, `delete` 0x2E, `home` 0x24, `end` 0x23, `pageup` 0x21, `pagedown` 0x22, digits 0x30–0x39, letters 0x41–0x5A, F1–F12 0x70–0x7B. Classic MapleStory keymaps put potions and pet food on Insert/Delete/Home/End/PgUp/PgDn quickslots.
- **Critical bug to avoid:** `Win32Input.send` uses `KEYEVENTF_SCANCODE` and sets `KEYEVENTF_EXTENDEDKEY` only for `left`/`right`. Microsoft's list of extended keys is: the arrows, Insert, Delete, Home, End, PgUp, PgDn, right Ctrl/Alt, numpad Enter and `/`, and the Windows and Application keys. Without the flag, `MapVirtualKeyW(VK_UP, 0)` yields scan 0x48. That is **numpad 8**, and with NumLock on the game sees a different key. Replace the `("left", "right")` check with an `EXTENDED` set that covers all of these.
- **Hold duration vs `max_action_seconds = 0.25`:** a rope climb needs Up held for 0.5–3 s. Don't raise the global cap. Make the climb a held-key **lease**: `up` stays down while each new frame confirms progress, and is released if a frame shows no progress, the lease expires (≤ about 0.6 s without renewal), or any gate fails. The stale-hold watchdog in `KeyboardController` already implements the "release if not renewed" half.
- **Skill attack and MP fallback:** a config key `attack_skill`. The decision layer picks `attack_skill` when the last confident MP reading is at or above a `skill_mp_min` percent, otherwise `attack`. No new technology.

### 4. HP/MP robustness and out-of-potion detection

The existing `BarReference.read` (HSV fill mask, left/right split with fewest inconsistent columns, border-anchor check) is a sound base. Add:

- **Temporal smoothing:** keep the last 3 confident readings and act on the median. That filters single-frame misreads from popups or effects while still reacting within about 1 s at 3 fps. The current `low_frames >= 2` rule already does part of this.
- **Effect window per press:** record the reading before the press `p0`. The press counts as effective if, within `effect_window_s` (start at 1.5 s, which is 4–5 frames at 3 fps), a confident reading exceeds `p0 + min_gain` (start at 5 points). Count consecutive ineffective presses while the bar stays readable. Two or three in a row means out of potions or a wrong key: **safe stop + alarm**. An unreadable bar during the window is "unknown", not "failed".
- **Quickslot icon presence (MEDIUM, verify on client):** teach the potion's quickslot icon as a template at a fixed HUD ROI. In classic clients the icon disappears or changes when the stack reaches 0. A masked `matchTemplate` on that small ROI every few frames is a direct out-of-potion signal that doesn't depend on damage timing. If it works on the target client, it detects the condition before a failed press.
- **Numeric HP/MP text (defer):** if the HUD shows `HP [cur/max]`, the existing glyph-shape matcher used for name tags can read digits exactly. It is more robust than color fill under translucent overlays, but it costs more. Only build it if recordings show fill misreads.
- **Potion priority:** potion presses preempt movement and attack holds, but only between sequences. Release the movement keys first, then press the potion key. The planned `KeyboardController.execute_sequence` lock already serializes this.

### 5. Pet-food timer

A pure `PeriodicKey(interval_s, jitter_s, last_at)` evaluated with the frame's `now`, then routed through `KeyboardController` like any other action. No scheduler library: the single worker thread owns time, so a background scheduler thread would break the actor model. Persist `last_fed_at` only for the session. On start, feed immediately or after a configurable delay.

### 6. Alarm sound (stdlib `winsound`)

```python
import winsound
winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
# operator acknowledges in the debugger, or timeout:
winsound.PlaySound(None, 0)
```

- `SND_LOOP` requires `SND_ASYNC`. Without it the call blocks forever. `SND_MEMORY` cannot be combined with `SND_ASYNC` or `SND_LOOP`, so play from a file path. Use `importlib.resources.as_file` for a packaged WAV, and add `static/*.wav` to `[tool.setuptools.package-data]`. Or generate `data/alarm.wav` once with the stdlib `wave` module, which keeps binaries out of git. `SND_PURGE` is unsupported on modern Windows. Stop with `PlaySound(None, 0)`.
- Fallback when `PlaySound` raises `RuntimeError`: `winsound.MessageBeep(winsound.MB_ICONHAND)` repeated on a timer. Avoid `winsound.Beep`, which blocks the calling thread.
- Put it in a small `alarm.py` behind an `AlarmBackend` protocol (real vs fake), owned by `Application`, and trigger it from `_stop()` only for unrecoverable reasons. It must sound in dry-run and capture-only sessions too, because it is output to the operator, not to the game. Never import it from `perception.py` or `decision.py`.
- Known limit: it is silent if the PC is muted. Optionally pair it with `FlashWindowEx` on the debugger or game window via `ctypes`. That is cheap and also stdlib.

### 7. Loop speed (do in this order)

1. **Instrument:** add per-stage `perf_counter` spans to `status` (capture, detect, potion, decide, execute, annotate, encode). Profile a replay with pyinstrument.
2. **Stop encoding PNGs per frame on the worker** (~64 ms saved at 1366x768): keep the latest `ndarray` under `self.lock` and encode lazily in the `GET /frame.png` handler thread. Pass arrays to `SessionRecorder` and PNG-encode in its writer thread, so recordings stay lossless for replay. Optionally serve the live view as JPEG (3 ms).
3. **Don't block capture on key holds:** use the lease pattern above for movement and climbing, so the worker keeps observing while keys are held.
4. **ROI-limit perception:** search for the player near the last tracked position, and for monsters only on taught platform bands. A full-frame search is needed only after a tracking loss.
5. **Only then** consider dxcam (saves 10–17 ms per frame, measured).

## Installation

```bash
# Runtime: no changes. Keep pyproject [project] dependencies as-is:
#   mss>=10,<11  numpy>=2,<3  opencv-python-headless>=4.13,<5

# Dev extra: add the profiler
#   [project.optional-dependencies] dev = [..., "pyinstrument>=5.1,<6"]
.venv\Scripts\python -m pip install -e ".[dev]"

# Optional, later, only if profiling justifies it (behind [capture] backend):
#   capture = ["dxcam>=0.3,<0.4"]   -> pip install -e ".[capture]"
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `heapq` Dijkstra | networkx 3.7 (2026-09-21, requires Python >=3.12) | If the graph grows to whole-map navigation with hundreds of nodes, or you need graph analytics. For fewer than 20 platforms with custom failure-penalty edges, it adds a dependency and import time and saves almost no code. |
| MSS | dxcam 0.3.0 (DXGI) | When measured capture is above ~15% of frame time after the other fixes, or when you need >30 fps. Single monitor output per instance; map window coordinates to that output's origin. |
| MSS | windows-capture 2.0.1 (Rust, Windows Graphics Capture, 2026-08-08) | If you ever need to capture a covered window or want window-targeted capture without crop math. Its push/callback model (`@capture.event on_frame_arrived`), which only delivers frames on change, inverts the single-owner pull loop in `Application._run`. It also captures content the operator can't see, which weakens the "obscured window = unsafe" gate. |
| `winsound` | Browser `Audio()` in the debugger page | Only as a second channel. Autoplay policies need a prior user gesture, and background tabs can be throttled. |
| Geometry-first rope state | Pose classifier (taught climbing sprites only) | Never as the sole signal. Gear and cape changes break sprite matches; geometry plus motion doesn't care. |
| Fill-ratio bar reading | Glyph OCR of `HP [cur/max]` with the existing matcher | When recordings show fill misreads under overlays or translucency. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| networkx / igraph / scipy.sparse.csgraph | Heavy dependency for a graph with fewer than 20 nodes; the failure-penalty and launch-zone logic is custom anyway | `heapq` Dijkstra in `navigation.py` |
| pygame, simpleaudio (last release 2019, no 3.12 wheels), playsound, sounddevice | Extra native dependencies or unmaintained, for something stdlib does | `winsound` |
| bettercam (1.0.0, last release 2023-11), d3dshot (abandoned) | Stale forks of the DXGI approach | `dxcam` 0.3.x if needed |
| pyautogui, pydirectinput, `keyboard`, pynput for sending keys | They bypass `KeyboardController` (focus, calibration, watchdog, F8 gates), which is a safety constraint in PROJECT.md | Extend `KEYS` + `Win32Input` |
| pytesseract / EasyOCR / PaddleOCR for HP/MP digits | Large installs and slow per frame; Tesseract is poor on small pixel fonts | Existing glyph-template matcher, if numeric reading is ever needed |
| APScheduler / `schedule` / `threading.Timer` for pet food or potions | Adds a second thread that sends input outside the worker's ordering; breaks replay determinism | Pure timers evaluated with the frame's `now` |
| pydantic / attrs for the layout schema | New dependency; the project validates by hand in `config.py` | `dataclasses` + explicit validation, like `Calibration`/`PotionMonitor` |
| YOLO / ONNX detectors for player or rope state | Training data, GPU/latency cost, and opaque failures, for a single taught spot | Taught templates + geometry |
| Hough / edge-based rope and platform auto-detection | Terrain auto-detection is explicitly out of scope | Operator-taught layout |
| Upgrading to OpenCV 5.0 inside this milestone | Unbenchmarked threshold drift in a safety-gated detector | Stay on 4.14.0.94; upgrade as a separate phase behind replay benchmarks |
| Raising `input.max_action_seconds` to fit a climb | Weakens a global safety cap for every action | Held-key lease renewed per confirming frame |

## Stack Patterns by Variant

**If the taught spot fits entirely on screen and the camera never moves:**
- Store the layout in screen coordinates relative to the calibrated crop.
- Skip the anchor patch.

**If the camera scrolls (map larger than the viewport):**
- Store the layout in world coordinates. Combine the `CameraTracker` shift with a periodic anchor-patch re-lock.
- Treat anchor loss as "unexpected screen", which means safe stop + alarm.

**If the game renders at 800x600 or 1024x768 (classic clients):**
- Capture is about 5–17 ms either way. dxcam is not worth a dependency.

**If the HUD shows numeric HP/MP:**
- Consider glyph reading later. Keep fill-ratio as the primary reading.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| numpy 2.5.4 | Python >=3.12, opencv-python-headless 4.14.0.94 | Already installed together in `.venv`. |
| opencv-python-headless 4.14.0.94 | numpy 2.x | Keep `<5`. 5.0.0.93 exists but is unvalidated here. |
| mss 10.2.0 | Python >=3.9 | Current major; `mss.MSS()` as used in `capture.py`. |
| dxcam 0.3.0 | CPython 3.10–3.14 wheels; numpy; comtypes | `output_color="BGR"` needs cv2. It found `opencv` missing in a clean venv; with the project's headless OpenCV it would work, but `BGRA` + slicing avoids the dependency path. |
| pyinstrument 5.1.3 | Python >=3.8, win_amd64 wheels | Dev extra only. |
| networkx 3.7 (not recommended) | Python >=3.12, !=3.14.1 | Listed only for reference. |

## Sources

Confidence tiers come from the GSD `classify-confidence` seam, which rates `websearch`/`webfetch` LOW. Claims marked HIGH above rest on **direct local verification** (benchmarks run in the project venv or an isolated temp venv on this PC, PyPI JSON API metadata, and reading the project code), not on the web tier.

- PyPI JSON API (queried 2026-10-24): versions and dates for mss, dxcam, windows-capture, networkx, opencv-python-headless, numpy, bettercam, simpleaudio, sounddevice, pyinstrument, py-spy. HIGH (direct)
- Local benchmark, this PC: MSS vs dxcam grab, PNG vs JPEG encode at 1024x768, 1366x768, 1920x1080. HIGH (measured)
- Project code: `src/maplebot/runtime.py` (two PNG encodes per frame, synchronous `execute`), `keyboard.py` (scan-code SendInput, extended flag only for left/right), `autopotter.py`, `config.toml` (`max_action_seconds = 0.25`). HIGH (direct)
- https://docs.python.org/3.12/library/winsound.html: PlaySound flags, SND_LOOP/SND_ASYNC/SND_MEMORY rules, `PlaySound(None, 0)` stop, SND_PURGE unsupported. Seam tier LOW; official CPython docs.
- https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input: extended-key list, scan code table (Up = 0xE048 vs Keypad 8 = 0x0048). Seam tier LOW; official Microsoft docs.
- https://pypi.org/project/dxcam/ (README via PyPI JSON): `grab(region, new_frame_only)`, BGRA without cv2, `start()`/ring buffer, release semantics. Seam tier LOW; confirmed by running it.
- https://pypi.org/project/windows-capture/: callback API, `minimum_update_interval`, `draw_border`. Seam tier LOW.
- https://lab.trianta.dev/mirrors/opencv.opencv/wiki/OpenCV-4-to-5-migration and https://opencv.org/opencv-5/: Python bindings keep `cv2.<func>`, 1D `Mat` mapping, contrib moves. LOW (community mirror; the official transition guide returned 403).
- Game-behavior techniques (rope back-view sprite, quickslot icon disappearing at 0, minimap yellow dot, camera scrolling while climbing): domain knowledge of classic MapleStory clients. MEDIUM to LOW. **Verify against recordings from the target client before committing phase designs.**

---
*Stack research for: screenshot-driven MapleStory navigation and sustain bot (Python 3.12, Windows 11)*
*Researched: 2026-10-24*
