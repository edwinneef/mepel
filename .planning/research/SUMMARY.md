# Project Research Summary

**Project:** Maple External Bot
**Domain:** Supervised, screenshot-in / keyboard-out grinding bot for one taught multi-platform screen of a MapleStory client (melee warrior, bot-friendly server, Windows 11, Python 3.12)
**Researched:** 2026-10-24
**Confidence:** MEDIUM (engineering findings HIGH; game-mechanic findings LOW to MEDIUM until checked on the target client)

## Executive Summary

This milestone turns a single-platform combat bot into one that navigates a taught screen, keeps itself alive, and fails loudly. Bots of this kind (auto-maple, nanpuhaha/maplebot) share three ideas: an operator-taught layout, graph search over it, and HP healing plus pet feeding. Where they fall short is in checking whether a move worked and in handling failure. This project's edge is a pure, replayable decision layer. Every move is verified on later frames, and anything the bot can't handle ends in a bounded safe stop with an alarm.

The recommended approach needs **no new runtime dependencies**. Use stdlib `heapq` Dijkstra over a dataclass platform/rope graph, `json` layout files, and `winsound` for the alarm, plus the NumPy/OpenCV/MSS already in use. Architecturally, keep `Agent.step` pure and deterministic. Feed it a logged `PolicyInput` (observation, HUD, anchor, capture timestamp, last action outcome). Split behaviors into proposers (Safety > Potion > Recovery > Upkeep > Combat/Navigation) and let a priority arbiter pick one per tick. Navigation is a Localizer, a Planner and a per-edge MoveExecutor (ALIGN → PERFORM → SETTLE → VERIFY). Recovery is replanning plus a bounded budget, not a separate mode.

The biggest risks are about timing, not features. At about 3 fps the bot can judge a move on a stale or mid-air frame. The 0.25 s hold cap blocks rope climbing, the blocking input path blinds capture during actions, and the tracker can stay at the old position during a drop. A layout stored in screen pixels drifts if the camera scrolls. Prevent these with a foundation phase that comes before any navigation code: capture timestamps, non-blocking input with per-kind renewable hold leases (never raise the global cap), ordered chord primitives, the extended-key scan-code fix, and worker-death-safe stopping. Several game facts are unverified and must be measured on the target client first: whether the camera scrolls, rope grab and drop-down chords, Up entering portals, potion effect latency, and quickslot icon behavior at 0.

## Key Findings

### Recommended Stack

No new runtime dependencies. Keep OpenCV pinned `<5`. OpenCV 5.0 exists, but nobody has checked the detector thresholds against it, so upgrade later in its own phase behind replay benchmarks. Measurements show capture is not the bottleneck. MSS takes 17–21 ms at 1366x768, while two PNG encodes per frame on the worker cost about 64 ms. Fix them in this order: profile, take PNG encoding off the worker, limit template search to ROIs, and only then consider dxcam. See STACK.md.

**Core technologies:**
- `heapq` + `dataclasses` + `json` (stdlib): layout graph, Dijkstra and persistence. The graph has fewer than 20 nodes, and the edge semantics (failure penalties, take-off zones) are custom anyway.
- `winsound` (stdlib): looping async alarm (`SND_FILENAME|SND_ASYNC|SND_LOOP`, stop with `PlaySound(None, 0)`), with `MessageBeep` as fallback. Called from the runtime only.
- Existing Win32 SendInput: add up/down/Insert/Home/PgUp/digits/letters/F-keys to `KEYS`. **Critical bug:** the `EXTENDEDKEY` flag is set only for left/right, so Up is sent as numpad 8. Use the full Microsoft extended-key set.
- Existing OpenCV/NumPy: anchor patches, optional climbing-pose and quickslot-icon templates, masked `matchTemplate`.
- `pyinstrument` (dev extra only): profile a replay run before any speed work. `dxcam` 0.3 is optional, deferred, and would sit behind a config switch.

### Expected Features

**Must have (table stakes):**
- Safe stop with a repeating alarm, structured stop reasons and two severities (pause without alarm, stop with alarm until acknowledged). Build it first, because every other feature adds stop reasons to it.
- Real HP/MP potions: separate thresholds (50/30 %), a cooldown per resource (the current preview shares one), priority over combat, an effect check after each press (+3 pp within about 2 s), a stop after 3 ineffective presses, a critical-HP stop, and HP 0 treated as death.
- Skill attack with MP hysteresis fallback (basic attack below 10 %, skill again above 15 %; basic when MP is unreadable).
- Timed pet feeding through a generic timed-key scheduler. The operator must set the interval (no hidden default). Feed only when idle.
- Layout teaching on a frozen frame (platforms, ropes, directed links with take-off x-ranges), spot anchors and an identity check, localization with hysteresis, route planning.
- Verified movement primitives: walk, grab and climb a rope, jump up, drop down, jump off a rope. Each one acts, then waits for the expected localization change before a deadline. Includes dry run.
- Multi-platform targeting with commitment: pick a destination platform first, then a specific monster on arrival.
- Bounded recovery: replan after a knock-off, stuck → retry → alternative route → stop, drop a lost target. Budget of 3 attempts per incident and about 5 per 2 minutes.
- Navigation overlay and decision-log fields.

**Should have (differentiators):**
- Supervised "test this link" with measured durations and per-edge reliability. Strong candidate for v1, because otherwise primitive timeouts are guesses.
- Buff entries in the timed-key scheduler, an idle home or patrol node, a run-stats panel, distinct alarm sounds per category.
- Pet presence check and quickslot icon check. Pitfalls research argues the icon check belongs in v1 as the main out-of-potion and wrong-slot signal.

**Defer (v2+):**
- Quickslot count OCR, death or map-change recovery, minimap or multi-screen navigation, movement tricks (mid-air rope catch), and anything humanization or "anti-detection" (excluded by policy).

### Architecture Approach

Keep `Agent.step(observation, now)` as the single pure entry point. Behind it, add four pure modules in the existing flat package: `layout.py` (taught data, validation, version hash), `localize.py` (node classification with hysteresis), `navigation.py` (Dijkstra, MoveExecutor, Navigator with edge penalties) and `scheduler.py` (Proposal, Arbiter, Potion/Upkeep/Recovery/Safety behaviors). Today's FSM becomes `CombatBehavior`. Behaviors read time only through the capture `now`, and the policy uses no randomness. Log `PolicyInput`, `Decision` and `agent.snapshot()` every frame so the new policy-only replay can diff decisions exactly. A test-only kinematic simulator (`tests/sim.py`) covers the closed loop that recorded frames can't.

**Major components:**
1. **Layout + SpotAnchor:** taught graph in spot/world coordinates, re-registered each frame against 1–3 static anchor patches. Losing the anchors means an unexpected screen or map change, which stops the bot.
2. **Localizer:** player feet → `on_platform(id)` / `on_rope(id)` / airborne / unknown, plus monster → platform assignment.
3. **Navigator / MoveExecutor:** replans every tick from the actual node. Each edge has named outcomes (done, no effect, diverted, timeout). Dry run (`NOT_SENT`) never counts as a failure.
4. **Behaviors + Arbiter:** fixed priorities. A PERFORM chord in progress is never cut except by Safety. Upkeep has a soft due time and a hard deadline.
5. **Runtime adapter:** the only I/O. It runs actions, turns controller results into `ActionOutcome`, plays the alarm, and handles recording.

### Critical Pitfalls

1. **Verifying moves on stale or mid-action frames.** Stamp observations with the capture time. Judge a move only on frames captured after key-up plus a settle time, and require two consecutive confirmed frames for success. Express windows in seconds with a minimum frame count.
2. **The 0.25 s hold cap and blocking input don't allow climbing.** Never raise `max_action_seconds` globally. Use per-kind renewable leases (a dead-man switch, at least 2x the p95 frame time) for Up and Down, only inside taught rope zones. Re-check the focus and safety gate on every renewal. Take input off the capture thread so frames keep coming during holds.
3. **Tracker stays at the old position, or drifts onto a monster tag, during fast moves.** Give the tracker the move's expected corridor, require confirmed (not tracked-only) evidence for any success or failure verdict, and teach climbing poses.
4. **Screen-pixel layout while the camera scrolls.** Store the layout relative to anchors and re-register absolutely rather than summing `camera_shift`. Bind the layout to calibration geometry and refuse to arm on a mismatch. Check whether the spot scrolls at all before designing navigation.
5. **Chord order and Up/Down side effects.** Use ordered chord primitives (Down before Jump), with jitter allowed only inside the ordering constraints, and seeded order tests. Teach forbidden-Up (portal) zones, because Up enters portals. Validate drop links (no solid floors, not next to a rope top).
6. **Potion and safe-stop failures.** Potions must interrupt holds. "Bar didn't rise" alone gives false out-of-potion stops during heavy damage, so measure the rise against the trend over several presses and add the quickslot icon check. Make `safe_stop` idempotent and callable from any thread, including the worker's `finally`. The alarm runs on its own thread, starts after the keys are released, and outlives a dead worker.

## Implications for Roadmap

The research files suggest slightly different orders. This order reconciles them: architecture's build order, with the pitfalls' requirement that the foundation (non-blocking input, leases, chords, worker-death stop) comes first.

### Phase 1: Determinism and Input Foundation
**Rationale:** Every later timer, verify window and replay depends on it. It touches the safety-critical controller, so do it alone. Retuning navigation after moving input off-thread would cost a lot.
**Delivers:** Capture-time `now` passed to `step`. `PolicyInput`, `ActionOutcome` feedback, an expanded recorder line, policy-only replay with a diff. Extended `KEYS`/`ACTIONS` (up/down/potion/pet/skill) with the extended-key flag fix and new control probes. `Action.holds` ordered chord primitives. Per-kind hold leases on the watchdog. Input moved off the capture thread. Worker-death → safe-stop path. Per-stage timing and PNG encoding taken off the worker.
**Addresses:** prerequisites for every feature.
**Avoids:** Pitfalls 1, 2, 5, the worker-death part of 12, and the PNG performance trap.

### Phase 2: Safety Stop and Alarm
**Rationale:** Low cost, high value. Every later feature adds stop reasons, and the bot must not move between platforms without it.
**Delivers:** Central idempotent `safe_stop(reason, severity)`, a `winsound` alarm on its own thread that repeats until acknowledged, structured stop reasons in the debugger, a fault-injection test suite.
**Avoids:** Pitfall 12, alarm fatigue.

### Phase 3: Arbiter, Potions, Skill Fallback, Pet Timer
**Rationale:** Doesn't depend on navigation, and works on the existing single-platform combat. Proves the arbiter early.
**Delivers:** `CombatBehavior` refactor, arbiter, `HudReader` split, real potion keys with per-resource cooldowns, preemption, effect check, quickslot icon check and out-of-potion stop. Skill/basic hysteresis. Generic timed-key scheduler with pet food and persisted `last_fed_at` or a prompt at start. Rule: bot potions and the in-game pet auto-pot are mutually exclusive.
**Avoids:** Pitfalls 8 and 9.

### Phase 4: Layout Teaching, Anchors, Localization
**Rationale:** Highest perception risk. Prove it on recordings in capture-only mode before any movement code exists. Can run in parallel with Phases 2–3.
**Delivers:** `layout.py`, a canvas teaching UI (platforms, ropes, links, forbidden-Up zones, anchors), save-time validation, SpotAnchor, the Localizer with hysteresis, monster → platform assignment, the navigation overlay, a "does this spot scroll" check.
**Avoids:** Pitfalls 4 and 6 (zones and links).

### Phase 5: Movement Primitives and Simulator
**Rationale:** The critical path. Needs Phases 1 and 4. Build one edge kind at a time: walk → rope grab/climb → drop down → jump up → jump off.
**Delivers:** Planner, MoveExecutor, `tests/sim.py`, move-aware tracking corridors, climbing-pose templates, labeled rope and drop replay clips, noise-floor measurement, dry run then armed per edge kind. Optionally test-this-link.
**Avoids:** Pitfalls 1, 3, 5, 6 and 13.

### Phase 6: Multi-Platform Targeting and Recovery
**Rationale:** Thin layers on a working Navigator.
**Delivers:** Platform-level target selection with hysteresis and route commitment, edge failure penalties, the recovery budget, knock-off replan, per-intent stuck detection, a "controls not reaching game" stop, recovery counters in the status view.
**Avoids:** Pitfalls 7, 10 and 11.

### Phase Ordering Rationale

- The foundation comes first because the pitfalls research rates retrofitting non-blocking input and timestamps HIGH cost once navigation is tuned.
- Safety and resources ship before navigation, so the bot can survive and fail loudly on the existing single platform before it gets new ways to fail.
- Layout and localization are proven offline on recordings before any movement input is sent, in line with the project's capture-only default.
- Recovery is mostly replanning, so it comes after the Navigator rather than as its own system.

### Research Flags

Needs `/gsd-plan-phase --research-phase`:
- **Phase 4:** whether the camera scrolls (this decides the data model), anchor selection, minimap dot as a cross-check.
- **Phase 5:** live chords and timings per edge kind, rope grab tolerance, climb speed, whether Up enters portals, Down at a rope top, landing slide, tracker behavior on rope and drop frames.
- **Phase 3 (partial):** potion effect latency on this server, quickslot icon at 0, elixir cooldowns, pet hunger rate.

Standard patterns (skip research):
- **Phase 1:** the codebase is fully understood. Win32 extended keys and leases are well documented.
- **Phase 2:** stdlib `winsound`, an idempotent stop function.
- **Phase 6:** standard planner and penalty logic once Phase 5 works.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions checked against PyPI; capture and encode timings measured on this PC; stdlib and Microsoft docs |
| Features | MEDIUM | Comparable bots document little; default values are engineering judgment (LOW-MEDIUM) |
| Architecture | HIGH (integration) / MEDIUM (movement) | Based on reading the code directly; MapleStory movement specifics need live checks |
| Pitfalls | HIGH (engineering) / LOW-MEDIUM (game) | Engineering pitfalls come from the code; game claims come from fan wikis marked "verify in-game" |

**Overall confidence:** MEDIUM

### Gaps to Address

- **Does the camera scroll on the target spot?** Check existing recordings or walk the spot in capture-only mode before planning Phase 4.
- **Chords and mechanics** (rope grab, drop-down, jump-off, portals on Up, knock-off from ropes): measure live in capture-only or dry-run mode during Phase 5 research.
- **Potion effect latency, and quickslot icon behavior when a stack runs out:** measure before fixing the effect window and stop rule values.
- **Death and unexpected-screen pixel signals** (tombstone, dialog, fade to black): Safety needs at least one cheap heuristic for each.
- **Input-thread design vs "one bounded chord per tick".** ARCHITECTURE.md keeps the synchronous loop; PITFALLS.md asks for an input thread. Recommendation: renewable leases on the watchdog, with input off the capture thread. Settle this in Phase 1 planning.
- **Pet interval and hunger rate:** set by the operator; no reliable default exists.

## Sources

### Primary (HIGH confidence)
- Project code: `runtime.py`, `keyboard.py`, `decision.py`, `autopotter.py`, `perception.py`, `replay.py`, `recorder.py`, `config.toml`, `.planning/codebase/CONCERNS.md`
- Local benchmarks (MSS vs dxcam, PNG vs JPEG) and the PyPI JSON API, queried 2026-10-24
- docs.python.org/3.12 winsound; Microsoft keyboard-input docs (extended keys, scan codes)

### Secondary (MEDIUM confidence)
- auto-maple and nanpuhaha/maplebot READMEs (feature landscape, layout and A* design)
- MeowDB Classic item DB (pet auto-pot, pet food, elixir cooldown)

### Tertiary (LOW confidence)
- MeowDB movement guide and pet formulas, StrategyWiki (rope, portal and drop mechanics, pet going home), MapleMate marketing, OpenCV 4→5 community migration wiki, HFSM and behavior-tree papers

---
*Research completed: 2026-10-24*
*Ready for roadmap: yes*
