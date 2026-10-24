# Pitfalls Research

**Domain:** Screenshot-in / keyboard-out bot for a 2D side-scroller (MapleStory client, melee warrior), adding multi-platform navigation, potions, pet feeding, recovery and safe-stop
**Researched:** 2026-10-24
**Confidence:** MEDIUM overall. The engineering pitfalls (timing at 3 fps, verification, blocking input, failure handling) are HIGH: they come straight from this codebase (`decision.py`, `keyboard.py`, `autopotter.py`, `config.toml`, CONCERNS.md). The game-mechanic claims (rope grab, Up enters portals, pet goes home when hungry, ladder knock-off) are LOW to MEDIUM: they come from fan wikis (MeowDB Classic, StrategyWiki) and must be checked on the target server. Each such claim is marked **[verify in-game]**.

Phase names below are suggestions; the roadmapper should map them to real phase numbers:

- **P-Foundation**: non-blocking input thread, timestamped observations, per-action hold leases, ordered key chords
- **P-Layout**: teaching the spot layout, platform localization, camera anchoring
- **P-Moves**: rope climb and dismount, jump-up, drop-down, each with verification
- **P-Targeting**: route planning and targeting across platforms
- **P-Resources**: potion keys, skill/MP fallback, pet feeding
- **P-Recovery**: knock-off, stuck, lost target, escalation ladder
- **P-SafeStop**: alarm, stop-path hardening, incident capture of navigation state

---

## Critical Pitfalls

### Pitfall 1: Open-loop moves verified against stale or mid-action frames

**What goes wrong:**
The bot presses "walk right 0.4 s, then Up", checks one frame, and decides whether the move worked. At 250-400 ms per frame, that frame was often captured during the key hold or before it. The check then reports "not on rope yet" and the bot presses again. The result is double moves, overshot ropes and oscillation. The opposite also happens: a frame captured mid-jump shows the player higher up, so the bot marks "jumped up to ledge" as done when the player is about to fall back.

**Why it happens:**
The current `Agent.step` takes `now` and an observation, but nothing links an observation to the action that came before it. `verify_until` uses decision time, not frame capture time. At 3 fps, walking moves the player tens of pixels between frames (measure this: px/s at the character's speed). That is larger than the window in which a rope can be grabbed.

**How to avoid:**
- Stamp every observation with its capture time (`perf_counter` taken before `grab`), and every action with its key-up time. A move may only be judged on frames captured after key-up plus a settle time (landing, rope latch). Frames captured during the action count only as "in progress".
- Model each move as a small state machine: precondition (platform or rope id, x-window), expected postcondition (platform or rope id, y-band), deadline, attempt count. "Success" requires the postcondition on **two consecutive confirmed frames** with stable feet y. One frame is not enough, because a player in mid-air looks like a player on a higher platform.
- Align on x with calibrated taps (measured px per ms of hold, fitted from replay) plus observe. Do not use long timed walks near the target.
- Let the game do the precise timing where it can. Hold Up while walking toward a rope so the client grabs it at the right x, instead of predicting the x yourself **[verify in-game]**. Bound the hold with a lease (Pitfall 2) and a portal guard (Pitfall 6).

**Warning signs:**
Decision logs where a move is "retried" while the next frame shows it already happened. Rope approaches that alternate left and right around the rope x. Success declared with only one frame of evidence. Move durations in recordings that vary a lot between identical attempts.

**Phase to address:** P-Foundation (timestamps, settle rule) and P-Moves (per-move state machines).

---

### Pitfall 2: The 250 ms hold cap and the blocking input worker are incompatible with climbing

**What goes wrong:**
Climbing a rope needs Up held for one to several seconds. Today `input.max_action_seconds = 0.25`, the watchdog releases any key held past its deadline, and `execute_sequence` sleeps on the capture thread. Planners usually pick one of two bad fixes:
(a) Raise `max_action_seconds` to 3 s for everything. A wrong Left/Right then runs off a ledge for 3 s, and the hold cap stops being a safety guarantee.
(b) Chain many 0.25 s Up taps on the capture thread. No frames are captured while they run, so a knock-off during the climb goes unseen, and the bot keeps tapping Up at the bottom of the rope. Up at the bottom can re-grab the rope or enter a portal.

**Why it happens:**
The safety design assumes short taps on a single platform. CONCERNS.md already notes that input blocks the capture worker and that no frames are observed or recorded during an action.

**How to avoid:**
- Move input onto its own thread **before** any navigation work, so capture keeps running during actions (the fix CONCERNS.md already proposes). Keep the watchdog as the only path that releases keys.
- Replace the global cap with **per-kind leases**. A continuous hold (Up on a rope, Down for a drop) is granted for a short lease, about 2 frame intervals (for example 600-800 ms at the current fps). The decision loop renews the lease only when a fresh confirmed frame shows the precondition still holds (still on the same rope, y still changing). If no renewal arrives, the watchdog releases the key: a dead-man switch. Keep a hard per-kind maximum (for example rope climb no more than rope length / climb speed x 1.5).
- Horizontal walking keeps a short cap. Only Up and Down get longer leases, and only inside taught rope zones.
- Never let a lease outlive a stop, focus loss or F8. The existing `stopped` event must cancel renewals as well as held keys.

**Warning signs:**
PRs that change `max_action_seconds` globally. Recordings with frame gaps longer than 1 s during climbs. A climb that keeps going after the player sprite is seen on the floor.

**Phase to address:** P-Foundation. This blocks P-Moves.

---

### Pitfall 3: Player tracking that stays at the old position during fast moves

**What goes wrong:**
The tracking chain accepts partial evidence near the last position for up to 5 s, and partial name tag scores of 0.6 sit close to the about 0.46 that random scenery reaches. A drop-down moves the player a full platform height in well under a second. In the frame after the drop, the true player is outside the search window, while scenery, a monster tag or brambles near the old position score just enough. The tracker then says the player never moved, so the drop is marked failed and gets retried. Or the tracker drifts onto a monster's name tag and the bot navigates a monster's position. Climbing poses (sprite seen from behind) and jump poses also lower sprite scores at the exact moments that need verification.

**Why it happens:**
The "near last position" gate was tuned for a player who is hidden while standing or walking. It has no idea that the bot just issued a move with a known expected displacement.

**How to avoid:**
- Make tracking move-aware. While a move is in progress, give the expected displacement (rope: x fixed, y moving; drop: y down to the taught target platform; jump-up: y up) to the tracker and search that corridor, not a circle around the old fix.
- A move's success **requires a confirmed (non-tracked) fix**, such as a full name tag or sprite match. Tracked-only evidence means "unknown, wait". It never counts as proof that the move succeeded or failed.
- Teach climbing and back-facing sprites (and jump and fall poses if they score badly) as player templates. Benchmark them on recorded rope frames with `tools/benchmark_catalog.py`.
- Reset or widen the track at every move boundary, and log which evidence type (tag, sprite, tracked) supported each navigation decision.

**Warning signs:**
"Move failed, retrying" while the raw frame clearly shows the player at the destination. A player box that stays in place while camera shift is non-zero. Tracked-only frames clustering around ropes and drops in recordings.

**Phase to address:** P-Moves, with a perception sub-task. Flag it for deeper research and labeled rope and drop fixtures.

---

### Pitfall 4: A layout taught in screen pixels while the camera moves

**What goes wrong:**
The operator draws platforms and ropes on one frozen frame. When the player climbs, jumps or walks toward an edge, the MapleStory camera follows and scrolls vertically or horizontally if the map is bigger than the viewport. Every taught platform is then off by the camera offset. The bot believes it is on platform B while standing on C, and route planning becomes nonsense. Integrated `camera_shift` drifts over a session, so the error grows slowly and is not obvious.

**Why it happens:**
"One screen" sounds like static coordinates. The current same-platform test is feet y within 18 px, which hides small offsets until a rope 20 px away gets missed.

**How to avoid:**
- Store the layout in **scene coordinates** anchored to 2-3 taught static landmarks (distinctive terrain or background patches that monsters and the player do not cover). Re-register the anchors every frame, or every N frames, with `matchTemplate` on small regions. Do not integrate per-frame shifts.
- If the anchors disagree or are not found on K consecutive frames, the position is "unknown" and the bot pauses or stops, as for an unexpected screen.
- During teaching, check whether the spot scrolls at all: walk the whole spot in capture-only mode and record the anchor offsets. If they never change, say so in the spot file. If they do, scene coordinates are mandatory.
- Tie the layout file to the calibration (view size, DPI, window client size). Refuse to arm when they do not match, so a recalibration cannot silently shift the layout.

**Warning signs:**
The debugger overlay of the taught platforms slides away from the real terrain after a climb. "Current platform" flickers between two platforms while the player stands still. Rope grabs work at the start of a session and fail later.

**Phase to address:** P-Layout. It must be settled before P-Moves, since every move postcondition depends on it.

---

### Pitfall 5: Key chords whose order the timing randomizer can break

**What goes wrong:**
Several moves are chords whose order matters. A drop-down is Down held **then** Jump. A rope dismount is a direction plus Jump while hanging. A rope jump is Jump plus Up while moving. `_execute_sequence` plans overlapping holds through the timing planner, which adds offset variation, key stagger and hold variation. If Jump lands before Down, the result is a normal jump, not a drop. If the direction is released before Jump, the character may just hang on the rope (jumping straight off a rope reportedly needs a direction **[verify in-game]**). These failures are intermittent and look like the game being flaky.

**Why it happens:**
The planner was built for single taps where "Movement/jump/attack may overlap; opposites may not." It has no ordering constraints between keys.

**How to avoid:**
- Add explicit chord primitives with ordering constraints: `after(key_a_down, min_ms)` and `hold_until(key_b_up)`. Randomization may only jitter **inside** the constraints and never reorder.
- Unit-test each chord against the fake backend: assert the event order and the minimum lead time over 1,000 seeded runs.
- Add `up` and `down` to `[input]` and to the allowed `Action.kind` set. Today `execute` raises `ValueError` for anything other than left, right, attack and jump.

**Warning signs:**
The drop-down success rate is well below 100% with no visible cause. Recorded `last_timing` events show Jump-down before Down-down.

**Phase to address:** P-Foundation (chord primitives) and P-Moves (per-move chords).

---

### Pitfall 6: Up and Down have side effects beyond climbing (portals, rope tops, bottom floors)

**What goes wrong:**
- **Up enters portals.** The same key grabs a rope and enters a portal **[verify in-game; documented on fan wikis]**. A bot that holds Up while walking to a rope near a portal, or keeps holding Up after a knock-off, changes map. That is an unrecoverable case in v1.
- **Down at a rope top grabs the rope** instead of dropping through the platform **[verify in-game]**. A drop-down link taught next to the top of a ladder sometimes produces "on rope" instead of "on the lower platform".
- **The bottom floor cannot be dropped through.** Down plus Jump there does nothing visible, or a crouch-jump in place. A "drop" link taught on a solid floor, or near a platform edge with nothing under it, never completes, or lands on an unexpected platform.

**How to avoid:**
- Teach **forbidden-Up zones** (portal x-ranges, drawn like ropes) and refuse any Up hold whose lease window overlaps one. Allow Up only inside a taught rope's x-window plus a margin.
- Give each drop-down link a taught x-range and a taught target platform, and check during teaching that the x-range is not within N px of a rope top.
- On a map-change signal (anchors lost, screen fade, minimap or title change), stop at once with an alarm. Do not try to recover.

**Warning signs:**
A drop that ends "on rope". Any frame where every anchor vanishes at once (fade to black). Up held while the player x is outside every rope window.

**Phase to address:** P-Layout (zones and links) and P-Moves (guards).

---

### Pitfall 7: Knock-off treated as a failed move instead of a new state

**What goes wrong:**
A melee warrior walks into monsters. Contact damage knocks the player back and can push them off a ledge, and a hit while climbing can knock them off a ladder **[verify in-game]**. Bots usually handle this in one of three bad ways:
(a) The current move keeps running (still holding Up or still walking toward a rope that is now a platform away).
(b) The move times out, is counted as "stuck", and gets retried from the wrong place.
(c) The bot keeps grinding from the new platform with its target still set on the old one.

**Why it happens:**
Navigation is written as "execute plan step by step" instead of "on every confirmed frame, localize, then compare against the expected state".

**How to avoid:**
- Localize on every confirmed frame (platform id, rope id or "airborne/unknown"). Keep "where the plan expects me" separate from "where I am". A mismatch outside an active move's allowed corridor is a **knock-off event**: release held keys, wait for a stable landing (2 confirmed frames), then re-plan from the actual platform.
- Count knock-offs per time window. A spot where the bot is knocked off more than X times in Y minutes is a configuration problem (bad spot, too many monsters on the rope route), so stop with a reason. Do not loop forever.
- Use the post-hit invincibility window as information: right after a knock-off, climbing again is safer than walking back into the same monster. That is a planner preference, not a requirement.

**Warning signs:**
Recordings where the player falls while the decision log still says "climbing". Recovery counters that reset on every success, so a spot that knocks the player off every 30 s never escalates.

**Phase to address:** P-Recovery, but the localization hook belongs to P-Layout and P-Moves.

---

### Pitfall 8: Potion logic that trusts the bar, the press and the slot

**What goes wrong:**
- **Latency kills.** Two consecutive low readings at 3 fps take about 0.6-0.8 s to confirm. Add a potion press queued behind a blocking attack sequence, and the effect shows 1-1.5 s after HP crossed the threshold. Against hard-hitting monsters, a threshold set as "30%" is effectively 10%.
- **"Out of potions" false alarms.** The plan is to stop when a press doesn't change the bar. But the player takes damage while drinking, so HP can stay flat or fall even though the potion worked. MP falls when a skill is used in the same window. A naive "bar didn't rise means out" stops the bot during heavy fights. The opposite error: natural regen or a level-up refill makes an empty slot look like it worked.
- **Misread bars.** Tooltips, the chat window, level-up and other screen effects, or a HUD that moved after a resolution or window change can produce `None` or wrong percentages. A misread 0% looks like death. A misread 100% suppresses potions.
- **Wrong slot.** The potion key is a quickslot binding. If the slot holds something else (the operator moved items, or the potion stack ran out and the slot is empty or auto-filled), pressing it uses the wrong item. A return scroll causes a map change.
- **Cooldown items.** Elixirs and Power Elixirs have a 30 s cooldown on Classic-era clients **[verify on server]**. Spamming during cooldown is wasted and also looks like "no effect".

**How to avoid:**
- Make potions an **interrupt**, not a queued action. The input thread must be able to pre-empt a long hold (release movement keys, press potion, resume). This depends on P-Foundation.
- Set thresholds with latency in mind. Document that the effective trigger point is the threshold minus the damage taken over about 1.5 s, and show measured HP drop per second in the debugger so the operator can choose.
- Verify the effect statistically. After a press, look at the next 2-4 confirmed readings for a rise of at least a fraction of the potion's taught heal amount, relative to the trend before the press. Declare "potion ineffective" only after 2-3 consecutive ineffective presses, then stop with an alarm.
- Teach the **quickslot icon** for each potion key and check it by template before every press. A missing or changed icon means "out of potions or wrong slot", so stop. This is more reliable than inferring from the bar, and it guards against the return-scroll case. If the client shows a stack count, OCR is optional. Icon presence is enough for v1.
- Require a valid HUD read (both bars found, anchors in place) before **any** potion decision. `None` readings keep the current safe default (no suggestion), and N consecutive `None` readings stop the bot, since a blind bot cannot heal.
- Keep "HP 0" as death and stop. The existing preview already does this. Keep it when the keys go live.

**Warning signs:**
HP traces in recordings dipping well below the threshold before the rise. "Out of potions" stops while the potion count is clearly not zero. Potion presses logged more often than the heal amount could justify.

**Phase to address:** P-Resources, with the pre-emption dependency in P-Foundation.

---

### Pitfall 9: Pet feeding as a blind timer

**What goes wrong:**
- On Classic-era clients a pet at 5 fullness or less goes home **[verify on server; MeowDB "unconfirmed"]**. Auto-loot then stops silently, and the bot keeps grinding without looting. Nothing in the screenshot pipeline notices.
- The feeding timer lives in memory. After every restart, or after a long stop, the bot does not know when the pet was last fed. Hunger keeps running while the bot is stopped.
- Feeding a pet at 100 fullness costs closeness **[verify]**, so feeding "to be safe" every few minutes has a cost.
- Out of pet food, or a moved quickslot, means presses do nothing. With no check, the bot cannot tell.

**How to avoid:**
- Treat **pet presence** as a monitored condition. Teach the pet sprite (as is done for monsters) and check on each frame that it is near the player. If the pet is missing for more than N seconds, feed once and check again. If it is still missing, stop with an alarm ("pet gone home or despawned; auto-loot off").
- Persist `last_fed_at` with the spot or session config. On start, ask the operator ("fed just now?") or feed immediately.
- Set the interval from the pet's hunger rate, chosen by the operator per pet, rather than a magic number. Check the food quickslot icon as for potions.
- Never feed during a move or an Up lease. Feed only from a stable standing state.

**Warning signs:**
Recordings with drops piling up on the floor. No pet sprite near the player in late-session frames. The feeding timer showing "never fed" after a restart.

**Phase to address:** P-Resources. The pet-presence check could also be a P-Recovery health check.

---

### Pitfall 10: Stuck detection that cannot tell standing still on purpose from failing to move

**What goes wrong:**
The existing stall guard is "less than 1.5 px of progress for 5 approach steps". Across multiple platforms this misfires both ways:
- **False stuck:** attacking, waiting out a potion, hanging on a rope while a monster passes, or waiting for landing frames are all "no progress" by design.
- **False progress:** detection jitter of a few pixels, or a tracked position sliding along with the camera shift, looks like movement while the character is pinned against a wall, blocked by a monster, or locked in a chat or NPC dialog.
- **Captured keys:** if a chat input or dialog has focus, arrows do nothing and letter keys (skill and potion keys bound to letters) are **typed into chat**. A stuck detector that only retries makes this worse.

**How to avoid:**
- Measure progress **per intent**. Each move or approach declares its expected displacement vector and a minimum within a time window. Intents that expect no motion (attack, potion, wait) are excluded from the stall check.
- Measure the detection noise floor from replay (std dev of the confirmed player x and y while standing) and require progress greater than 3x that noise. Count only confirmed fixes.
- Treat "no key has any visible effect for K consecutive intents" (not move, not attack animation, not potion) as **controls not reaching the game**, which means stop. Do not route around it. This includes the chat and dialog case. Consider a template for the chat-input caret or for common dialogs as an unexpected-screen signal.
- Use an escalation ladder with a **global budget**: re-align and retry the same link once, then try an alternate route (if the layout has one), then safe stop. Also stop if more than N recoveries happen in M minutes, even if each one "succeeded". A spot that needs constant recovery is broken.

**Warning signs:**
Stuck stops logged during attack sequences. Recovery attempts that succeed every time while the session makes no kills. Chat-window text appearing in recordings.

**Phase to address:** P-Recovery, with the noise-floor measurement as a P-Moves acceptance task.

---

### Pitfall 11: Cross-platform targeting that thrashes between platforms

**What goes wrong:**
With targets on every platform, "nearest monster by Euclidean distance" picks a monster one platform up that is 6 s of route away over one 1.5 s away on the current platform. While the bot travels, the monster walks away, dies to someone else, or is hidden by grass. The 80 px association gate and the 8 px ambiguity margin then stop the bot ("Target missing", "Ambiguous target association"), or it re-targets mid-route and turns around. The bot ends up commuting between platforms and kills little.

**Why it happens:**
The current agent targets monsters by identity and stops whenever association fails. That works on one platform at short range and breaks across a 5-8 s route.

**How to avoid:**
- Target a **platform**, not a monster, while travelling. Choose a destination platform by (monsters on it) / (route time + fight time), with strong hysteresis in favour of the current platform. Pick a specific monster only after arrival.
- Assign monsters to platforms by feet position against the taught platform extents (in scene coordinates), not by `abs(feet_y - player_feet_y) <= 18`.
- A target lost during travel is **normal**. Re-evaluate on arrival, and stop only when no platform has confident targets for T seconds. Being idle is not an error, since monsters respawn.
- Commit to a route once started (no re-planning except on knock-off or when the destination becomes empty), so the bot does not turn around on a rope.

**Warning signs:**
Kill rate falling as more platforms are taught. Route changes per minute higher than kills per minute. Many "Target missing" stops right after a climb.

**Phase to address:** P-Targeting.

---

### Pitfall 12: A safe-stop path that fails exactly when needed

**What goes wrong:**
- The alarm is raised only from the decision path. If the capture worker raises, `_run` sets IDLE and returns, and `__main__` exits with the HTTP server. CONCERNS.md documents this. There is then no alarm, no clip, and a dead debugger page.
- `winsound.PlaySound`/`Beep` called synchronously on the capture or input thread blocks key release or frame capture.
- The alarm plays once while the operator is away from the PC and is missed. The opposite also happens: transient pauses (target lost, waiting for respawn) sound the alarm too, the operator learns to ignore it, and then misses the death alarm.
- Stop and act race: the watchdog stops, then the decision thread renews a lease or presses a potion a few milliseconds later because it read `enabled` before the stop.

**How to avoid:**
- Keep one `safe_stop(reason, severity)` function that is idempotent and callable from any thread, in this order: release keys, cancel leases, flush the recording clip, then signal the alarm on a **separate** thread or process. Call it from the watchdog, from the worker's `finally`, and from the top-level exception handler. The HTTP server and the alarm must outlive a dead worker.
- Two severities. "Pause" (no targets, waiting) has no alarm. "Stop" (death, map change, potions out, pet gone, recovery budget used up, controls not reaching the game, unknown screen) plays a repeating alarm until the operator acknowledges it in the debugger.
- Every key-down path checks the stop event **under the controller lock** right before `SendInput`. The existing `_execute_sequence` does this; the new lease and potion-interrupt paths must too. Add a fake-backend contention test.
- Test the stop path on purpose: inject an exception in perception, kill capture, steal focus, press F8 mid-climb. In each case assert that keys are released, the clip is saved and the alarm fires.

**Warning signs:**
Any stop without a saved clip. A debugger page that dies with no reason shown. The operator muting the alarm.

**Phase to address:** P-SafeStop. Part of it (worker-death handling) should be pulled into P-Foundation, since navigation adds many more ways to fail.

---

### Pitfall 13: Trying to validate closed-loop navigation with offline replay

**What goes wrong:**
The project's strength is offline replay that never sends input. But recorded frames do not react to the bot's keys, so replay cannot tell you whether a climb, drop or recovery works. Teams then either ship navigation checked only by unit tests on synthetic detections (as `tests/test_decision.py` does today), or spend live sessions debugging logic errors that a simulator would have caught.

**How to avoid:**
- Use replay for **perception and localization** of navigation states. Record labeled clips of the operator moving manually (climbs, drops, knock-offs, grass occlusion on ropes) and assert platform and rope localization and move-success detection on them.
- Add a small **kinematic simulator** for the decision layer: taught layout, walk and climb speeds, fall, knockback events, perception noise, 3 fps frame timing and frame drops. Unit-test move state machines, leases, recovery escalation and stop paths against it with a fake input backend.
- Live tests are acceptance runs only, with full recording on and navigation state in every decision log.

**Warning signs:**
Navigation bugs found only in live play. Unit tests that call `step` with observations that do not respect frame timing.

**Phase to address:** P-Moves (simulator and labeled clips), reused by P-Targeting and P-Recovery.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Raise `max_action_seconds` globally for climbing | Climbing works in a day | Hold cap no longer bounds damage from a wrong key; a runaway walk off a ledge lasts seconds | Never. Use per-kind leases |
| Keep input on the capture thread and "just chain taps" | No threading work | Blind during every move; knock-off and potion latency unbounded | Only for a throwaway spike in capture-only/dry-run |
| Layout in raw screen pixels | Simple teaching UI | Breaks the first time the camera scrolls; silent drift | Only if teaching proves the spot never scrolls (record it in the spot file) |
| Fixed pet-feed timer without a presence check | Trivial | Silent loss of auto-loot; overfeed closeness loss | MVP only if the operator checks the pet at intervals; add the presence check before longer runs |
| "Bar didn't rise means out of potions" | One rule | False stops in heavy fights, missed empty slots | Never as the only signal; combine with the quickslot icon check |
| Retry-until-success recovery | Looks robust in demos | Endless loops hide broken links; never escalates to alarm | Never. Always bounded attempts plus a global budget |
| Tracked-only positions count as move success | Fewer "unknown" pauses | Phantom success; bot navigates a monster's tag | Never for success or failure; fine for display |
| Hard-coded walk and climb speeds | No calibration step | Wrong after speed buffs, equipment or server rate changes | Acceptable if measured per spot during teaching and checked against replay |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Win32 `SendInput` chords | Relying on randomized planner order for Down+Jump or Dir+Jump | Ordered chord primitives; jitter only inside constraints; seeded order tests |
| Game quickslots (potions, pet food, skill) | Assuming the key always maps to the same item | Template-check the slot icon before pressing; a changed or empty icon means stop |
| Game camera | Integrating per-frame `camera_shift` to place the layout | Re-register against taught static anchors; unknown means pause |
| Game UI focus (chat, NPC dialog, menus) | Letter-bound keys keep firing into an open chat box | "No key has effect" check means stop; optional chat-caret or dialog template as unexpected screen |
| Windows audio for the alarm | Synchronous `winsound` on the capture or input thread | Alarm on its own thread or process, repeating until acknowledged, started after key release |
| Window and calibration changes | The layout survives a recalibration with a different view origin | Bind the layout to calibration geometry; refuse to arm on mismatch |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Full-frame detection plus added landmark, pet, quickslot and HUD templates | fps drops from about 3 to about 2; the 500 ms guard starts stopping the bot | ROI search: anchors and quickslots at fixed small regions; monsters per platform band; player in the move corridor | Every added template group; measure with `benchmark_catalog.py` per group |
| PNG encoding of two images per frame | Frame time increases with no added value | Encode lazily or only when the debugger or recorder needs it (CONCERNS.md) | Already today; worse with navigation overlays |
| Lease renewals tied to frame rate | Up released mid-climb when one frame is slow; jerky climbing | Lease of at least 2x p95 frame time; report p95 in `/api/status` | Any frame above about 400 ms |
| Potion trigger latency | HP dips far below threshold before the heal | Pre-emptive potion interrupt; latency-aware threshold; consider a dedicated HUD-only fast path (small ROI, no detection) at a higher rate | When monster damage per second x 1.5 s exceeds the threshold margin |
| Recording pre-roll at full size while full recording is on during navigation tests | RSS grows; GC pauses add frame jitter | Downscale pre-roll; cap queue (`max_queue_frames`) | Long live acceptance sessions |

## Security Mistakes

Out of scope per project rules: anti-cheat evasion and input-origin concealment. The safety issues that do apply are about input reaching the wrong place:

| Mistake | Risk | Prevention |
|---------|------|------------|
| Longer holds (Up or Down leases) without the focus gate re-checked at each renewal | Keys held into another window after an alt-tab during a climb | Lease renewal must pass the same `safe()` focus, obscuration and calibration gate as key-down |
| Letter-bound skill and potion keys while the chat box has focus | Bot types text into public chat | "No effect" stop; prefer non-letter quickslot keys in the operator setup guide |
| Navigation recordings of long sessions | Larger plaintext captures of the desktop (manual region mode) | Keep existing retention limits; warn when the manual region is used with full recording |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Teaching UI accepts any drawn link | Operator teaches a drop on a solid floor or a rope near a portal; the bot fails at runtime | Validate during teaching: show the link, then offer "test this link" in supervised armed mode with a pass or fail verdict |
| Stop reason is one string | Operator cannot tell "potions out" from "lost localization" from "controls not reaching game" | Structured stop reasons with severity, plus the frame and nav state at stop, shown first in the debugger |
| Alarm for every pause | Alarm fatigue; real deaths missed | Two severities; alarm only for Stop; repeat until acknowledged |
| No live view of the plan | Operator cannot see why the bot walks away from a monster | Overlay current platform, planned route, active lease and recovery counter on the annotated frame (already an Active requirement) |
| Recovery counters hidden | A slowly degrading spot is noticed only when it fails | Show knock-offs, retries and ineffective potions per 10 min in status |

## "Looks Done But Isn't" Checklist

- [ ] **Rope climb:** Often missing the knock-off-mid-climb case. Verify: with a simulated hit during a climb, Up is released within one lease and the bot re-localizes.
- [ ] **Rope climb:** Often missing the portal guard. Verify: an Up hold is refused when the player x is in a forbidden zone or outside every rope window.
- [ ] **Drop-down:** Often missing the chord order guarantee. Verify: 1,000 seeded plans all have Down-down at least N ms before Jump-down.
- [ ] **Drop-down:** Often missing the "landed on rope" or "landed on wrong platform" outcome. Verify: the state machine has explicit outcomes other than success and fail.
- [ ] **Jump-up:** Often declared a success on a mid-air frame. Verify: success needs two confirmed landed frames on the target platform.
- [ ] **Move verification:** Often uses frames captured during the action. Verify: every verdict cites frame capture times later than key-up plus settle.
- [ ] **Layout:** Often valid only at the camera position where it was taught. Verify: the overlay stays aligned after climbing to the top platform and back.
- [ ] **Potions:** Often never tested while taking damage. Verify on replay or simulator: potion works while HP keeps falling, and no "out of potions" false stop.
- [ ] **Potions:** Often missing the empty or changed quickslot check. Verify: a removed potion stack leads to stop and alarm within one press.
- [ ] **Potions:** Often queued behind a long hold. Verify: the potion interrupt releases movement and presses within one frame of the decision.
- [ ] **Pet:** Often only a timer. Verify: hiding the pet (despawn) leads to feed, recheck, then stop and alarm.
- [ ] **Pet:** Often the timer resets on restart. Verify: `last_fed_at` persists or the bot prompts on start.
- [ ] **Stuck:** Often fires during attacks. Verify: no stall counts during attack, potion or wait intents.
- [ ] **Recovery:** Often unbounded. Verify: a link that always fails reaches safe stop within the configured budget.
- [ ] **Safe stop:** Often only on the happy path. Verify: an injected perception exception, capture loss, focus steal and F8 mid-climb each release keys, save a clip and alarm.
- [ ] **Alarm:** Often blocks a worker. Verify: the alarm runs on its own thread; key release happens before the sound starts.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Layout taught in screen coordinates | MEDIUM | Add anchors, then re-teach. If the spot provably never scrolls, keep the coordinates but add the "anchors moved means stop" check |
| Global hold cap raised | LOW to MEDIUM | Revert to a short cap; add per-kind leases; re-run keyboard watchdog tests |
| Input still on the capture thread when navigation is built | HIGH | Navigation timing is tuned around blocked frames, so everything must be re-tuned after moving input off-thread. Do P-Foundation first |
| Tracker drifted onto a monster or scenery during moves | MEDIUM | Make move success require confirmed fixes; add move-aware corridors; label rope and drop clips; benchmark |
| False "out of potions" stops | LOW | Switch to quickslot icon plus multi-press statistical verification |
| Thrashing targeting | LOW to MEDIUM | Platform-level targeting with hysteresis; route commitment |
| Alarm never fired on a crash | MEDIUM | Central idempotent `safe_stop`; HTTP server and alarm outlive the worker; fault-injection tests |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Open-loop moves on stale frames | P-Foundation, P-Moves | Decision log shows the capture time of the frame behind each verdict, later than key-up plus settle; simulator tests at 2.5-4 fps with jitter |
| 2. Hold cap vs climbing; blocking input | P-Foundation | Capture fps unchanged during actions; lease expiry releases Up in fake-backend tests; no global cap change |
| 3. Tracker stays at old position on fast moves | P-Moves (perception sub-task) | Labeled rope and drop clips: move-success detection precision and recall; no tracked-only verdicts |
| 4. Screen-pixel layout vs camera | P-Layout | Overlay aligned after a full spot traversal; anchor-loss leads to pause |
| 5. Chord order broken by randomizer | P-Foundation | Seeded ordering tests on every chord |
| 6. Up enters portals; Down at rope top; solid floors | P-Layout, P-Moves | Forbidden-zone refusal test; drop links validated during teaching; map-change stop |
| 7. Knock-off as a failed move | P-Recovery (hook in P-Moves) | Simulator knock-off during climb and approach leads to release, re-localize, re-plan; knock-off budget leads to stop |
| 8. Potion latency, false "out", wrong slot | P-Resources (interrupt in P-Foundation) | Replay or simulator with concurrent damage; slot-icon removal stop; measured trigger latency in status |
| 9. Blind pet timer | P-Resources | Pet-absent test leads to feed, recheck, stop; persisted `last_fed_at` |
| 10. Stuck detection misfires; captured keys | P-Recovery | Noise-floor-based thresholds from replay; no stalls during non-motion intents; "no effect" leads to stop |
| 11. Cross-platform thrashing | P-Targeting | Simulator: kills per minute vs route changes per minute; no stop on target loss during travel |
| 12. Safe-stop path fails | P-SafeStop (worker-death part in P-Foundation) | Fault-injection suite: every injected failure leads to keys released, clip saved, alarm |
| 13. Replay cannot validate closed loop | P-Moves | Kinematic simulator exists and covers moves, leases, recovery and stop paths |

## Sources

- Codebase (HIGH): `src/maplebot/decision.py` (single-platform `step`, 80 px and 8 px association, 5-step stall guard, 18 px platform tolerance), `src/maplebot/keyboard.py` (`execute` allows only left, right, attack, jump; `_execute_sequence` blocks; 5 ms watchdog with hold deadlines), `src/maplebot/autopotter.py` (two-frame low confirmation, cooldown from suggestion time, HP 0 treated as possible death), `config.toml` (`max_action_seconds = 0.25`, `nametag_partial = 0.6` vs scenery about 0.46, `track_max_seconds = 5`), `.planning/codebase/CONCERNS.md`, `.planning/PROJECT.md`, `docs/BACKLOG.md`.
- [MeowDB MapleStory Classic: Efficient Movement Guide](https://meowdb.com/msclassic/forum/guides/Kargo/efficient-movement-guide) (LOW): Up grabs ropes, jumping off ropes early, hits on ladders bump the player off, invincibility frames.
- [MeowDB MapleStory Classic: Pet Formulas](https://meowdb.com/msclassic/formulas/pets) (LOW, marked unconfirmed by the source): Pet Food +30, pet goes home at 5 fullness or less, feeding at 100 costs closeness, loot box sizes.
- [MeowDB Classic item DB: Elixir / Power Elixir](https://meowdb.com/msclassic/item-db/274) (LOW): 30 s cooldown on Elixir-type potions; pet auto-potion skill exists.
- [StrategyWiki: MapleStory walkthrough](https://strategywiki.org/wiki/MapleStory_Thief_Edition/Walkthrough) and [MeowDB Classic jump quest pages](https://meowdb.com/msclassic/jump-quest) (MEDIUM when cross-checked): Up at a portal enters it, Up at a rope grabs it; Down then Jump drops through a platform.
- [tanjeffreyz/auto-maple](https://github.com/tanjeffreyz/auto-maple) (LOW, different design): an open-source screen-based MapleStory bot that localizes from the minimap, with `move_tolerance` and `adjust` steps before commands. This supports the "tolerance band plus fine-adjust" approach to alignment.
- Web searches found nothing authoritative on player knock-off from ledges or ropes, on which footholds block a drop-down, or on HP bar update lag. Treat these as **open questions to measure in-game** in capture-only mode during P-Layout or P-Moves.

---
*Pitfalls research for: screenshot-driven MapleStory melee bot, navigation, potions and recovery milestone*
*Researched: 2026-10-24*
