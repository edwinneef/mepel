---
last_mapped_commit: 9370ad5f14eb90e5ce4aeae8e7b52bb5b14ac14d
last_mapped_at: 2026-10-24
---
# Codebase Concerns

**Analysis Date:** 2026-10-24

## Tech Debt

**Live capture loop runs slower than its configured FPS:**
- Issue: `Application._run` in `src/maplebot/runtime.py` performs template detection, decision, potion preview and PNG encoding synchronously on one thread at `capture.fps` (default 12, `config.toml`). Each frame budget is about 83 ms at 12 fps, but `docs/VERIFICATION.md` records 157–199 ms per frame for real saved frames (about 6 processing FPS). The config value is therefore not what the loop delivers.
- Files: `src/maplebot/runtime.py`, `src/maplebot/perception.py` (`TemplateDetector.detect`), `config.toml`, `docs/VERIFICATION.md`
- Impact: Decisions use observations that are 150–200 ms old. The 500 ms "processing exceeded" guard in `_process` is the only backstop. Adding catalog templates (61 frames x 2 orientations) increases cost further.
- Fix approach: Profile `detect` per template group. Cache template signatures and pre-filter by kind. Decouple PNG encoding (`png(image)` for both raw and annotated frames each cycle) from detection, or only encode when the debugger or recorder needs it. Lower the default fps to match measured throughput and report measured fps in `/api/status`.

**Input execution blocks the capture worker:**
- Issue: `Application._process` calls `self.controller.execute(...)` on the capture thread. `KeyboardController.execute_sequence` sleeps through reaction delay, key holds and rest (up to about 0.25 s plus 85 ms + 65 ms of timing). No frames are observed or recorded during that time.
- Files: `src/maplebot/runtime.py` (`_process`), `src/maplebot/keyboard.py` (`execute_sequence`, `_execute_sequence`)
- Impact: The debugger's `/api/status` and recording lose frames during each action. Stop/emergency handling depends on the watchdog thread, not the worker.
- Fix approach: Dispatch sequences to a dedicated input thread and keep capture running. Keep the watchdog as the only safety path.

**Duplicated Win32 struct definitions per key event:**
- Issue: `Win32Input.send` in `src/maplebot/keyboard.py` declares `KeyboardInput`, `MouseInput`, `InputUnion` and `Input` ctypes classes on every call.
- Files: `src/maplebot/keyboard.py`
- Impact: Extra allocation on every key event, and the mouse struct is never used. The layout is hard to verify.
- Fix approach: Move the structure definitions to module scope once, and keep only the keyboard path.

**Silent defaults that disagree with the shipped config:**
- Issue: `InputConfig` in `src/maplebot/config.py` defaults `attack = "z"`, while `config.toml` sets `attack = "ctrl"`. `CaptureConfig` defaults `window_title = "MapleUnity"`, while `config.toml` sets `"MapleStory"`. `TimingConfig.key_stagger_seconds` default is 0.012, and the README documents it as "at least 12 ms"; this is consistent, but the default-versus-file split is easy to miss.
- Files: `src/maplebot/config.py`, `config.toml`, `README.md`
- Impact: The effective window title and attack key depend on which file is loaded. See the title mismatch below.
- Fix approach: Keep one source of truth (either the dataclass defaults or the TOML), and have `Config.load` log the effective values at startup.

**Incomplete `docs/BACKLOG.md` autopotter entry:**
- Issue: The backlog says "Nothing reads [HP/MP] yet", but `src/maplebot/autopotter.py` (`PotionMonitor`) now reads both bars and produces suggestions. The entry is partly stale and still describes sending keys, which is not implemented.
- Files: `docs/BACKLOG.md`, `src/maplebot/autopotter.py`, `README.md` (autopotter section)
- Impact: Planners using the backlog will plan from the wrong baseline.
- Fix approach: Split the entry into "done: HUD reading and preview" and "open: potion key execution, inventory and effect verification".

**Unbounded growth of data and backup files:**
- Issue: Only recordings are pruned (`SessionRecorder._prune`, capped at `max_total_mb` and `max_age_days`). Other artifacts are never pruned: `data/screenshots/` (`Application._save`), `data/templates/sources/` (saved on every `template` command), `data/templates/**` (manual sprites), and timestamped `.bak` copies written on every save by `Calibration.save`, `PotionMonitor.save` and `import_catalog`. Current sizes are about 478 MB in `data/` and 449 MB in `artifacts/`.
- Files: `src/maplebot/runtime.py`, `src/maplebot/capture.py` (`Calibration.save`), `src/maplebot/autopotter.py` (`PotionMonitor.save`), `src/maplebot/catalog.py`, `src/maplebot/recorder.py`
- Impact: Disk use grows without limit. Backups accumulate silently on each re-save.
- Fix approach: Keep only the newest N backups per file. Add a size report to `doctor`. Document retention for screenshots and templates next to `[recording]` in `config.toml`.

**Relative paths resolve against the current working directory:**
- Issue: `Config.load` takes `config.toml` relative to CWD by default. `Application.__init__` resolves `capture.data_dir` relative to CWD. Running `maplebot` from a different directory silently uses a new, empty `data/` tree, so calibration and templates appear lost. `run.ps1` avoids this by calling `Set-Location`, but the console script does not.
- Files: `src/maplebot/__main__.py`, `src/maplebot/runtime.py` (`Application.__init__`), `src/maplebot/config.py`
- Impact: Calibration and template loss that looks like corruption.
- Fix approach: Resolve `--config` and `data_dir` against the config file's directory, and print the resolved data path at startup.

## Known Bugs

**Window title mismatch between `config.toml` and the bot's input gates:**
- Symptoms: `config.toml` sets `window_title = "MapleStory"`. `Application._input_safe` and the `arm`/`probe` commands require that string to appear in the window title (case-insensitive). The documented target window is "MapleUnity - Unity", so arming refuses with "Input is restricted to the configured MapleUnity window title", a message that also names the wrong game. `Calibration.valid_for` requires the exact title, so it fails the same way.
- Files: `config.toml`, `src/maplebot/runtime.py` (`_command`, `_input_safe`), `src/maplebot/capture.py` (`Calibration.valid_for`), `README.md` (lines about temporary MapleStory testing)
- Trigger: Attach to "MapleUnity - Unity" with the committed `config.toml`, then click Arm or Probe.
- Workaround: Set `window_title = "MapleUnity"` for live MapleUnity runs. The README's temporary MapleStory testing needs its own config file.

**Calibration invalidates on any title change:**
- Symptoms: `Calibration.valid_for` compares the window title exactly. Unity changes the window title when the scene is modified (for example, an unsaved-changes marker or scene name), and then calibration is discarded and input stops.
- Files: `src/maplebot/capture.py` (`Calibration.valid_for`), `src/maplebot/runtime.py` (`_input_safe`)
- Trigger: Edit or save the scene in the Unity Editor while the bot is attached. The title change is not confirmed in live testing; this is inferred from the exact-match code.
- Workaround: Recalibrate after title changes. Consider comparing the window class and size instead of the title, or matching the title only as a substring.

**Debugger process exits when the capture worker fails:**
- Symptoms: `_run` catches the outer exception and sets the status to IDLE, then returns. The `__main__` loop `while app.worker.is_alive()` exits, and the process shuts down the HTTP server, so the browser shows a dead page with no reason.
- Files: `src/maplebot/runtime.py` (`_run`), `src/maplebot/__main__.py`
- Trigger: `Capture(self.windows)` fails at startup (for example, an `mss` error), or any exception escapes the inner loop's handler.
- Workaround: Check the console output. Consider keeping the HTTP server alive and exposing the failure in `/api/status`.

**Port collision is unhandled:**
- Symptoms: `debugger.serve` binds `127.0.0.1:8765` (from `config.toml`). If the port is busy, `ThreadingHTTPServer` raises `OSError` before any user-facing message.
- Files: `src/maplebot/debugger.py` (`serve`), `src/maplebot/__main__.py`
- Trigger: A debugger from an earlier session is still running.
- Workaround: Stop the other process or change `[debugger] port`.

## Security Considerations

**Local debugger exposes unauthenticated read endpoints:**
- Risk: `GET /api/status`, `GET /frame.png` (raw and annotated frames) and the `windows` command do not require the token; only POST endpoints check `X-Debug-Token`. Any local process can read the latest screenshots, window titles and calibration state. The Host header check defends against DNS rebinding, but not against other local users or processes.
- Files: `src/maplebot/debugger.py` (`Handler.do_GET`, `Handler.do_POST`)
- Current mitigation: Bound to `127.0.0.1`; Host header must be `127.0.0.1:<port>` or `localhost:<port>`; `Cache-Control: no-store`; CSP `frame-ancestors 'none'`.
- Recommendations: Require the token on GET routes that return screenshots or window lists, or pass it via a cookie set by `/`. Add a test for the 403 paths.

**Screenshots may contain unrelated desktop content:**
- Risk: The manual desktop region mode (`Capture.grab`) captures any screen area, and `Application._save` and the recorder write those frames to `data/`. The `.gitignore` excludes `data/` and `artifacts/`, but files are still plaintext on disk and may be shared accidentally.
- Files: `src/maplebot/capture.py` (`Capture.grab`), `src/maplebot/runtime.py` (`_save`, recorder usage), `.gitignore`
- Current mitigation: Recordings are age- and size-limited (`[recording]`). Git ignores `data/` and `artifacts/`.
- Recommendations: Warn in the UI when the manual region is active and recording. Offer a redaction or crop-only save option.

**Third-party sprite source and redistribution:**
- Risk: `src/maplebot/catalog.py` downloads Nexon sprites from the unofficial `api.dreamms.gg` API with no authentication, version pin, or license check. The manifest records the attribution text, but the sprites are cached locally and the API's availability and content are outside the project's control.
- Files: `src/maplebot/catalog.py` (`API`, `import_catalog`), `data/templates/catalog/manifest.json`, `README.md` (catalog section)
- Current mitigation: Sprites are not bundled in the repository; `.gitignore` excludes `data/`; manifest stores hashes and source URLs.
- Recommendations: Keep sprite caches out of any shared artifact. Record the API response date in the manifest. Document the legal position before any redistribution.

**Keyboard output is a real-world automation risk:**
- Risk: `Win32Input.send` uses `SendInput`, and gameplay input is enabled by a single command after a focus check. The focus check is not atomic with the event delivery, as `README.md` notes.
- Files: `src/maplebot/keyboard.py`, `src/maplebot/runtime.py`, `README.md`
- Current mitigation: Capture-only default (`run.ps1`), focus and occlusion gates, F8 emergency stop polled every 5 ms, hold cap of 250 ms, release on exit.
- Recommendations: Keep the capture-only default. Add an automated test that the watchdog releases keys when the focus gate fails mid-hold, using a fake backend.

## Performance Bottlenecks

**Full-frame template matching on every frame:**
- Problem: `TemplateDetector._candidates` and `_sprite_candidates` run `cv2.matchTemplate` against every template (including both mirror orientations and the catalog set) on each full frame.
- Files: `src/maplebot/perception.py` (`detect`, `_candidates`, `_sprite_candidates`, `_anchor_candidates`)
- Cause: No region-of-interest restriction, no template pyramid, and no reuse of the previous frame's search area beyond the tracking heuristic.
- Improvement path: Search only in the ground band around the player's last position for monsters, and use the tracked player position to limit the player search. Benchmark with `tools/benchmark_catalog.py` before and after.

**Per-frame PNG encoding for debugger and recording:**
- Problem: Every frame is encoded twice (raw and annotated) with `cv2.imencode` in `Application._run`, even when no client has requested the image.
- Files: `src/maplebot/runtime.py` (`png`, `_run`)
- Cause: Encoding is unconditional.
- Improvement path: Encode lazily on request, or encode only when the debugger has an active client or the recorder is active.

**Recorder buffers raw PNG bytes in memory:**
- Problem: `SessionRecorder.observe` appends every frame's PNG bytes to a `deque` sized `buffer_seconds * fps` (120 frames at defaults). Full-size game frames are held in memory continuously.
- Files: `src/maplebot/recorder.py`, `config.toml` (`[recording]`)
- Cause: Pre-roll is stored as encoded bytes, not downscaled or compressed differently.
- Improvement path: Measure RSS during a 10-second run. Consider storing the pre-roll at reduced resolution or as JPEG when the recorder is not in full-record mode.

**Watchdog polls every 5 ms while enabled:**
- Problem: `KeyboardController._watch` calls `safe()` (which calls `Windows.get`, `SetThreadDpiAwarenessContext` and nine `WindowFromPoint` checks) and `emergency()` about 200 times per second whenever input is enabled.
- Files: `src/maplebot/keyboard.py` (`_watch`), `src/maplebot/runtime.py` (`_input_safe`), `src/maplebot/windows.py` (`unobscured`)
- Cause: Safety is checked on a fixed timer, independent of whether a key is held.
- Improvement path: Poll the emergency key at 5 ms, but run the full focus/occlusion check at about 50 ms, which still stops input well inside a 250 ms hold cap.

**Template reload on every template or catalog change:**
- Problem: `TemplateDetector.reload` re-reads, validates and recomputes signatures for all templates on each `template`, `reload_templates` and startup call.
- Files: `src/maplebot/perception.py` (`reload`), `src/maplebot/runtime.py` (`_command`)
- Cause: Full reload, no per-file cache.
- Improvement path: Cache signatures keyed by file hash, and reload only the changed file. Not measured.

## Fragile Areas

**Player identity from name tag plus sprite:**
- Files: `src/maplebot/perception.py` (`_resolve`, `_follow`, `_partial_nametag`, `_refresh_sprite`, `_fuse_nametag`), `src/maplebot/runtime.py` (`_process`)
- Why fragile: Identity depends on a template that must match pixels within a 0.90 confidence gate (`[perception] confidence`). `docs/VERIFICATION.md` records one real frame that failed at 0.7675 before a mask-based fix. Partial-tag tracking (`nametag_partial = 0.6`) is explicitly close to random scenery scores ("random scenery near the player scores up to ~0.46" in `config.toml`). The fresh-sprite snapshots (`self.fresh`) and tracking state (`self.track`) are in memory only and reset on any `reload`.
- Safe modification: Change thresholds only with labeled saved frames and `tools/benchmark_catalog.py` or the replay path (`src/maplebot/replay.py`). Re-run `tests/test_perception.py`.
- Test coverage: Synthetic sprites and generated frames. No labeled live Hunting Ground captures exist (see `docs/VERIFICATION.md`).

**Target association and platform heuristic:**
- Files: `src/maplebot/decision.py` (`Agent.step`), `src/maplebot/perception.py` (`CameraTracker`)
- Why fragile: Association uses a fixed 80 px distance and an 8 px ambiguity margin. The same-platform test is "feet within `platform_tolerance` (18 px)", which the README admits is not terrain recognition. A stall guard stops after five non-progressing steps.
- Safe modification: Keep ambiguous cases stopping. Add replay fixtures before changing constants in `[agent]`.
- Test coverage: `tests/test_decision.py` covers state transitions with synthetic detections only.

**Configuration validation is incomplete:**
- Files: `src/maplebot/config.py` (`Config.load`), `src/maplebot/__main__.py`
- Why fragile: `PerceptionConfig` ranges are not validated (only `confidence`), and `[agent]` fields other than the two durations are unchecked. Unknown keys in a TOML section raise a raw `TypeError` from the dataclass constructor, which is not a friendly message. `InputConfig` keys are validated against `KEYS` only inside `KeyboardController.__init__`, which runs after the window and capture objects exist.
- Safe modification: Validate all sections in `Config.load`, and reject unknown keys with the section name.
- Test coverage: No test module for `config.py`.

**Calibration state machine across many flags:**
- Files: `src/maplebot/runtime.py` (`Application._command`, `_run`), `src/maplebot/capture.py` (`Calibration`)
- Why fragile: Gates depend on `calibrating`, `capture_verified`, `controls_verified`, `probed`, `pending_action`, `mode`, `stop_requested` and `frozen` together. Several commands call `_stop` before validating preconditions, so a rejected command can still stop a running session. Example: `arm` and `probe` call `self._stop(...)` before checking `calibrating`.
- Safe modification: Validate preconditions first, then stop. Add a test that rejected commands leave `mode` unchanged.
- Test coverage: `tests/test_runtime.py` covers the main paths; no test checks the stop-before-validate ordering.

**Recorder state shared across threads without a lock:**
- Files: `src/maplebot/recorder.py` (`path`, `full`, `manual`, `closing`, `post_until`), `src/maplebot/runtime.py`
- Why fragile: `start`, `stop`, `trigger` and `observe` mutate state. Most callers run on the capture worker, but `snapshot()` is read from the HTTP thread through `status`. Only `pending` and `dropped` are locked.
- Safe modification: Route all recorder calls through the capture worker, or guard the state with `self.lock`.
- Test coverage: `tests/test_recorder.py` runs single-threaded.

**Keyboard controller lock ordering:**
- Files: `src/maplebot/keyboard.py`, `src/maplebot/runtime.py` (`request`)
- Why fragile: `request` takes `controller.lock` and calls `controller.stop`, which takes the same `RLock`. `_watch` runs `safe()` outside the lock and `_release_keys` inside it. `_input_safe` calls `windows.get`, which may block on Win32 calls. Lock order is not documented.
- Safe modification: Keep `safe()` and `emergency()` outside `controller.lock`. Document the order in `keyboard.py`.
- Test coverage: `tests/test_keyboard.py` covers cancellation and release, not contention.

## Scaling Limits

**Single capture thread and single detector:**
- Current capacity: One capture loop; measured 6–7 processing FPS on saved frames (`docs/VERIFICATION.md`).
- Limit: Any detector cost above the frame budget reduces the effective decision rate, and the 500 ms guard stops combat rather than degrading gracefully.
- Scaling path: Separate capture, detection and input threads (see Tech Debt above), and benchmark per-stage timings in `/api/status`.

**Disk budget for recordings and artifacts:**
- Current capacity: `[recording] max_total_mb = 2048` and `max_age_days = 7` apply only to `data/recordings/session-*`. Current on-disk totals are about 478 MB (`data/`) and 449 MB (`artifacts/`), with no cap.
- Limit: Growth from screenshots, template sources and `.bak` files is unbounded.
- Scaling path: Extend the prune logic to `data/screenshots` and `data/templates/sources`, and cap backup counts.

## Dependencies at Risk

**OpenCV and NumPy pinned to narrow ranges:**
- Risk: `pyproject.toml` pins `opencv-python-headless>=4.13,<5`, `numpy>=2,<3` and `mss>=10,<11`. Behavior of `cv2.imdecodeanimation` (used in `src/maplebot/catalog.py`) is version-sensitive and was not checked against older builds.
- Impact: Catalog import fails with an `AttributeError`-style error on older OpenCV, which `import_catalog` does not catch (it catches `cv2.error`, not `AttributeError`).
- Migration plan: Catch `AttributeError` at the call site with a clear message, or document the minimum OpenCV version.

**Python 3.12-only runtime:**
- Risk: `pyproject.toml` requires Python 3.12 or newer. `install.ps1` hardcodes `py -3.12`.
- Impact: Other Python versions are blocked by design; no CI verifies the claim.
- Migration plan: Keep the constraint, and add a CI job or a `doctor` check that prints the interpreter version.

**Unofficial sprite API:**
- Risk: `https://api.dreamms.gg/api/GMS/latest` is a third-party service with no published SLA. The manifest hard-codes its URL pattern.
- Impact: Catalog refresh fails, and the bundled cache may stop matching the live game version (the README already notes this).
- Migration plan: Keep the offline cache as the source of truth. Make imports explicit rather than automatic.

## Missing Critical Features

**Potion usage is preview-only:**
- Problem: `PotionMonitor` (`src/maplebot/autopotter.py`) reads HP/MP and suggests potions, but never sends a potion key. The backlog entry (`docs/BACKLOG.md`) lists this as open.
- Blocks: Automatic healing during combat; any test that the bot survives longer than the current agent.

**No death, revival or inventory handling:**
- Problem: `README.md` lists "no ladder/path planning, autonomous jump actions, minimap reading, health/revival handling, damage OCR or reliable death classification".
- Blocks: Unattended sessions. The agent stops on uncertainty, so it cannot run past the first death or target loss.

## Test Coverage Gaps

**Debugger HTTP surface:**
- What's not tested: Token enforcement on POST, the Host header allow-list, 403 and 400 response paths, and the frozen-frame 404 path.
- Files: `src/maplebot/debugger.py`
- Risk: Auth regressions would not be caught. `tools/debugger_smoke.py` is a manual script, not a test.
- Priority: High

**Windows-specific code:**
- What's not tested: `Windows.get`, `Windows.list`, `Windows.unobscured` and `Win32Input.send` are only exercised by `tools/capture_smoke.py` and `tools/input_smoke.py`, which need a live desktop.
- Files: `src/maplebot/windows.py`, `src/maplebot/keyboard.py`
- Risk: DPI or structure-layout regressions would surface only on a real machine.
- Priority: Medium

**Configuration loading:**
- What's not tested: Config validation for `[perception]`, `[agent]`, unknown keys, and the `window_title` mismatch described above.
- Files: `src/maplebot/config.py`, `config.toml`
- Risk: The committed config drifts from code defaults without failing a test.
- Priority: High

**Live gameplay accuracy:**
- What's not tested: Player and monster detection, target association and attack outcomes on real MapleUnity frames. `docs/VERIFICATION.md` states that real sprite accuracy and native approach/attack remain unverified.
- Files: `src/maplebot/perception.py`, `src/maplebot/decision.py`
- Risk: Passing tests (124 at the time of this analysis) cover synthetic fixtures only.
- Priority: High

**Failure paths in the capture worker:**
- What's not tested: Recovery after `Capture.window` raises mid-session (calibration invalidation, `capture_verified` reset) and the worker-exit path in `_run`.
- Files: `src/maplebot/runtime.py`
- Risk: Regressions could leave input armed after capture is lost. `_run` calls `self.controller.stop` in `finally`, but no test asserts it.
- Priority: Medium

---

*Concerns audit: 2026-10-24*
