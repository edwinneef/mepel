# Verification — 2026-10-23

## Environment observed

- Windows 11, build 26200; Python 3.12.10.
- OpenCV 4.14.0, MSS 10.2.0, NumPy 2.5.4 installed in the project `.venv`.
- Two 2560 × 1440 monitors; combined desktop 5120 × 1440.
- No running Unity/UnityHub process and no matching MapleUnity window were found. No executable build was assumed or created. No game project was modified.

## Measured results

| Check | Evidence | Result |
| --- | --- | --- |
| Real Windows capture of our own test window | `artifacts/capture-smoke.json`, `capture-smoke.png` | 20 frames at 1024 × 768; red/blue pixel assertions passed; 200 × 150 crop passed; resize invalidated calibration |
| Capture timing, without pacing | Same JSON | Mean 18.297 ms, 54.65 capture FPS; includes window geometry checks, excludes detector/debugger |
| Ordinary external keyboard mechanism | `artifacts/input-smoke.json` | Own temporary Tk window received Left, Right, Z and Space down/up in order; Unity acceptance remains unverified |
| Generated replay benchmark | `artifacts/synthetic/results/metrics.json` | 60 generated 1024 × 768 frames; 3.81 processing FPS; mean 262.521 ms, p95 296.236 ms |
| Decision latency | Same JSON | Mean 0.0452 ms on generated replay |
| Detection on generated exact templates | Same JSON and `artifacts/synthetic/labels.json` | Player TP 60 / FP 0 / FN 0; monster TP 114 / FP 0 / FN 0; this is synthetic self-consistency, not real sprite accuracy |
| Target acquisition in generated replay | Same JSON | 1 acquisition / 2 SEARCH attempts, rate 0.5; second attempt had no same-platform monster |
| State progression in generated replay | `artifacts/synthetic/results/replay-*.jsonl` | APPROACH, ATTACK, VERIFY, SEARCH and IDLE observed; no input sent; no kill claimed |
| Browser debugger | Temporary own-window fixture on port 8766 | Live screenshot and player/monster/target annotations displayed; Freeze switched to capture-only mode; desktop 1280 × 800 and mobile 390 × 844 had no horizontal overflow |
| Automated tests | `python -m pytest -q` | 44 passed: detection, mirrored sprites, ambiguity, low confidence, target selection, direction, state transitions, missing targets, stalled approach, camera movement, calibration, focus/visibility/DPI gates, emergency stop, release, canceled commands and offline replay |

The native smoke windows used 96 DPI. Higher-DPI coordinate math is covered offline, but actual rendering/capture on a scaled monitor is unverified. Actual capture/processing rates vary with window size, template count, CPU load and recording.

## Milestones

1. **Capture/calibration/debugger:** implemented; real MSS pixels, crop, resize detection and debugger rendering verified against our own temporary windows. MapleUnity's exact Game-view crop still needs a live check.
2. **Player/monster detection:** implemented and tested on generated screenshots only. No real MapleUnity sprite examples were available; real detection acceptance remains open.
3. **Keyboard control:** Win32 scan-code mechanism verified against our own receiving window. Focus gates, watchdog and cleanup tested. Unity Game-view acceptance and actual control bindings remain open.
4. **Single-platform combat:** state machine and dry/replay behavior tested. A native MapleUnity approach/attack has not been observed; initial success criterion remains open.
5. **Offline tests/metrics:** implemented and measured. Real gameplay accuracy and effectiveness require labeled live captures.

## Remaining live acceptance

Use README's calibration and control workflow with the existing MapleUnity Editor project. First verify capture with no combat. Then collect tight player/monster examples and inspect dry-run boxes. Finally perform the four bounded control probes and one approach/attack run. Stop after the first visible attempt and inspect the evidence; do not infer success from the sent-key log. No new game install, internal inspection or recording of unrelated applications is required.

The program is installed locally and starts with all gameplay input disabled. Templates and screenshot data are user-owned local files. Capture/control verification must be repeated in each new session.

## Input realism update — 2026-10-24

- Added configurable software timing variation, independently timed overlapping holds, selective releases and key-down staggering. Timing is separate from the backend and deterministic decision logic.
- `python -m pytest -q`: **66 passed**. New coverage includes bounded/nonconstant timings, reproducible seeds, exact timing mode, compatible overlap, duplicate/opposite-key rejection, independent releases, cancellation during reaction delay, focus/emergency cleanup with multiple held keys and application-level backend replacement.
- Ruff lint and format checks passed. The decision module was unchanged by this update.
- Native receiving-window smoke was attempted twice. Windows kept another application foreground, so the existing focus gate refused to enable the temporary smoke receiver before sending any key-down. The new overlap behavior is verified with recording test backends, **not yet with a native receiving window or Unity**. No attempt was made to bypass the focus gate.
- The previous capture, native single-key and synthetic-replay numbers above remain historical measurements from 2026-10-23. They are not new timing-realism measurements or evidence of human-likeness.

The default backend remains ordinary Win32 software input. No hardware, input-origin concealment or anti-cheat bypass was added. The current combat agent still requests individual actions; intentional combinations are available to agent authors through `execute_sequence` without changing backend code.

The update was installed in the existing editable project environment and launched separately at `http://127.0.0.1:8766`, using `artifacts/input-realism.toml`. Its status endpoint returned capture/IDLE with input disabled. The existing debugger on port 8765 was left intact. No dependencies or saved capture/template data were changed.

## Player recognition after movement — 2026-10-24

The user-selected test-window screenshots reproduced a failure after a small movement. All three source examples matched themselves, but the moved character's frame had a best full-rectangle score of 0.7675 against the unchanged 0.90 threshold. The examples included background, a label and moving body parts, so full-rectangle matching treated changes outside the stable character appearance as identity changes.

The detector now derives a stable foreground component from each player example and verifies candidates using masked color/structure similarity. No example files, confidence thresholds or input restrictions were changed. The selected box remains the tracking box; reliable segmentation is not assumed for every sprite, and full-example matching remains the fallback.

Offline checks on the three original real screenshots and the failed frame detected the player in all four; the previously missed frame scored 0.960585. An edited negative frame with the character removed but scenery/nameplate retained returned no player. Observed detection times for this single pass were 157.57–198.89 ms; these are bounded observations, not general performance or accuracy claims. Evidence is under `artifacts/player-detection-investigation/`.

Regression coverage in `tests/test_perception.py` now includes changed backgrounds, walking legs, mirrored directions, player absence with retained scenery/label, and ambiguous foreground matches. Full suite: **70 passed**. Fix scope: `perception.py`, its existing test file and these usage/verification docs. The rest of the uncommitted project and user configuration were preserved; review was limited to the fix-owned lines.

Both debuggers were restarted with input disabled. The selected window and existing crop were restored, and all nine saved template/source files retained their original hashes. At the live deployment check the game window was covered by another application, so no player was detected, as expected for visible-screen capture. No keyboard input or forced focus change was used. Capture confirmation remains required after the restart; the existing crop can be reused.

## Automatic catalog enemies — 2026-10-24

Installed an offline reference catalog from the public [Dream MS image API](https://api.dreamms.gg/): 12 classic ground-monster species and 61 transparent stand/move frames. The importer requests names and images only, records image/source hashes and URLs, and caches repeat imports. Live detection does not contact the database or read game assets, coordinates, maps, stats or spawns. No vision model or external hardware was installed.

The detector uses native-pixel color signatures to propose positions, then verifies all opaque reference pixels with color/structural similarity. It generates both orientations and retains the existing confidence gate. Catalog appearance matching cannot guarantee hostility when a friendly entity uses identical artwork; unsupported types, scales or major color changes remain limitations.

`tools/benchmark_catalog.py` evaluated all 61 poses in both directions, composited onto a saved screenshot: **122 expected instances, 122 matches, zero extras/misses**. Three explicitly labeled town screenshots containing NPCs/players/pets produced **zero enemy detections** and retained player detection. This is reference self-consistency plus limited real negative evidence, **not native Hunting Ground accuracy**.

The latest measured 15-frame pass averaged **161.78 ms** (p95 **165.95 ms**), equivalent to **6.18 processing FPS**, excluding disk I/O and annotation. Metrics and per-frame results are under `artifacts/catalog-benchmark/`. Full suite: **80 passed**; coverage includes import/caching, provenance, unavailable animations, invalid images, hash tampering, no-network detection, transparency, both directions, multiple enemies and small color shifts.

The catalog status/species list was verified in the debugger at 1280×800 and 390×844 with no horizontal overflow or browser console errors. That temporary UI used a backend that rejects all keyboard events and was stopped afterward. The application update is installed, all original manual examples are preserved, and the project remains stopped as requested. A live Hunting Ground enemy check remains pending.

## Enforced capture-only testing — 2026-10-24

`run.ps1` now defaults to `debug --capture-only`. This session creates a disabled backend instead of an OS keyboard backend, ignores supplied input adapters, rejects probes/arming/control confirmation, and blocks controller enablement. Capture, calibration, template selection, recording and dry-run decisions remain available. The debugger displays **CAPTURE ONLY · INPUT LOCKED** and hides gameplay controls. Input capability requires a separate launch with `run.ps1 -EnableGameplayInput`; existing verification requirements still apply.

The new regression first failed because the capture-only entry point did not exist, then passed with the implementation. It exercises already-verified calibration, injected backends, direct backend/enable attempts, rejected gameplay commands, dry run and an invalid live-mode transition. Full suite: **81 passed**. Ruff check/format and `pip check` passed. A standard isolated-build installation dry run passed, followed by the editable local installation without dependency changes. An initial `--no-build-isolation` dry run could not import setuptools in the environment; build isolation resolved that packaging prerequisite.

At the user's request, verification used saved screenshots, with no live game capture or keyboard input. Three previously saved town scenes were copied into `artifacts/capture-only/saved-replay/frames`, retaining source-selected player boxes and explicitly empty enemy labels. Replay measured **3/3 player matches, zero false enemy detections**, mean **156.507 ms**, p95 **158.216 ms**, **6.39 processing FPS**, and `input_sent: false`. These frames contain NPCs, other players and pets, but no ground enemies: enemy recall and successful combat remain unmeasured. Metrics, decisions and annotated screenshots are under `artifacts/capture-only/saved-replay/results`.

The default launcher was started on port 8765 with no capture source attached. HTTP probes for `arm`, `probe` and `confirm_controls` all returned 400 with a capture-only error; `/api/status` reports the session lock even before the first frame. Browser inspection verified the lock, hidden controls, available dry run and no horizontal overflow at desktop and mobile widths. All **111 preexisting data files** retained their SHA-256 hashes, including calibration and templates. Evidence and process ownership are in `artifacts/capture-only/`; task-owned prior source copies were backed up there before editing.

Code review: skipped (ce-code-review unavailable) — its scope helper rejected the unborn Git checkout's missing HEAD, and all files are untracked. The attempt made no edits and did not expand scope. A local comparison against the task's saved baseline and the checks above supplied the final verification; no commit or PR was created.

## HP/MP autopotter preview — 2026-10-24

Added independent screenshot HUD measurement and potion-preview policy in `autopotter.py`. Calibration selects a full red HP or blue MP bar including its pale frame. The reader checks the saved HUD frame and capture dimensions, classifies fill/empty columns, and estimates the fill boundary. Confidence is a consistency score, not a probability. Two low observations are required, HP has priority, and a shared cooldown prevents repeated suggestions. Uncertain/covered HUDs, stale observations and an empty HP bar suppress suggestions. Disabled resources do not block active resources. Global STOP/F8 and calibration stop preview, and settings/restarts require starting it again.

This is **preview-only in every launch mode**. No potion key mapping or OS input execution was added. All potion statuses and replay records report `input_sent: false`; potion effects are never inferred from a suggestion. The existing capture-only backend and gameplay lock remain unchanged.

The new reader/policy tests first failed at import because the module did not exist. The final suite contains **102 passing tests**; new coverage includes fill percentages, confidence failures, cooldown, priority, recovery, empty HP, duplicate timestamps, settings/backups, disabled MP, browser-command integration, global stop/emergency and no-input replay. Ruff check/format and `pip check` passed. A dry-run editable installation passed, followed by the local installation without dependency changes.

All three original 1023×766 saved screenshots read **HP 100%, MP 100%**, matching their visible full bars and numbers. They do not establish low-health accuracy. An explicitly simulated eight-frame sequence altered only the bar interiors and included a covered frame: it produced **one HP suggestion and one MP suggestion**, retained the cooldown, and rejected the covered HUD. The simulated 20% HP read as 20.0%, and 10% MP as 9.8%. The replay measured mean **150.5 ms**, p95 **168.354 ms**, **6.64 processing FPS**, and no input. Evidence is under `artifacts/autopotter/real-saved-readings.json` and `artifacts/autopotter/simulated/`.

The browser panel was checked at 1280×800 and 390×844 with no horizontal overflow; defaults displayed 50%, 30%, and 1.5 seconds. Starting preview without a live verified screenshot returned the expected 400 response and left it stopped. HTTP checks rejected combat in capture-only mode and invalid thresholds. The former browser tab retained historical network errors during restart; a fresh tab had only the expected failed-start 400 response, with no script exception observed.

The installed capture-only debugger was restarted at port 8765 with no source attached and potion preview stopped. A combined restart command was rejected by automatic command review; separately validating ownership, stopping the known debugger, and starting the replacement succeeded. Existing calibration, screenshots, catalog and templates are unchanged: all **111 preexisting data-file hashes** matched. The only new installed data is `data/autopotter.json`, derived from the saved screenshot HUD; prior task-owned source copies are in `artifacts/autopotter/before-20261024-131719/`.

Live damaged/recovered HUD readings, alternative HUD layouts, actual potion bindings, inventory availability and potion effects remain unverified/unimplemented. No live game capture or gameplay input was used for this work.

## Status roll-up — 2026-11-02

The entries above are historical measurements from 2026-10-23/24 against a MapleUnity target.
The project now targets the MapleStory client on the bot-friendly server; live evidence is
recorded per topic under `docs/` and summarized here. Tests were not rerun for this entry.

| Area | Live evidence | Offline evidence |
| --- | --- | --- |
| Control probes, town movement | Accepted left/right/jump and ladder controls, 14/14 calibration pulses ([henesys-park-session.md](henesys-park-session.md), [town-validation.md](town-validation.md)) | `tests/test_town_check.py`, navigation harness |
| Single-platform combat | Supervised approach, skill use and operator-confirmed hit on 2026-10-28; a 32 s session ended with F8 ([single-platform-combat.md](single-platform-combat.md), [warrior-ranges.md](warrior-ranges.md)) | Policy replay of the saved sessions |
| Potions | One observed MP gain after a live potion ticket; HP recovery unverified ([passive-potion-evidence.md](passive-potion-evidence.md)) | `tests/test_autopotter.py`, `tests/test_potion_evidence.py` |
| Multi-platform farming, rotation, circuits | **No live acceptance** ([farming.md](farming.md), [BACKLOG.md](BACKLOG.md)); the floor-batch start control did not work on 2026-11-01 ([AGENTS.md](../AGENTS.md)) | `tests/test_farming*.py`, `tests/test_rotation.py` |
| Recording retention | Automatic deletion removed on 2026-11-01; nothing under `data/recordings` is pruned ([recording-preservation.md](recording-preservation.md)) | `tests/test_recorder.py` |

Test suite: 110 files under `tests/`. `docs/BACKLOG.md` records two tests that fail on a clean
HEAD (`tests/test_navigation_recovery.py::test_up_is_not_released_when_the_jump_ticket_completes`,
`tests/test_meowdb.py::test_classic_routes_replay_at_three_fps`). The local gate is
`tools/dev_cycle.ps1`; there is no CI. Unattended operation, the project's stated core value,
has not been demonstrated: every live batch still needs operator presence and explicit
authorization.
