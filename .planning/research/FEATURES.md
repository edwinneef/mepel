# Feature Research

**Domain:** Supervised, screenshot-driven grinding bot for one taught screen of a MapleStory client (melee warrior, bot-friendly server, Windows)
**Researched:** 2026-10-24
**Confidence:** MEDIUM. Game mechanics come from community wikis and guides (MEDIUM/LOW). The behavior and default values are engineering judgment based on the existing code (`src/maplebot/autopotter.py`) and the 3 fps constraint. Comparable open-source bots document very little about thresholds or recovery, so few numbers could be checked against them.

## How the comparable tools behave (context)

- **auto-maple** (tanjeffreyz, open source, modern GMS) reads the player position from the **minimap**. It runs operator-written CSV **routines**: Points with `move_tolerance`, `adjust`, `frequency` and `skip`, plus Labels and Jumps. A per-class "command book" defines skills and timing, and A* runs over a recorded quadtree layout. The README does not cover stuck handling, alarms or potion logic. Lesson: a taught layout and graph search are the accepted pattern. Fixed point-by-point routines are how that bot works, but they don't suit reactive knock-off recovery.
- **nanpuhaha/maplebot** (AutoIt) lists "HP detection and heal", "pet detection and feed", relog, reboot, chat-triggered CC/DC, and SMS/email/Twitter notifications and control. It gives no thresholds. Lesson: the features operators expect are HP healing, pet feeding and being alerted. The rest (relog, CC, remote control) belongs to unattended play, which is out of scope here.
- **MapleMate** (commercial, private servers) markets a CV "dynamic farmer" and a "shuffle mode" that rotates between paths "to bypass behavior tracking". That second feature is exactly the kind this project excludes (see Anti-Features).
- **In-game:** many versions sell pet **Auto HP/MP Potion** skills, which drink potions below a threshold you set. Pets that are not fed lose hunger until they reach 0, then lose a lot of closeness and **return to the inventory**, which ends auto-loot. **Overfeeding also lowers closeness.** Pet Food restores 30 fullness. Hunger rate differs by species.
- **Movement (community guides):** pressing Up in front of a rope or ladder grabs it. Down plus Jump drops through to a lower platform. You can jump off a rope sideways. Getting hit can knock you off ropes and platforms. Some servers give elixirs a shared 30 s use cooldown, while ordinary potions usually have none. This depends on the server, so cooldowns must be configurable per key.

## Feature Landscape

### Table Stakes (Users Expect These)

Without these, the bot cannot grind a multi-platform spot unattended.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Teach spot layout on a frozen frame** (platforms as horizontal segments, ropes/ladders as vertical segments, directed links: walk, climb-up, climb-down, jump-up, drop-down, jump-off-rope) | The operator teaches the layout instead of auto-detection (Key Decision). Nothing else in navigation works without it. | MEDIUM | Platform = `y`, `x_min..x_max`. Rope = `x`, `y_top..y_bottom`, plus which platform sits at each end. Each link has a source/destination and a **take-off x-range**. Drop-down must be marked explicitly per platform, because the bottom floor and some footholds don't allow it. Save per spot as atomic JSON with a `.bak`, the same way `autopotter.json` is saved. Validate on save: every platform must be reachable, and every rope must touch a platform. |
| **Spot identity check** | Without it, a teleport or map change could make the bot "navigate" on the wrong screen. | LOW-MEDIUM | Store 1–3 static background anchor patches with the layout. If they stop matching for about 2 s, treat it as a map change or unexpected screen and safe-stop. This also covers the "map change" stop condition. |
| **Localization: which platform/rope the player is on** | The route planner and recovery both depend on it. | MEDIUM | Match the feet position to the nearest platform within a y tolerance (a few px) and inside its x-range, or to a rope within an x tolerance. States: `on_platform(id)`, `on_rope(id)`, `airborne/unknown`. Use **hysteresis**: require 2 agreeing frames before switching. Treat `unknown` as "wait, don't act". Beyond the existing 5 s tracking cap, safe-stop. |
| **Route planning over the taught graph** | Needed to reach targets on other platforms. | LOW | Dijkstra/BFS over fewer than about 20 nodes. Edge cost = expected seconds, measured where possible. Replan every time the localized platform changes. |
| **Verified movement primitives** (walk-to-x, climb rope, jump-up, drop-down, jump off rope) | Every move must be checked by watching the player (Active requirement). At 3 fps, open-loop moves fail without anyone noticing. | HIGH | Pattern: **act, then wait for the expected localization change before a timeout.** Don't steer mid-air at 3 fps. Rope grab: line up x with short taps until the player is within tolerance, hold Up, and require `on_rope` within about 1 s. Climb: hold Up until `on_platform(top)` or a timeout derived from rope length. Drop-down: Down+Jump, then require a lower platform within about 1.5 s. Each primitive returns success / wrong-platform / no-change, which feeds recovery. Every hold goes through `KeyboardController` and its watchdog. |
| **Multi-platform target selection** | Melee on one platform clears it, then has nothing to do. | MEDIUM | Score = route cost to the monster's platform plus horizontal distance. Prefer the current platform, then the cheapest reachable one. **Commit** to a target until it dies, disappears for about 2 s, or a clearly better one appears on the current platform. Without commitment the bot oscillates at 3 fps. Ignore monsters that aren't on a taught platform. |
| **Skill attack with basic-attack fallback** | The warrior uses a skill key. Running out of MP must not stop the grind. | LOW | Config: `skill_key`, `basic_key`, `skill_min_mp_percent`. Use **hysteresis** (for example, switch to basic below 10 % and back to skill above 15 %) so it doesn't flip every frame. If the MP bar can't be read, use the basic attack. The skill's range and hitbox may differ from the basic attack, so make attack range configurable per attack. |
| **Real HP/MP potion presses with priority** | This is the main survival feature. Every bot of this kind has it. | MEDIUM | Separate HP and MP thresholds and keys. Keep the existing defaults of HP 50 % and MP 30 %. Require 2 stable readings (as the existing preview does). **Use a separate cooldown per resource.** The current preview shares one `cooldown`, so HP can be blocked by an MP press. Potions take priority over attacking. They run between primitives, never during a jump or drop-down hold. Pressing while on a rope is allowed in-game, but treat that as an option and test it. HP takes priority over MP. |
| **Out-of-potion / ineffective-press detection** | A bot that keeps pressing an empty slot dies (Active requirement). | MEDIUM | After a press, expect the bar to rise by at least about 3 percentage points within about 1.5–2 s (5–6 frames). Count consecutive presses with no effect. **Stop and alarm after 3 in a row.** Separately, if **HP stays below a critical level** (for example 20 %) after one press with no effect, stop at once. Damage taken at the same time can hide a heal, so measure the rise against the lowest reading since the press. Don't use the instant value. An HP bar reading 0 % means likely death, so stop (the preview already detects this). |
| **Timed pet feeding** | Pet auto-loot replaces a loot key. A hungry pet goes back to the inventory and loot stops. | LOW | `pet_food_key`, `interval_minutes`, `feed_on_start`. Press only when idle (not mid-move). Log each feed. It is **open-loop**: no cheap pixel signal confirms the pet ate. The interval must be set by the operator. Hunger rate differs by species and server, and overfeeding costs closeness, so make the default conservative and visible in the UI. |
| **In-place recovery with a bounded budget** | This is the Core Value: keep grinding without touching anything. | MEDIUM-HIGH | Cases: (1) **Knocked off**: localization changes to an unexpected platform, so replan from there. This is ordinary replanning, not a special mode. (2) **Stuck / no progress**: the player moves less than about 8 px over about 3 s (around 9 frames) while a move is active. Release keys, re-localize, retry once with re-alignment, then **try an alternative route** (with that edge's cost raised), then stop. (3) **Lost target**: unseen for about 2 s, so drop it and rescan. (4) **Player hidden**: the existing tracking chain handles this, with a stop after 5 s. Budget: at most 3 attempts per incident, and **at most about 5 recoveries in 2 minutes**, otherwise safe-stop. |
| **Safe stop plus PC alarm** | This is the Core Value's failure mode. A supervised bot is only safe if its stops are loud. | LOW | It releases all keys, flushes the 10 s clip, records the stop reason, and plays a sound (stdlib `winsound`). The sound **repeats until acknowledged** in the debugger or by F8, because one beep is easy to miss. Stop reasons: death (HP 0 %), spot anchors lost (map change or unexpected screen), potions exhausted or critical HP, recovery budget used up, player unknown for more than 5 s, HUD unreadable for more than about 5 s while armed, focus or calibration lost, F8. |
| **Navigation state in the debugger and recordings** | Operators need to see why the bot did something (Active requirement). | LOW-MEDIUM | Overlay: platforms and ropes, current node, planned route, current primitive and its deadline, target, recovery counter. Log the same fields to the decision log so offline replay can reconstruct a failure. |
| **Dry run for navigation** | Combat already has a dry run and an armed mode. Navigation input is riskier, so it needs the same. | LOW | The dry run shows the route and primitive it would run, without input. It reuses the existing dry-run path. |

### Differentiators (Competitive Advantage)

These fit the Core Value. Pick a few.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Supervised "test this link"** (run one taught link while armed, record its duration and outcome) | Turns a guessed layout into a measured one. It is the fastest way to find a bad take-off x-range or a drop-down that isn't allowed. | MEDIUM | Store the measured duration and success count on each edge. Use them for timeouts and route costs. Strongly recommended. Without it, timeouts are guesses at 3 fps. |
| **Per-edge reliability learning** | The bot stops choosing a rope it keeps missing. | LOW (after the test-link feature) | Raise the cost of an edge after each failure, and let it decay over time. Show the counts in the debugger. |
| **Generic timed-key scheduler** (pet food plus warrior buffs such as Rage, Iron Body, Power Guard, Booster) | Pet feeding needs a timer anyway. Generalizing it makes buffs nearly free. | LOW | Each entry: key, interval, "only when idle", "on start". Build the pet timer this way from the start, even if v1 only configures pet food. |
| **Idle positioning / spawn patrol** | When the screen is clear, standing still wastes respawn time. Moving to a taught "home" platform gets to the next spawn sooner. | LOW-MEDIUM | Operator marks a home node, or a short patrol cycle. Idle only after about 2 s with no targets. |
| **Run stats panel** | Supervisors can see at a glance that the bot is healthy. | LOW | Uptime, potions pressed per resource, feeds, recoveries by type, stops by reason, attacks. |
| **Quickslot potion-count reading** | Warns *before* potions run out, not after a failed press. | MEDIUM | Glyph OCR on the quickslot digits. It could reuse the name-tag glyph matcher idea. Defer: the "no effect after press" check already covers safety. |
| **Pet presence check** | Turns open-loop feeding into a checked one. The bot stops if the pet went back to the inventory. | MEDIUM | Template of the pet sprite near the player. The pet wanders, so use a long grace window. v1.x. |
| **Distinct alarm sounds per stop category** | The operator knows from across the room whether it's "potions out" or "stuck". | LOW | Small but useful for supervised play. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Humanization / randomized timing / path shuffling "to avoid detection"** (MapleMate's shuffle mode) | Commercial bots market it. | Out of scope by policy, because the server allows bots. It also adds nondeterminism that ruins offline replay and debugging. | Deterministic decisions. Keep the existing timing limits in `KeyboardController` only for game-input reliability. |
| **Scripted point-by-point routines** (auto-maple-style CSV) | Familiar to bot users, and simple at first. | Brittle against knock-offs and lost targets: the script's position doesn't match reality. It duplicates the taught graph. | A goal-driven planner (target → route → primitives) over the taught graph. |
| **Automatic terrain / rope detection** | Saves teaching time. | Unreliable over foreground grass and clouds, which the live recordings already showed. Key Decision: the operator teaches the layout. | A fast teaching UI plus the test-link feature. |
| **Minimap / multi-screen navigation** | Bigger grinding maps. | Out of scope for v1. It needs a second localization system. | One taught screen. |
| **Death / map-change recovery, relog, restock, CC on chat or GM** (MapleBot) | Unattended runs. | v1 is supervised. These are large, risky state machines that are hard to test. | Safe-stop and alarm. |
| **Remote notifications (SMS/email/Twitter/phone)** | Away-from-PC alerts. | Out of scope. A PC sound is enough for supervised play. | A repeating `winsound` alarm. |
| **Loot key spam** | "Pick up everything". | The pet auto-loots, and extra presses compete with potions and attacks. | Pet feeding timer. |
| **Unlimited retry / "never stop" recovery** | Looks more autonomous. | Hides real faults, burns potions while stuck, and risks death. | A bounded budget (3 per incident, about 5 per 2 min), then stop. |
| **Potion presses while the HUD is unreadable, or "spam until the bar rises"** | Feels safer. | Wastes potions, hides an empty slot or wrong key, and fights with in-game pet auto-pot. | Only press on confident readings. Stop if the HUD is unreadable for too long. Count presses with no effect. |
| **Movement tricks** (mid-air rope catch, jump-boost, early rope jump-off) | Faster movement. | Needs frame-precise timing that isn't possible at 3 fps. | Ground-to-rope grabs, full climbs and explicit drop-downs. Revisit after capture gets faster. |
| **Opening the pet or inventory UI to verify hunger or potion count** | Exact state. | It blocks the game view, breaks perception, and needs UI navigation. | Open-loop timer, then (v1.x) a pet-presence check and quickslot-count OCR. |
| **Other-player / kill-steal avoidance** | Shared maps. | Needs player classification beyond the bot's own character. Not a v1 problem when supervised. | The operator picks an empty spot. Revisit with the overlapping-name-tag work. |

## Expected Operator Settings (defaults to put in requirements)

| Setting | Recommended default | Rationale / confidence |
|---------|---------------------|------------------------|
| HP threshold | 50 % | Existing preview default. Melee takes contact damage, so be conservative. MEDIUM |
| MP threshold | 30 % | Existing default. MEDIUM |
| Critical HP (immediate stop if a press doesn't help) | 20 % | Judgment. Classic mobs can hit for large chunks. LOW-MEDIUM |
| Potion cooldown per resource | 1.5 s (range 0.5–30) | Existing bounds. Must exceed the effect-check window at 3 fps. Elixir-type items on some servers need 30 s. MEDIUM |
| Effect-check window / min rise | 2 s / +3 pp | About 6 frames at 3 fps. LOW-MEDIUM, tune on recordings |
| Ineffective presses before stop | 3 consecutive | Judgment. LOW-MEDIUM |
| Skill → basic fallback | below 10 %, back above 15 % MP | Hysteresis band. Depends on the skill's MP cost. LOW |
| Pet food interval | operator-required, no hidden default | Varies by species and server. Overfeeding costs closeness. MEDIUM (that it varies), LOW (any number) |
| Stuck detection | < 8 px movement in 3 s while moving | Judgment for 3 fps. LOW-MEDIUM |
| Lost-target drop | 2 s unseen | LOW-MEDIUM |
| Recovery budget | 3 per incident, 5 per 2 min | LOW-MEDIUM |
| Player-unknown stop | 5 s | Existing tracking cap. HIGH (existing) |
| HUD-unreadable stop (armed) | 5 s | Matches the player-unknown cap. LOW-MEDIUM |
| Alarm | repeats until acknowledged | Supervised-play expectation. MEDIUM |

## Feature Dependencies

```
Spot layout teaching
    ├──> Spot identity check (anchors saved with layout) ──> map-change / unexpected-screen stop
    └──> Localization (platform / rope / unknown)
              └──> Route planning
                        └──> Verified movement primitives
                                  ├──> Multi-platform target selection
                                  ├──> In-place recovery (knock-off = replan; stuck = alt route)
                                  └──> [diff] Test-this-link ──> Per-edge reliability

HP/MP bar reading (exists) ──> Real potion presses ──> Ineffective-press detection ──> "potions exhausted" stop
HP/MP bar reading (exists) ──> Skill/basic fallback (MP %)

Safe stop + alarm ──required by──> every recovery and stop condition (build early)
Timed-key scheduler ──> Pet feeding ──enhances──> [diff] Buffs, [diff] Pet presence check
Navigation debugger overlay ──enhances──> every navigation feature (build alongside localization)

Potion presses ──conflicts with──> mid-primitive key holds (jump, drop-down): potions run between primitives
In-game pet Auto HP/MP Potion ──conflicts with──> bot potion verification (bar rises without a bot press;
                                                   bot press shows "no effect" if pet already drank)
```

### Dependency Notes

- **Localization requires the layout.** It is plain geometry against taught segments. Do it before any movement input, and check it in dry run against recordings first.
- **Movement primitives require localization and are the critical path.** Targeting and recovery are thin layers on top of "act, then check the platform changed within a deadline".
- **Knock-off recovery comes free with replan-on-localization-change.** Only stuck handling needs real work, namely alternative routes and edge-cost penalties.
- **Safe stop and alarm should come first.** Every later feature adds stop reasons to it. It is LOW complexity and HIGH value.
- **Potions are independent of navigation.** They can ship as a parallel, early phase on the existing bar reader. That gives survival before the bot starts moving between platforms.
- **Conflict with the in-game pet auto-pot:** if the operator also uses the pet's Auto HP/MP Potion skill, the bot's "no effect" check can fire falsely. Requirement: document that only one of them should be enabled, or add a "pet auto-pot active" mode that skips the bot's potion presses and keeps only the critical-HP and death stops.

## MVP Definition

### Launch With (v1)

- [ ] Safe stop with a repeating alarm and stop reasons. Every other feature depends on it.
- [ ] Real HP/MP potions with per-resource cooldown, priority, ineffective-press and critical-HP stops. Survival.
- [ ] Skill attack with MP-hysteresis fallback to basic. Cheap, and needed for the warrior.
- [ ] Timed pet feeding through a generic timed-key scheduler. Loot depends on it.
- [ ] Layout teaching, spot anchors, localization, route planning. The base for navigation.
- [ ] Verified primitives (walk, climb, jump-up, drop-down, rope jump-off) with dry run.
- [ ] Multi-platform targeting with commitment.
- [ ] Bounded recovery: knock-off replan, stuck → alternative route → stop, lost target.
- [ ] Navigation overlay and decision-log fields.

### Add After Validation (v1.x)

- [ ] Test-this-link and per-edge reliability. Add as soon as primitive timeouts turn out to be guesses. Consider pulling into v1.
- [ ] Buff entries in the timed-key scheduler. Add when the operator wants Rage, Iron Body and so on.
- [ ] Idle home/patrol node. Add when clear-screen idle time becomes noticeable.
- [ ] Run stats panel, and distinct alarm sounds per category.
- [ ] Pet presence check. Add if a lost pet is ever seen in recordings.

### Future Consideration (v2+)

- [ ] Quickslot potion-count OCR. Ineffective-press detection already covers safety.
- [ ] Death/map-change recovery, multi-screen navigation, ranged classes. Out of scope by project decision.
- [ ] Movement tricks (mid-air rope catch). Only after capture is much faster than 3 fps.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Safe stop + repeating alarm | HIGH | LOW | P1 |
| Real potions + out-of-potion detection | HIGH | MEDIUM | P1 |
| Skill/basic fallback | MEDIUM | LOW | P1 |
| Timed pet feeding (scheduler) | HIGH | LOW | P1 |
| Layout teaching + spot anchors | HIGH | MEDIUM | P1 |
| Localization + route planning | HIGH | MEDIUM | P1 |
| Verified movement primitives | HIGH | HIGH | P1 |
| Multi-platform targeting | HIGH | MEDIUM | P1 |
| Bounded in-place recovery | HIGH | MEDIUM-HIGH | P1 |
| Navigation overlay/logging | MEDIUM | LOW-MEDIUM | P1 |
| Test-this-link + edge reliability | HIGH | MEDIUM | P2 (strong candidate for P1) |
| Buff timers | MEDIUM | LOW | P2 |
| Idle home/patrol | MEDIUM | LOW-MEDIUM | P2 |
| Run stats, alarm categories | LOW-MEDIUM | LOW | P2 |
| Pet presence check | MEDIUM | MEDIUM | P3 |
| Quickslot count OCR | LOW-MEDIUM | MEDIUM | P3 |

## Competitor Feature Analysis

| Feature | auto-maple | nanpuhaha/maplebot | MapleMate (marketing) | Our Approach |
|---------|------------|--------------------|-----------------------|--------------|
| Position source | Minimap template match | Not documented | "Computer vision" | Player sprite + name tag + tracking chain on the main view (exists) |
| Layout | Recorded quadtree + A* | Per-map scripts | Up to 3 farming paths | Operator-taught platform/rope graph + Dijkstra |
| Behavior | CSV routines of Points | Per-map AutoIt scripts | "Dynamic farmer" | Goal-driven: target → route → verified primitives |
| HP | Not documented | "HP detection and heal" | Not documented | Thresholds, per-resource cooldown, effect check, critical stop |
| Pet | Not documented | "Pet detection and feed" | Not documented | Timed feed (v1), presence check (v1.x) |
| Failure handling | Not documented | Relog/reboot, CC on chat | Not documented | Bounded recovery, then safe stop + alarm + clip |
| Anti-detection | No | Chat-triggered CC/DC | Path "shuffle" to evade tracking | Explicitly excluded |

## Sources

- auto-maple README: https://github.com/tanjeffreyz/auto-maple (MEDIUM: primary for that tool, thin on thresholds)
- nanpuhaha/maplebot README: https://github.com/nanpuhaha/maplebot (MEDIUM: feature list only)
- MapleMate thread (vendor marketing): https://www.epicnpc.com/threads/maplemate-%E2%80%93-a-farming-bot-for-any-maplestory-server.3185212/ (LOW)
- Pet Auto HP Potion skill: https://meowdb.com/msclassic/item-db/1530, Auto MP: https://meowdb.com/msclassic/item-db/1531 (MEDIUM: Classic-specific)
- Pet hunger/closeness behavior: https://strategywiki.org/wiki/Special:MobileDiff/156979 and https://meowdb.com/msclassic/formulas/pets (MEDIUM/LOW: older or Classic values)
- Pet food fullness: https://meowdb.com/msclassic/item-db/3170 (MEDIUM)
- Movement mechanics: https://meowdb.com/msclassic/forum/guides/Kargo/efficient-movement-guide and https://meowdb.com/msclassic/jump-quest (LOW-MEDIUM: community)
- Elixir 30 s cooldown (server-specific): https://meowdb.com/msclassic/item-db/276 (MEDIUM for Classic only)
- Project context: `.planning/PROJECT.md`, `docs/BACKLOG.md`, `src/maplebot/autopotter.py` (HIGH: existing defaults 50/30 %, 1.5 s shared cooldown, 2-reading confirm, HP 0 % handled as possible death)

---
*Feature research for: supervised screenshot-driven MapleStory grinding bot (one taught screen, melee)*
*Researched: 2026-10-24*
