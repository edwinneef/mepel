# Maple External Bot

## What This Is

A Windows desktop bot that plays a melee (warrior) character on a MapleStory server whose rules allow bots. It only reads screenshot pixels and sends ordinary keyboard input. It grinds one taught spot: a single screen with a few platforms linked by ropes, ladders and ledges. It moves between those platforms, attacks with a skill, keeps HP/MP up with potion keys, and keeps the pet fed so pet auto-loot works. The operator supervises it from a local web debugger, which also records every incident for offline replay.

## Core Value

On a taught spot, the bot keeps grinding without the operator touching it. Anything it cannot handle ends in a safe stop: keys released, the clip saved, and an alarm sound.

## Requirements

### Validated

<!-- Inferred from the existing codebase (see .planning/codebase/). -->

- ✓ Window capture: attach to a window or a manual screen region, crop and calibrate the game view, with DPI-aware physical pixels and per-thread Per Monitor V2 awareness. Moving or resizing the window invalidates the calibration. — existing
- ✓ Local web debugger on 127.0.0.1: live annotated view, freeze-and-select, template teaching, status and decision history. — existing
- ✓ Capture-only session mode, in which no keyboard backend is constructed at all. — existing
- ✓ Bounded keyboard input through Win32 SendInput, with these gates: focus, obscuration and verified calibration; the F8 emergency stop; a stale-hold watchdog; a three-second focus countdown; and four control probes the operator confirms by watching them. — existing
- ✓ Monster detection from a cached public sprite catalog (12 classic species) plus taught examples, with a color-index proposal step and masked verification. — existing
- ✓ Player detection that survives gear changes, ropes, edges and partial cover. It combines taught sprites, the name tag (matched on glyph shape), in-memory sprite snapshots, and a tracking chain that accepts partial evidence near the last position for up to 5 s. — existing
- ✓ Single-platform combat state machine: target the nearest confident same-platform monster, approach, face, attack, and stop when there is no progress. It runs as a dry run or armed. — existing
- ✓ HP/MP bar reading and potion decision preview, with no potion keys sent yet. — existing
- ✓ Automatic incident recording: decisions are always logged; a 10 s frame buffer is flushed on stops, uncertain-player events or a manual clip; optional full recording; retention limited by size and age. — existing
- ✓ Offline replay and benchmarks over recorded frames, which never send input. — existing

### Active

- [ ] Operator can teach a spot's layout once: platforms, ropes/ladders, and jump-up / drop-down links, drawn on a frozen frame and saved per spot.
- [ ] Bot knows which taught platform the player is on, including on a rope, and plans a route to any other platform.
- [ ] Bot climbs ropes and ladders, jumps up to ledges and drops down through platforms, checking each move by watching the player's position.
- [ ] Bot picks targets across all taught platforms, not only the current one, and moves to reach them.
- [ ] Bot attacks with a configured skill key, with basic attack as fallback when MP is low.
- [ ] Bot presses real HP/MP potion keys when the bars drop below their thresholds. Potions take priority over combat, and the bot stops and alerts when potions run out (a press doesn't change the bar).
- [ ] Bot presses the pet-food key on a configurable timer.
- [ ] Bot recovers from being knocked off a platform, from no-progress / stuck states (try another route before stopping), and from a lost target.
- [ ] Every unrecoverable situation ends in a safe stop with an alarm sound on the PC. Examples: death, map change, unexpected screen, potions exhausted, repeated failed recovery.
- [ ] Recordings and the debugger show the navigation state: current platform, planned route and recovery attempts.

### Out of Scope

- Reading game memory, packets, client files or using injected code. The bot stays screenshot-in, keyboard-out, matching the existing design.
- Hiding that input comes from software, or evading anti-cheat. The target server allows bots, so this is unnecessary, and the project has always excluded it.
- Official Nexon servers or any server that bans bots. Gameplay input is only for servers whose rules permit it; capture-only stays available everywhere.
- Multi-screen or whole-map navigation using the minimap. v1 covers one screen with a few platforms.
- Automatic terrain detection. The operator teaches the layout instead, because that is more reliable.
- Fully unattended multi-hour runs, and recovering from death or map changes (respawn, walking back, restocking). v1 is supervised; these stop and alert.
- Phone or remote notifications. A sound on the PC is enough for supervised play.
- Picking up loot with a key. The pet auto-loots.
- Ranged and mage attack styles. The character is a melee warrior.

## Context

- This is a brownfield Python 3.12 project for Windows 11. The codebase map is in `.planning/codebase/`: one capture worker thread runs capture → perception → decision → input, with the localhost debugger as its control surface (`src/maplebot/runtime.py`).
- It was first built against MapleUnity, an offline Unity re-implementation, which didn't look right. It is moving to a MapleStory client on a server that allows bots. The target window title is `MapleStory` (`capture.window_title`). The README's MapleUnity setup section and `docs/VERIFICATION.md` still describe the old target.
- Live recordings on the new client showed what is hard in real play: foreground grass and brambles hide the player and the name tag, monster name tags overlap the player's, the translucent tag box turns light over clouds, and the player is sometimes at the screen edge. Player detection was hardened for all of these.
- Processing takes about 250–400 ms per frame (2.5–4 fps), against 12 fps configured. Movement checks and timing have to work at that rate, or capture has to get faster.
- The current agent only knows a single platform and left/right/attack/jump. Potion use is preview-only. `docs/BACKLOG.md` already outlines the autopotter.

## Constraints

- **Tech stack**: Python 3.12+, OpenCV, NumPy, MSS, Win32 SendInput, and a stdlib HTTP debugger. Stay within the existing stack and patterns.
- **Platform**: Windows 11 only, Per Monitor V2 DPI awareness, 1x native game pixels.
- **Safety**: All input goes through `KeyboardController` with its focus, calibration, watchdog and emergency-stop gates. Any uncertainty releases keys. Arming still requires a confirmed player and confirmed control probes.
- **Server policy**: Gameplay input is allowed only on the bot-friendly server. Capture-only remains the default launch mode.
- **Performance**: Decisions must stay correct at about 3 fps until capture gets faster.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Target the MapleStory client, not MapleUnity | MapleUnity didn't look like the real game; the new server permits bots | — Pending |
| The operator teaches each spot's layout instead of terrain auto-detection | Reliable and inspectable; only one spot is needed | — Pending |
| Pet auto-loot instead of a loot key | No drop detection needed; only pet feeding | — Pending |
| v1 is supervised; unrecoverable cases stop with an alarm sound | Smaller scope; safe failure matters more than autonomy | — Pending |
| Recover in place only: knock-off, stuck, lost target, hidden player | The cases the bot can fix on its own screen; death and map change are out of scope | — Pending |
| Name tag plus tracking chain for the player position (5 s cap) | Survives gear changes, ropes, grass and overlapping tags in live recordings | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-24 after initialization*
