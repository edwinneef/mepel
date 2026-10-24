# Architecture Research

**Domain:** Screenshot-driven 2D side-scroller grinding bot (MapleStory client, melee warrior, one taught screen), Windows, Python 3.12
**Researched:** 2026-10-24
**Confidence:** HIGH for integration with the existing code (taken from reading `decision.py`, `keyboard.py`, `runtime.py`, `replay.py`, `recorder.py`, `perception.py`). MEDIUM for MapleStory movement specifics (rope grab, drop-down chords, momentum), which come from community knowledge and need live verification. LOW for the few web sources, which only confirm general patterns.

## Answer in One Paragraph

Keep `Agent.step(observation, now) -> Decision` as the single pure entry point, but turn `Agent` into a thin coordinator over four new pure components: a **Layout** (taught platform and rope graph, plain data), a **Localizer** (observation plus layout gives "on platform P at x", "on rope R at y", "airborne", or "unknown"), a **Navigator** (Dijkstra planner plus a per-edge **MoveExecutor** state machine that verifies each move against the next frames), and a **priority Arbiter** that asks each behavior (Safety > Potion > Recovery > Upkeep (pet food, buffs) > Combat/Navigation) for a proposal on every tick and picks the highest. All time comes in through `now` (the capture timestamp), there is no randomness in the policy, and the policy's three inputs (observation, now, outcome of the previous action) are logged on every frame. Replay can then re-run the policy exactly, with no game and no keyboard. Keyboard timing jitter stays in `TimingPlanner`, outside the policy. The alarm sound and every other OS effect stay in `runtime.py`.

## Standard Architecture

### System Overview

```text
                       capture worker thread (unchanged ownership)
┌──────────────────────────────────────────────────────────────────────────┐
│ Capture ──► Perception (TemplateDetector)  ──► Observation               │
│             HudReader (from autopotter.py) ──► HudReading                │
│             SpotAnchor (new, in perception) ──► spot offset / lost       │
│                                   │                                      │
│                                   ▼                                      │
│ ┌──────────────────────── PURE POLICY (decision layer) ────────────────┐ │
│ │  PolicyInput(observation, hud, anchor, now, last_outcome)            │ │
│ │        │                                                             │ │
│ │        ▼                                                             │ │
│ │  Localizer ──► Localization (platform/rope/airborne/unknown, world)  │ │
│ │        │                                                             │ │
│ │        ▼                                                             │ │
│ │  Behaviors (each proposes, none acts):                               │ │
│ │   Safety    → stop+alarm (death, anchor lost, potions out, budget)   │ │
│ │   Potion    → hp/mp key, effect check                                │ │
│ │   Recovery  → await landing / replan / penalize edge                 │ │
│ │   Upkeep    → pet food / buff timers                                 │ │
│ │   Combat    → target select (all platforms) → approach/attack        │ │
│ │                 └─► Navigator: Planner(Layout) + MoveExecutor         │ │
│ │        │                                                             │ │
│ │        ▼                                                             │ │
│ │  Arbiter: highest-priority proposal wins this tick                   │ │
│ │        │                                                             │ │
│ │        ▼                                                             │ │
│ │  Decision(state, action: chord of KeyHolds, reason, nav, stop, alarm)│ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│                                   │                                      │
│        ┌──────────────────────────┼──────────────────────┐               │
│        ▼                          ▼                      ▼               │
│ KeyboardController.execute   Alarm (winsound,      Recorder.observe      │
│ (gates unchanged) → outcome   runtime only)        (policy input+output) │
│        │                                                                 │
│        └──► ActionOutcome fed into the NEXT PolicyInput                  │
└──────────────────────────────────────────────────────────────────────────┘

Offline: replay feeds logged PolicyInputs (or re-perceived frames) into the same policy.
Tests: a toy kinematic simulator closes the loop (action → fake player motion → Observation).
```

### Component Responsibilities

| Component | Owns | Pure? | Lives in | Talks to |
|-----------|------|-------|----------|----------|
| **Layout** | Platforms `(id, x0, x1, y)`, ropes/ladders `(id, x, y_top, y_bottom, kind)`, explicit links `(kind: jump_up / drop_down / jump_off, from, to, takeoff x-range)`, spot anchors, a version hash. Load, save and validation. | Yes (data plus JSON I/O) | new `layout.py` | Read by Localizer, Planner, annotate, debugger teaching commands |
| **SpotAnchor** | Turns screen coordinates into spot (world) coordinates each frame by matching 1-3 taught static terrain patches in a small search window. Falls back to the integrated `camera_shift`. Reports `anchor_lost`. | Yes (cv2 on the image) | `perception.py` (new class) | Produces the `anchor` field consumed by the Localizer and Safety |
| **HudReader** | HP/MP percent readings. This is the existing `PotionMonitor` reading half, without the preview policy. | Yes | `autopotter.py` | Produces the `HudReading` consumed by Potion and Safety |
| **Localizer** | Maps player feet (world coordinates) to a node: on platform P at x, on rope R at y, airborne, or unknown. Uses hysteresis (keeps the last node for k frames while the evidence is ambiguous) and the `tracked` flag. Also assigns each monster to a platform. | Yes, small state | new `localize.py` | Inputs: Observation, anchor, Layout. Output: `Localization` |
| **Planner** | Dijkstra over the graph (nodes are platforms and ropes; edges are rope grab/exit and taught links). Cost is walk distance to takeoff plus base edge cost plus failure penalty. | Yes, stateless function | new `navigation.py` | Called by Navigator; reads Layout and the penalty table |
| **MoveExecutor** | One edge at a time: `ALIGN` (walk to the takeoff x-range) → `PERFORM` (emit the chord) → `SETTLE` (release; wait while airborne) → `VERIFY` (expected node reached within N frames or T seconds) → `DONE` or `FAILED(reason)`. | Yes, explicit state | `navigation.py` | Owned by Navigator; reads Localization and `last_outcome` |
| **Navigator** | Holds the goal node, the current route and the active executor. Replans every tick from the actual localization, so a knock-off is handled by the replan. Keeps an edge-failure penalty table and a recovery budget. | Yes | `navigation.py` | Used by Combat (goal = target's platform) and Recovery |
| **Behaviors** | `propose(ctx) -> Proposal(priority, action, reason) or None`, plus their own timers and counters. | Yes | new `scheduler.py` (Potion, Upkeep, Safety, Recovery); `decision.py` (Combat, refactored from today's FSM) | Arbiter only |
| **Arbiter** | Sorts proposals by fixed priority and returns the winner. Applies preemption rules (an in-flight `PERFORM` is never cut by a lower priority). Records suppressed proposals for the debugger. | Yes | `scheduler.py` | Called by `Agent.step` |
| **Agent (coordinator)** | Same public API: `start`, `stop`, `step`. Builds the context, runs Localizer → behaviors → Arbiter, and returns a `Decision`. Exposes `snapshot()` (serializable policy state). | Yes | `decision.py` | `runtime.py`, `replay.py`, tests |
| **Runtime adapter** | Passes the capture `now` into `step`, executes `decision.action`, turns the controller's result string into `ActionOutcome`, plays the alarm, and triggers the recorder. | No (I/O) | `runtime.py` | Everything I/O |
| **KeyboardController** | Unchanged gates. Extended `KEYS` and `ACTIONS` (up, down, potion, pet, skill keys), and opposite-pair checks extended to up/down. | No | `keyboard.py`, `input_timing.py` | Runtime only |

## Recommended Project Structure

The package stays flat, matching the current convention of no sub-packages and one test file per module.

```text
src/maplebot/
├── layout.py        # NEW: Layout, Platform, Rope, Link, Anchor; load/save/validate; version hash
├── localize.py      # NEW: Localizer, Localization (pure; hysteresis state)
├── navigation.py    # NEW: plan() (Dijkstra), Route, MoveExecutor, Navigator, EdgeKind
├── scheduler.py     # NEW: Proposal, Arbiter, Timer, PotionBehavior, UpkeepBehavior,
│                    #      RecoveryBehavior, SafetyBehavior
├── decision.py      # CHANGED: Action gains chord holds; Decision gains nav/stop/alarm fields;
│                    #          today's FSM becomes CombatBehavior; Agent becomes the coordinator
├── perception.py    # CHANGED: SpotAnchor (world offset + anchor_lost); Observation unchanged
├── autopotter.py    # CHANGED: split HudReader (pure reading) from the preview policy
├── keyboard.py      # CHANGED: more KEYS; execute() accepts chord Actions
├── input_timing.py  # CHANGED: ACTIONS extended; opposites = {left/right, up/down}
├── runtime.py       # CHANGED: pass capture `now`; ActionOutcome feedback; alarm; layout commands
├── recorder.py      # CHANGED: log PolicyInput + Decision + policy snapshot per frame
├── replay.py        # CHANGED: add policy-only replay over logged PolicyInputs
└── static/index.html# CHANGED: layout teaching overlay, nav panel

data/spots/<spot>/layout.json      # taught layout + anchors (runtime data, gitignored)
data/spots/<spot>/anchors/*.png    # anchor patches
tests/test_layout.py, test_localize.py, test_navigation.py, test_scheduler.py
tests/sim.py                       # toy kinematic simulator for closed-loop tests (test helper only)
```

### Structure Rationale

- **`layout.py` is separate from `navigation.py`:** the layout is persisted, operator-taught data with its own validation and versioning. The navigator is behavior. The debugger teaching commands should depend only on `layout.py`.
- **`localize.py` is separate from perception:** perception answers "where is the sprite on screen". Localization answers "which taught node is that", which needs the layout and hysteresis. Folding it into `perception.py` would make perception depend on the layout and would break today's dependency rule that perception knows nothing of policy.
- **`scheduler.py` is separate from `decision.py`:** potions, pet food and safety don't depend on combat. Keeping them out of the combat FSM stops `decision.py` from turning into the next 600-line `runtime.py`.
- **`tests/sim.py` is test-only:** it is the cheapest way to test navigation closed-loop. It must never be imported by `src/`, so a fake world can't leak into a live session.

## Architectural Patterns

### Pattern 1: Policy as a pure function of logged inputs (deterministic core)

**What:** Everything the policy reads is in one frozen `PolicyInput`, which is logged every frame. The policy's internal state is explicit and serializable through `Agent.snapshot()`.

```python
@dataclass(frozen=True)
class PolicyInput:
    observation: Observation          # existing
    hud: HudReading | None            # hp/mp percent + confidence
    anchor: AnchorReading             # world offset (dx, dy), confidence, lost: bool
    now: float                        # CAPTURE timestamp, never perf_counter() at decide time
    last_outcome: ActionOutcome       # COMPLETED | INTERRUPTED | BLOCKED | NOT_SENT (dry run)
```

**Rules:**
- Pass the capture timestamp. `runtime.py` currently calls `self.agent.step(observation, time.perf_counter())` while replay passes the recorded `captured_at`. The two diverge by the 250-400 ms processing time, and every timer and verify window drifts with it. This must be fixed before navigation timing goes in.
- No `random`, no wall clock, no `time.*` in `decision.py`, `localize.py`, `navigation.py` or `scheduler.py`. Iterate over sorted ids, never over set order.
- Jitter belongs to `TimingPlanner` (keyboard side), so it changes only key timings, never decisions.
- Log `layout.version` in the session header. A replay against a different layout must refuse to run or warn.

**When to use:** Always. This is what keeps "replayable offline" true once timers and multi-tick moves exist.
**Trade-offs:** The per-frame log gets larger. The observation already serializes with `asdict`, as replay does today, and costs about 1-2 KB per frame, which is small next to the PNG.

### Pattern 2: Priority arbiter over proposing behaviors (not one big FSM)

**What:** Each behavior looks at the shared context and returns at most one `Proposal`. The arbiter picks the highest priority. Only the winner's action is sent, but every behavior's timers and counters update on every tick, so a pet-food timer keeps counting while a potion wins.

```python
class Priority(IntEnum):
    SAFETY = 100     # stop + alarm; always wins
    POTION = 80      # HP below threshold (HP above MP)
    RECOVERY = 60    # airborne after knock-off, replan, unstick
    UPKEEP_DUE = 50  # pet food / buff overdue past hard deadline
    COMBAT = 30      # navigation + approach + attack
    UPKEEP_SOON = 20 # pet food / buff due; taken only when nothing else wants the tick

def arbitrate(proposals: list[Proposal], executor_phase: Phase) -> Proposal:
    best = max(proposals, key=lambda p: (p.priority, p.tiebreak))
    if executor_phase is Phase.PERFORM and best.priority < Priority.SAFETY:
        return proposals_by_source["navigation"]   # never split a jump/drop chord
    return best
```

**Why not extend the current FSM:** Interrupts in a flat FSM mean wiring "low HP → potion → back to where I was" into every state. A per-tick priority choice gives preemption with no transition wiring, and the "resume where I left off" behavior falls out of the fact that `Navigator` and `CombatBehavior` keep their own state while they are suppressed. This is the standard HFSM/behavior-tree hybrid (top-level priorities, small FSMs inside each behavior), cut down to a list and a `max()`. A behavior-tree library would be overkill for five behaviors.

**Two-tier upkeep:** pet food has a soft due time (taken when the bot is grounded and nothing else wants the tick) and a hard deadline (outranks combat). This stops a pet-food press from landing in the middle of an approach every few minutes, while still guaranteeing it happens.

**Trade-offs:** Priorities are global and static, which is right for this scope. The one exception that is needed, "don't cut a chord", is handled by the executor-phase rule above.

### Pattern 3: Taught graph with node-internal motion

**What:** Graph nodes are platforms and ropes. Inside a node, motion is one-dimensional: walk to x on a platform, climb to y on a rope. Edges are only the discrete transitions:

| EdgeKind | From → To | Takeoff | Chord (configurable) | Expected result |
|----------|-----------|---------|----------------------|-----------------|
| `grab_rope` | platform → rope | `abs(x - rope.x) <= tol` | up (or jump then up, when the rope bottom is above the feet) | on rope R within N frames |
| `climb_exit_top` | rope → upper platform | top of rope | hold up repeatedly | on platform P |
| `climb_exit_bottom` | rope → lower platform | bottom | hold down, or jump off | on platform P |
| `jump_off` | rope → platform | any y | left/right + jump | on platform P (or airborne, then P) |
| `jump_up` | platform → platform | taught x-range | direction + jump | on upper P |
| `drop_down` | platform → platform | taught x-range | down + jump chord | on lower P |
| `walk_off` | platform → platform | platform end | direction | on lower P |

Rope-to-platform and platform-to-rope edges can be generated from geometry (a rope whose top or bottom lies within tolerance of a platform). `jump_up`, `drop_down` and `walk_off` must be drawn by the operator, because the layout is taught, not detected.

**Why:** Auto Maple, the best-known open-source MapleStory bot, stores a point cloud in a quadtree and runs A* with "teleport" neighbors, then moves with blocking loops and a shared 15-step budget that gives up silently. That suits a mobility-skill class with minimap coordinates. It doesn't suit a melee warrior on ropes and ledges, where the transitions are discrete and each one needs its own success check. With an explicit graph of 3-10 nodes, Dijkstra is trivial, every edge has a named failure mode, and the route can be drawn in the debugger.

### Pattern 4: Act, then verify on later frames (one bounded chord per tick)

**What:** The worker loop is already synchronous: capture, about 300 ms of processing, `execute()` (blocking, at most `max_action_seconds` = 0.25 s, plus rest), then the next capture. So every frame is taken after the previous action finished, and the `MoveExecutor` advances one phase per tick:

```text
tick n:   ALIGN    walk toward takeoff (existing short-step + no-progress counter)
tick n+1: PERFORM  emit chord (e.g. down 0.18s + jump at +0.04s 0.08s)  -> last_outcome
tick n+2: SETTLE   release; Localization == AIRBORNE/UNKNOWN is expected, not an error
tick n+k: VERIFY   Localization.node == edge.to  -> DONE
                   node == edge.from after settle window -> FAILED("no effect")
                   node is a third node           -> FAILED("diverted"), replan from there
                   now > deadline                  -> FAILED("timeout")
```

Climbing a long rope is several ticks of `up` held for 0.25 s each, with progress checked on y, the same way the current approach counter checks progress on x. Don't raise `max_action_seconds` to make climbing one action. The bound is a safety property.

**Dry run:** when `last_outcome == NOT_SENT`, the executor must not mark the edge as failed. It reports "PERFORM (dry run, unverified)" and stays put. Without this, every dry run of navigation would fail verification, fire recovery and penalize edges.

### Pattern 5: Recovery is replanning plus a budget, not a separate mode

- **Knocked off:** the Localizer reports a node that isn't on the plan. The Navigator replans from the actual node. That counts as one recovery attempt, not a failure.
- **Stuck:** an edge fails, so its penalty goes up (for example, +cost × 3 that decays over minutes) and the planner naturally picks an alternative route. After the same edge fails k times, or the route has no alternative, Safety wins the next tick.
- **Lost target:** the existing `VERIFY` / "target absent" logic, then back to target selection.
- **Hidden player:** while `player.tracked` is true and within the existing 5 s cap, hold position (release) and don't start new edges. After the cap, the Localizer reports unknown, and after k frames Safety stops.
- **Budget:** N recovery attempts within a sliding window of T seconds. Once it's exhausted, Safety proposes stop + alarm with the reason "repeated failed recovery". All counters live in `RecoveryBehavior` and are logged in `snapshot()`.

## Data Flow

### Per-Tick Flow (live)

```text
frame (captured_at = now)
  ├─► TemplateDetector.detect(image, now) ─► Observation
  ├─► HudReader.read(image)               ─► HudReading
  └─► SpotAnchor.update(image)            ─► AnchorReading
             │
             ▼
PolicyInput(observation, hud, anchor, now, last_outcome)   ──► recorder (logged)
             │
Agent.step(input)
  1. Localizer.update(obs, anchor, layout) ─► Localization (player node + monster→platform)
  2. every behavior .tick(ctx)  (timers/counters advance; never skipped)
  3. proposals = [b.propose(ctx) for b in behaviors]
  4. winner = arbitrate(proposals, navigator.executor.phase)
  5. Decision(state, action, reason, nav=NavSnapshot, stop, alarm, suppressed)
             │                                              ──► recorder (logged)
             ▼
runtime: if decision.stop: _stop(reason); if alarm: play sound (async)
         elif live: outcome = controller.execute(action)
         elif dry_run: outcome = NOT_SENT
         last_outcome = ActionOutcome.from_result(outcome) ─► next tick
```

### Offline Flows

1. **Frame replay (existing, extended):** PNG frames → perception → policy. `last_outcome` comes from the logged value for that frame, because no input is ever sent offline. This tests perception and policy together.
2. **Policy replay (new):** logged `PolicyInput`s → policy only. The new decisions are diffed against the logged decisions. This is exact and fast (no cv2), and any diff is a behavior change. Recorded incidents turn into regression fixtures under `tests/`.
3. **Closed-loop simulation (new, tests only):** `tests/sim.py` keeps a fake player (x, y, node) and applies simple kinematics to each `Action` (walk speed, climb speed, a jump arc lasting about 2 ticks, a drop-down that lands on the next lower platform, random knock-offs from a seeded RNG). It produces `Observation`s. This is the only way to test "route A→C via a rope, knocked off midway, recover" without the game. The kinematics don't need to be accurate. They only need to show the cases the executor must handle (in air, landed elsewhere, no effect).

### State Ownership

| State | Owner | Persisted | Logged per frame |
|-------|-------|-----------|------------------|
| Layout | `layout.py` file | `data/spots/<spot>/layout.json` | version hash in session header |
| Localization hysteresis | Localizer | no | yes (`nav.node`, `nav.confidence`) |
| Route, executor phase, edge penalties | Navigator | no (resets each session) | yes |
| Potion cooldowns, effect check, misses | PotionBehavior | no | yes |
| Pet food / buff timers | UpkeepBehavior | **last-fed time optional**, see Pitfalls | yes |
| Recovery attempts / window | RecoveryBehavior | no | yes |
| Combat target / attempts | CombatBehavior | no | yes (today's fields) |

## Integration With Existing Code (specific changes)

| Existing piece | Change | Why |
|----------------|--------|-----|
| `Agent.step(observation, now)` | Keep the signature. Add `step_input(PolicyInput)`; `step()` builds a default `PolicyInput` so existing tests keep passing. | Smallest break; `tests/test_decision.py` survives |
| `runtime._process` → `agent.step(observation, time.perf_counter())` | Pass the capture `now`. | Determinism bug: live and replay times differ today |
| `Action(kind, seconds)` | Add `holds: tuple[KeyHold, ...] = ()`. Legacy kinds map to one hold. `KeyboardController.execute` sends `holds` through the existing `execute_sequence`. | Chords (down+jump, direction+jump) already work in `execute_sequence`; only the `Action` type is missing |
| `KEYS`, `ACTIONS`, `InputConfig` | Add up, down, hp_potion, mp_potion, pet_food, skill (config-mapped). Opposites: left/right and up/down. | Climbing, dropping, potions, pet food, skill |
| `controller.execute` return string | Turn it into `ActionOutcome` in runtime and feed it into the next tick. | The executor needs to know whether the chord actually ran |
| `PotionMonitor` (preview policy) | Split it: the HUD reading stays; the decision moves to `PotionBehavior` in the policy. | Potions must take part in arbitration and be replayable |
| `Decision.state` (`State` enum) | Keep it for the top-level label; add a `nav` snapshot and `behavior` (the winner's name). | Debugger and recorder show route and recovery |
| `annotate(...)` | Draw the layout overlay, current node, route polyline and current edge takeoff. | Requirement: debugger shows navigation state |
| `_command` + stop-first set | Add `layout_*` teaching commands (`layout_platform`, `layout_rope`, `layout_link`, `layout_anchor`, `layout_save`, `layout_load`) to both places. | Existing anti-pattern rule; teaching mutates what the policy reads |
| `_stop(reason)` | Accept `alarm: bool`; play the sound with `winsound.PlaySound(..., SND_ASYNC)` or `MessageBeep`, called from runtime only. | Keeps OS calls out of the pure modules |
| `recorder.observe(stem, raw, status, now)` | Add `policy_input` and `decision` (asdict) to the line, and `layout.version` to the session header. | Enables policy replay |
| `replay.run_replay` | Load the layout; add a `--policy-only` mode over `decisions.jsonl`. | Offline verification of navigation |

## Suggested Build Order

Dependencies run top to bottom. Each step can be tested offline before the next one starts.

1. **Determinism groundwork** (no new behavior). Pass the capture `now`, add `ActionOutcome` feedback, `PolicyInput`, and the expanded recorder line, and add policy-only replay plus a diff. *Everything later depends on this being trustworthy, and it's cheap now while the policy is small.*
2. **Action vocabulary and keys.** Add `Action.holds`, the new KEYS and ACTIONS, the up/down opposite rule, and config keys for potion, pet, skill, up and down. Add control probes for the new keys, reusing the existing probe flow. *Needed by every later behavior; touches the safety-critical controller, so do it in isolation.*
3. **Arbiter plus Potion and Upkeep behaviors.** Refactor today's FSM into `CombatBehavior` (single platform, unchanged logic), add the arbiter, and wire real potion keys with the effect check and the "potions exhausted" stop. Add the pet-food timer. *Delivers value on the existing single-platform combat before any navigation exists, and proves the arbiter.*
4. **Safety behavior plus alarm.** Death, unexpected screen, potions out, budget exhausted → stop + alarm, with the recorder trigger. *Must exist before the bot is allowed to move between platforms unattended.*
5. **Layout model plus teaching UI plus SpotAnchor.** `layout.py`, the debugger drawing on a frozen frame, anchors, and the overlay. Capture-only is enough to build and verify it. *Pure data and UI; the next step needs it.*
6. **Localizer.** Platform/rope/airborne classification with hysteresis, and monster-to-platform assignment. Verify by replaying recorded sessions with the layout overlay before any movement code exists. *Highest perception risk; prove it on recordings first.*
7. **Planner plus MoveExecutor plus `tests/sim.py`.** One edge kind at a time: walk → grab_rope/climb → drop_down → jump_up → jump_off. Test closed-loop in the simulator, then live per edge kind using dry run (route only) and then armed. *Needs research per edge kind (chords, timings, settle windows).*
8. **Multi-platform targeting plus Recovery.** Target selection by route cost, edge penalties, the recovery budget, and knock-off replanning. *Needs a working Navigator.*
9. **Skill attack with MP fallback.** Small. It can go anywhere after step 3, but it's cleaner once HUD readings are in the policy.

Steps 3-4 and step 5 don't depend on each other and can run in parallel.

## Scaling Considerations

The only scale that matters here is frame rate and session length.

| Concern | At ~3 fps (now) | At 8-12 fps (if capture gets faster) |
|---------|-----------------|--------------------------------------|
| Verify windows | Express windows in **seconds** with a minimum frame count (for example, `max(0.8 s, 2 frames)`), never in frames alone | Same config keeps working |
| Jump/drop observation | Often 0-1 airborne frames are seen, so SETTLE must tolerate never seeing the player in the air | More in-air frames; hysteresis must not flicker |
| Log size | ~1-2 KB per frame of JSON is fine | Still fine; frames dominate |
| Planner cost | Dijkstra on <20 nodes, microseconds; replan every tick | Same |

### Scaling Priorities

1. **First bottleneck:** frame latency. Settle and verify logic tuned in frames breaks the moment the frame rate changes. Use seconds plus a minimum frame count from day one.
2. **Second bottleneck:** localization flicker near platform edges and rope bottoms, where feet y matches two nodes. Use hysteresis plus a "prefer the planned node" tie-break.

## Anti-Patterns

### Anti-Pattern 1: Blocking movement loops inside the policy

**What people do:** `while not arrived: press(); sleep(0.15)`, which is Auto Maple's `Move` design.
**Why it's wrong:** It bypasses the per-frame safety checks (the 500 ms processing gate, focus, the emergency path through `_process`), it can't be replayed frame by frame, and potions can't preempt it.
**Do this instead:** One bounded chord per tick, with the executor phase stored as state.

### Anti-Pattern 2: Screen-space layout coordinates

**What people do:** Save platform y values as screen pixels.
**Why it's wrong:** The MapleStory camera follows the player and scrolls when the map is larger than the viewport. Even a "single-screen" spot can shift vertically when the player climbs. Screen-space platforms then drift off the real ones. Summing `camera_shift` frame to frame also drifts over minutes.
**Do this instead:** Store spot coordinates relative to taught anchors and re-anchor absolutely every frame. When the anchors are lost, treat it as an unexpected screen or map change and let Safety stop.

### Anti-Pattern 3: Timers on wall clock or `perf_counter()` inside behaviors

**What people do:** `time.time()` for pet-food intervals.
**Why it's wrong:** Replay shows different upkeep presses, and policy replay diffs become noise.
**Do this instead:** Behaviors only read `ctx.now`.

### Anti-Pattern 4: Verifying moves by "the key was sent"

**What people do:** Treat `sequence completed` as "moved".
**Why it's wrong:** In MapleStory a drop-down chord on a solid bottom platform, or a rope grab 6 px off, does nothing. Treating it as success leaves the plan out of sync with reality.
**Do this instead:** Success comes only from the Localizer reporting `edge.to`. `ActionOutcome` only tells the executor whether to start the settle window or to retry the perform step.

### Anti-Pattern 5: Potion logic stays outside the policy

**What people do:** Keep `PotionMonitor` as a side component that presses keys itself.
**Why it's wrong:** You get two writers to the keyboard and no priority between them, and potions vanish from replay.
**Do this instead:** The HUD reading is a policy input, and the potion is a proposal. There is exactly one `controller.execute` per tick.

### Anti-Pattern 6: Alarm and sound inside the policy

**Do this instead:** `Decision.alarm = True`; runtime plays it. This keeps `decision.py` importable on non-Windows CI, as the existing rule requires.

## Integration Points

### External

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| MapleStory client window | Unchanged: pixels in through MSS, keys out through SendInput behind `KeyboardController` | New keys (up/down/potion/pet) need control probes like the existing four |
| Windows sound | `winsound` (stdlib), asynchronous, from runtime | No new dependency; matches "stay within stack" |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| perception → policy | `PolicyInput` (frozen dataclasses) | Perception never imports the layout or policy |
| layout ↔ localize/navigation | Read-only `Layout` object | Swapped only via a stop-first debugger command |
| behaviors ↔ arbiter | `Proposal` values | Behaviors never call each other; Combat owns the Navigator |
| policy → runtime | `Decision` (+ `stop`, `alarm`, `nav`) | Runtime never inspects behavior internals |
| runtime → policy | `ActionOutcome` on the next tick | The only feedback channel from I/O |
| policy → recorder | `asdict(PolicyInput)`, `asdict(Decision)`, `agent.snapshot()` | Enables exact policy replay |
| debugger → layout | `POST /api/layout_*` → `_command` (stop-first) | Same rule as `template`/`crop` |

## Open Questions for Phase Research

- Exact MapleStory chords and timings on this client: rope grab (up alone vs jump+up), drop-down (down+jump, and whether the chosen jump key allows it), jump-off-rope, ladder vs rope differences, and post-landing slide distance. **Verify live per edge kind before coding the executor's numbers** (MEDIUM confidence today).
- Whether this spot's camera scrolls at all. If the map fits the viewport, SpotAnchor reduces to a map-change detector. Find out by looking at existing recordings.
- Potion-effect latency: how quickly the HP bar rises after a key press on this server, which sets the "potions exhausted" detection window.
- Death and unexpected-screen detection signals (tombstone, dialog box, black loading screen). The Safety behavior needs at least one cheap pixel heuristic per case.

## Sources

- Codebase: `src/maplebot/decision.py`, `keyboard.py`, `runtime.py` (`_process`), `replay.py`, `recorder.py`, `perception.py`, `.planning/codebase/ARCHITECTURE.md`, `STRUCTURE.md`, `.planning/PROJECT.md` (HIGH, read directly)
- Auto Maple layout and movement design (LOW, web; source read through raw GitHub): https://github.com/tanjeffreyz/auto-maple (`src/routine/layout.py`, `src/routine/components.py`), summary at https://awesome.ecosyste.ms/projects/github.com%2Ftanjeffreyz%2Fauto-maple
- Navigation graphs with one-way edges (LOW, web): https://artemis.ms.mff.cuni.cz/pogamut_files/latest/doc/tutorials/ch05s03.html
- HFSM vs behavior tree priority and preemption (LOW, web): https://arxiv.org/pdf/1709.00084, https://imada.sdu.dk/u/march/Teaching/AY2012-2013/DM810/Slides/dm810-lec8.pdf

---
*Architecture research for: screenshot-driven MapleStory platform-navigation and scheduling bot*
*Researched: 2026-10-24*
