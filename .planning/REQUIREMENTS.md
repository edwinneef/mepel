# Requirements: Maple External Bot

**Defined:** 2026-10-24
**Core Value:** On a taught spot, the bot keeps grinding without the operator touching it. Anything it cannot handle ends in a safe stop: keys released, the clip saved, and an alarm sound.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Foundation

- [ ] **FND-01**: Every decision, timer and move check uses the frame's capture timestamp. A recorded session replays to identical decisions, and policy-only replay reports any difference.
- [ ] **FND-02**: Keyboard actions no longer block capture: frames keep arriving while a key is held.
- [ ] **FND-03**: Operator can bind and probe Up, Down, HP potion, MP potion, pet food and skill keys. Extended keys (arrows, Insert, Delete, Home, End, PgUp, PgDn) are sent with the extended flag.
- [ ] **FND-04**: Bot can hold Up/Down for climbing as a lease it renews on each frame that confirms the climb. The keyboard controller releases it within a fixed time if renewals stop. The global per-action cap stays.
- [ ] **FND-05**: Down+Jump and direction+Jump are sent as ordered key combinations that timing jitter cannot reorder.
- [ ] **FND-06**: Operator can see per-stage frame timing in the debugger, and PNG encoding no longer runs on the capture worker.

### Safety

- [ ] **SAFE-01**: Every stop releases all keys, saves the incident clip and shows a structured reason in the debugger.
- [ ] **SAFE-02**: Alarm-level stops play a sound on the PC that repeats until the operator acknowledges it (debugger button or F8). Pauses such as "no targets" stay silent.
- [ ] **SAFE-03**: If the capture worker crashes, the bot still releases keys and sounds the alarm.
- [ ] **SAFE-04**: The bot stops with the alarm on: death (HP 0 %), spot anchors lost (map change or unexpected screen), player unknown for more than 5 s, HP/MP unreadable for more than 5 s while armed, and focus or calibration lost.

### Sustain

- [ ] **SUST-01**: Bot presses the HP potion key below the HP threshold and the MP potion key below the MP threshold. Each resource has its own cooldown, HP comes before MP, and potions take priority over combat and holds.
- [ ] **SUST-02**: Bot checks that each potion press raised the bar, and stops with the alarm after 3 presses in a row with no effect.
- [ ] **SUST-03**: Bot stops at once if HP is still below the critical level (default 20 %) after a press.
- [ ] **SUST-04**: The debugger shows the HP/MP potion counts read from the quickslot, and the bot stops with the alarm when a count reaches 0.
- [ ] **SUST-05**: Bot attacks with the skill key. It switches to the basic attack below a low MP mark and back above a high mark, and uses the basic attack while MP is unreadable.
- [ ] **SUST-06**: Bot presses the pet-food key at an interval the operator must set, only while idle, and logs each feed.
- [ ] **SUST-07**: Bot stops with the alarm when the pet has not been seen near the player for a grace window.

### Navigation

- [ ] **NAV-01**: Operator can teach a spot on a frozen frame: platforms, ropes/ladders, directed links (walk, climb, jump up, drop down, jump off a rope) with take-off ranges, portal zones where Up is never pressed, and spot anchors. The layout is saved per spot and checked on save: every platform reachable, every rope touching a platform.
- [ ] **NAV-02**: Bot uses the anchors to confirm it is on the taught spot, and refuses to arm otherwise.
- [ ] **NAV-03**: The debugger shows which platform or rope the player is on (or "unknown"), without flickering.
- [ ] **NAV-04**: Bot plans the cheapest route to any taught platform and replans whenever the player's position changes.
- [ ] **NAV-05**: Bot can walk, climb ropes, jump up, drop down and jump off ropes. A move only counts as done when confirmed frames captured after the key release show the player at the expected place.
- [ ] **NAV-06**: Dry run shows the planned route and next move without sending input, and never counts unsent moves as failures.
- [ ] **NAV-07**: Operator can test one taught link under supervision. The bot records its duration and outcome and uses the measured duration as that link's timeout.

### Targeting & Recovery

- [ ] **TGT-01**: Bot picks targets on any taught platform, preferring the current platform and cheaper routes. It keeps a target until it dies, is unseen for about 2 s, or a clearly better target appears on its own platform.
- [ ] **TGT-02**: When knocked off a platform, the bot replans from wherever it landed.
- [ ] **TGT-03**: When stuck, the bot retries the move, then tries an alternative route, then stops.
- [ ] **TGT-04**: When the target is lost, the bot drops it and picks the next one.
- [ ] **TGT-05**: Recovery attempts are capped at 3 per incident and 5 per 2 minutes. Past either cap, the bot stops with the alarm.

### Operator Visibility

- [ ] **OPS-01**: The debugger overlay shows the taught layout, the current platform or rope, the route, the current move and its deadline, the target and the recovery counter. The same fields are written to the decision log.
- [ ] **OPS-02**: A run stats panel shows uptime, potions used per resource, feeds, recoveries by type and stops by reason.

## v2 Requirements

Deferred to a future release. Tracked but not in the current roadmap.

(None. Every table-stakes feature is in v1; unselected differentiators are listed under Out of Scope.)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Buff timers (Rage, Iron Body, …) | Not selected for v1; the timed-key scheduler built for pet food can add them later |
| Per-link reliability learning | Not selected for v1; "test this link" covers link timing |
| Idle home platform / patrol | Not selected for v1 |
| Quickslot potion icon check | Not selected for v1; reading the potion count (SUST-04) covers running out |
| A different alarm sound per stop reason | Not selected for v1; one repeating alarm is enough under supervision |
| Game's pet auto-potion skill | The bot presses potions itself; both at once would defeat the press-effect check |
| Memory, packet or client-file reading; injected code | Screenshot-in, keyboard-out design |
| Hiding software input, anti-cheat evasion, humanization for detection avoidance | The server allows bots; excluded by policy, and it would break deterministic replay |
| Gameplay input on official or bot-banning servers | Only the bot-friendly server gets input; capture-only stays available everywhere |
| Minimap / multi-screen navigation | v1 covers one taught screen |
| Automatic terrain / rope detection | Unreliable over foreground grass and clouds; the operator teaches the layout instead |
| Death or map-change recovery, relog, restock, channel change | v1 is supervised; these stop with the alarm |
| Phone or remote notifications | A sound on the PC is enough for supervised play |
| Loot key | The pet auto-loots |
| Unlimited recovery retries | They hide real faults and burn potions; recovery is capped (TGT-05) |
| Movement tricks (mid-air rope catch, jump boost) | Need frame-precise timing that 3 fps can't give |
| Opening pet or inventory windows to check their state | They cover the game view and break perception |
| Ranged / mage attack styles | The character is a melee warrior |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 1 | Gaps Found |
| FND-02 | Phase 1 | Gaps Found |
| FND-03 | Phase 1 | Gaps Found |
| FND-04 | Phase 1 | Gaps Found |
| FND-05 | Phase 1 | Gaps Found |
| FND-06 | Phase 1 | Gaps Found |
| SAFE-01 | Phase 1 | Gaps Found |
| SAFE-02 | Phase 1 | Gaps Found |
| SAFE-03 | Phase 1 | Gaps Found |
| SAFE-04 | Phase 2 | Pending |
| SUST-01 | Phase 3 | Pending |
| SUST-02 | Phase 3 | Pending |
| SUST-03 | Phase 3 | Pending |
| SUST-04 | Phase 3 | Pending |
| SUST-05 | Phase 3 | Pending |
| SUST-06 | Phase 3 | Pending |
| SUST-07 | Phase 3 | Pending |
| NAV-01 | Phase 2 | Pending |
| NAV-02 | Phase 2 | Pending |
| NAV-03 | Phase 2 | Pending |
| NAV-04 | Phase 4 | Pending |
| NAV-05 | Phase 4 | Pending |
| NAV-06 | Phase 4 | Pending |
| NAV-07 | Phase 4 | Pending |
| TGT-01 | Phase 5 | Pending |
| TGT-02 | Phase 5 | Pending |
| TGT-03 | Phase 5 | Pending |
| TGT-04 | Phase 5 | Pending |
| TGT-05 | Phase 5 | Pending |
| OPS-01 | Phase 5 | Pending |
| OPS-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 31 total
- Mapped to phases: 31
- Unmapped: 0 ✓

---
*Requirements defined: 2026-10-24*
*Last updated: 2026-10-24 after roadmap creation*
