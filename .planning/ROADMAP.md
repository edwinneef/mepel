# Roadmap: Maple External Bot

## Overview

The existing bot captures the game, finds the player and monsters, and fights on one platform. This milestone turns it into a bot that grinds a whole taught screen under supervision without the operator touching it. First the decision loop becomes replayable and the input path non-blocking, with every key the bot will need, and every stop becomes safe and loud. Next the operator teaches the spot, and the bot proves on recordings, with no movement input, that it knows the spot and the player's platform. Then it keeps itself alive with potions, a skill attack with MP fallback, and pet feeding. Then it moves between platforms, checking each move on later frames. Last, it picks targets across the whole spot and recovers in place from knock-offs, stuck moves and lost targets within a fixed budget, with the debugger showing all of it.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Deterministic Input and Safe Stop** - Replayable capture-time decisions, non-blocking input with new keys, hold leases and ordered chords, and one safe, loud stop path
- [ ] **Phase 2: Spot Teaching and Localization** - Operator teaches the spot; on recordings the bot knows the spot and the player's platform, and it stops with the alarm when it loses track
- [ ] **Phase 3: Sustain** - Real HP/MP potions, skill attack with MP fallback, timed pet feeding, and alarm stops when potions or the pet fail
- [ ] **Phase 4: Verified Movement** - Route planning plus walk, climb, jump-up, drop-down and jump-off moves, each confirmed on frames after key release
- [ ] **Phase 5: Multi-Platform Grinding and Recovery** - Targets on any platform, bounded in-place recovery, full navigation overlay and run stats

## Phase Details

### Phase 1: Deterministic Input and Safe Stop

**Goal**: Every decision replays exactly from recorded frames, the bot can send every key it will need without stalling capture, and any stop releases the keys, saves the clip and sounds an alarm the operator must acknowledge.
**Depends on**: Nothing (first phase)
**Requirements**: FND-01, FND-02, FND-03, FND-04, FND-05, FND-06, SAFE-01, SAFE-02, SAFE-03
**Success Criteria** (what must be TRUE):
  1. Replaying a recorded session in policy-only mode reproduces every logged decision, and a deliberate policy change shows up as a reported difference.
  2. While a key is held, the debugger keeps receiving new frames and shows per-stage frame timing, and PNG encoding no longer appears in the capture worker's timing.
  3. Operator can bind and probe Up, Down, HP potion, MP potion, pet food and skill keys. Up reaches the game as the arrow key (not numpad 8), and Down+Jump and direction+Jump always arrive in their defined order.
  4. A held Up or Down is released within the fixed lease time once renewals stop, and the global per-action hold cap is unchanged.
  5. Every stop, including a crash of the capture worker, releases all keys, saves the incident clip and shows a structured reason in the debugger. Alarm-level stops repeat a sound until the operator acknowledges it with the debugger button or F8, and pauses such as "no targets" stay silent.

**Plans:** 4 plans

Plans:
**Wave 1**
- [ ] 01-01-PLAN.md — Non-blocking serial input, complete bindings, vertical leases and ordered chords

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 01-02-PLAN.md — Capture-time PolicyInput replay, stable diffs and bounded frame encoding

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 01-03-PLAN.md — Idempotent safe stop, repeating alarm and dead-worker recovery

**Wave 4** *(blocked on Wave 3 completion)*
- [ ] 01-04-PLAN.md — Debugger timing, bounded probes, safe local install and operator acceptance

**Research flag**: Standard patterns (codebase fully mapped; Win32 extended keys and leases are documented). Decide during planning whether input moves to its own thread or stays synchronous with renewable leases.

### Phase 2: Spot Teaching and Localization

**Goal**: The operator teaches the grinding spot once. Still sending no movement input, the bot confirms it is on that spot, knows which platform or rope the player is on, and stops with the alarm when it loses track of the spot, the player, the HP/MP bars or the game window, or when the character dies.
**Depends on**: Phase 1 (capture timestamps for hysteresis and the 5 s timers; the safe stop and alarm)
**Requirements**: NAV-01, NAV-02, NAV-03, SAFE-04
**Success Criteria** (what must be TRUE):
  1. Operator can draw platforms, ropes/ladders, directed links (walk, climb, jump up, drop down, jump off a rope) with take-off ranges, portal zones and spot anchors on a frozen frame, and save them per spot. Saving rejects a layout with an unreachable platform or a rope that touches no platform.
  2. Bot refuses to arm unless the anchors confirm it is on the taught spot.
  3. On recorded sessions in capture-only mode, the debugger shows the platform or rope the player is on, or "unknown", without flickering, including on clips with ropes, screen edges and foreground grass.
  4. Bot stops with the alarm on death (HP 0 %), lost spot anchors, player unknown for more than 5 s, HP/MP unreadable for more than 5 s while armed, and lost focus or calibration. Each trigger is shown on a recording or a fault-injection test.

**Plans**: TBD
**UI hint**: yes
**Research flag**: Needed. Check whether the camera scrolls on the target spot before planning (this decides between screen and anchor-relative layout coordinates), how to choose anchors, and whether the minimap dot is a useful cross-check.

### Phase 3: Sustain

**Goal**: On the taught spot, the bot keeps HP, MP and the pet topped up while it fights on its current platform, and stops with the alarm when potions run out or stop working, or the pet disappears.
**Depends on**: Phase 2 (arming only on a confirmed spot, with the full set of alarm stops)
**Requirements**: SUST-01, SUST-02, SUST-03, SUST-04, SUST-05, SUST-06, SUST-07
**Success Criteria** (what must be TRUE):
  1. While armed, the bot presses the HP potion key below the HP threshold and the MP potion key below the MP threshold, HP first, each with its own cooldown. A potion press goes ahead of combat and cuts any key hold short.
  2. The debugger shows the HP and MP potion counts read from the quickslot. The bot stops with the alarm when a count reaches 0 or after 3 presses in a row that do not raise the bar, and stops at once when HP is still below the critical level (default 20 %) after a press.
  3. The bot attacks with the skill key, switches to the basic attack below the low MP mark and back above the high mark, and uses the basic attack while MP is unreadable.
  4. The bot presses the pet-food key only once the operator has set an interval, only while idle, and logs each feed. It stops with the alarm when the pet has not been seen near the player for the grace window.

**Plans**: TBD
**Research flag**: Partial. Measure on the target server: potion effect latency, how the quickslot shows counts (digit legibility at 1x, what it shows at 0), elixir cooldowns, pet hunger rate, and a reliable "pet near player" signal.

### Phase 4: Verified Movement

**Goal**: The bot travels between any two taught platforms by walking, climbing, jumping up, dropping down and jumping off ropes, and counts a move as done only when frames captured after the key release confirm it.
**Depends on**: Phase 1 (hold leases, ordered chords, non-blocking input), Phase 2 (layout and localization), Phase 3 (potions must be able to cut rope holds short before the bot moves armed)
**Requirements**: NAV-04, NAV-05, NAV-06, NAV-07
**Success Criteria** (what must be TRUE):
  1. In dry run, the debugger shows the cheapest route and the next move to a chosen taught platform and updates them as the player moves. No input is sent, and no unsent move is logged as a failure.
  2. Armed, the bot reaches a chosen platform using walk, climb, jump-up, drop-down and jump-off-rope moves. The decision log marks each move done only after confirmed frames captured after the key release show the player at the expected place.
  3. When a move leaves the player somewhere other than expected, the bot replans from the actual position instead of continuing the old route.
  4. The bot never presses Up inside a taught portal zone.
  5. Operator can run one taught link under supervision. The bot records its duration and outcome and uses the measured duration as that link's timeout.

**Plans**: TBD
**Research flag**: Needed. Measure live per move type: the key chords and timings, rope grab tolerance, climb speed, whether Up enters portals, Down at a rope top, landing slide, and how the tracker behaves on rope and drop frames. Build one move type at a time (walk, rope, drop, jump up, jump off).

### Phase 5: Multi-Platform Grinding and Recovery

**Goal**: The bot grinds the whole taught spot without the operator touching it. It picks targets on any platform and travels to them, recovers in place from knock-offs, stuck moves and lost targets within a fixed budget, and the operator can see all of it.
**Depends on**: Phase 4 (a working navigator to target and recover with)
**Requirements**: TGT-01, TGT-02, TGT-03, TGT-04, TGT-05, OPS-01, OPS-02
**Success Criteria** (what must be TRUE):
  1. The bot travels to and attacks monsters on other taught platforms, preferring its own platform and cheaper routes. It keeps a target until the target dies, is unseen for about 2 s, or a clearly better target appears on the bot's own platform.
  2. After a knock-off the bot replans from where it landed. When stuck it retries the move, then tries an alternative route, then stops. A lost target is dropped and the next one is picked.
  3. Once an incident has used 3 recovery attempts, or 5 attempts have happened within 2 minutes, the next recovery need stops the bot with the alarm.
  4. The debugger overlay shows the taught layout, the current platform or rope, the route, the current move and its deadline, the target and the recovery counter, and the decision log carries the same fields.
  5. A run-stats panel shows uptime, potions used per resource, feeds, recoveries by type and stops by reason.

**Plans**: TBD
**UI hint**: yes
**Research flag**: Standard patterns (planner penalties and recovery budget on top of a working Phase 4).

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Deterministic Input and Safe Stop | 0/4 | Planned | - |
| 2. Spot Teaching and Localization | 0/TBD | Not started | - |
| 3. Sustain | 0/TBD | Not started | - |
| 4. Verified Movement | 0/TBD | Not started | - |
| 5. Multi-Platform Grinding and Recovery | 0/TBD | Not started | - |
