# Phase 1: Deterministic Input and Safe Stop - Context

**Gathered:** 2026-10-24
**Status:** Executed through Plan 01-03; Plan 01-04 awaiting remaining acceptance

<domain>
## Phase Boundary

Every decision replays exactly from recorded frames (capture timestamp as `now`, policy-only replay with diff). Keyboard actions stop blocking capture, and per-stage frame timing is visible with PNG encoding moved off the capture worker. The new keys exist: Up, Down, HP potion, MP potion, pet food and skill, with the extended-key flag fix. Up/Down holds are renewable leases under the unchanged global cap, and Down+Jump / direction+Jump are ordered chords. Every stop, including a worker crash, releases keys, saves the clip, shows a structured reason, and alarm-level stops sound a repeating alarm until acknowledged.

Requirements: FND-01..06, SAFE-01..03. Stop *triggers* tied to the taught spot (SAFE-04) belong to Phase 2. Potion/skill/pet *behavior* belongs to Phase 3. This phase only binds and probes those keys.

</domain>

<decisions>
## Implementation Decisions

### Key binding
- **D-01:** New keys are bound in `config.toml` `[input]` only, as new fields on `InputConfig`, next to left/right/attack/jump. The debugger shows the current bindings read-only. There is no binding UI and no second source of truth in `data/`.

### Control probes and the arming gate
- **D-02:** Arming requires probes only for keys the policy can send in this phase: left, right, attack, jump, plus skill. Probes for Up, Down, HP potion and MP potion are offered in the debugger. Each one becomes *required* for arming in the phase that starts sending that key: Up/Down in Phase 4, potions in Phase 3. Probe permissions stay in-memory and reset on restart, as today.
- **D-03:** Up probe guard: the debugger warns "stand away from portals and ropes". Then the normal 3 s focus countdown runs, followed by one short tap capped by the hold cap. The operator confirms by watching, like the existing probes. Down uses the same flow. The probe exists to prove that Up arrives as the arrow key, not numpad 8.
- **D-04:** HP/MP potion probes confirm themselves from the HUD bar. After one press, the probe passes if the matching bar rises within a bounded window. If the bar is at or above ~95%, the probe is refused with an actionable message (for example "HP is full; take damage first"). It does not press.
- **D-05:** Pet food is bound in Phase 1 but has no probe. The pet-food probe moves to Phase 3 with feeding.

### Alarm
- **D-06:** The alarm is a WAV bundled as package data next to `static/`. It loops through `winsound` `SND_FILENAME|SND_ASYNC|SND_LOOP` and stops with `PlaySound(None, 0)`. If the file is missing or playback fails, it falls back to repeated `MessageBeep`. It is played only from runtime, never from `decision.py`.
- **D-07:** F8 acknowledges an active alarm. After an alarm stop, keys are already released, so F8 has no other job. The debugger also gets an Acknowledge button. Either one silences the alarm.
- **D-08:** Stops caused by the operator are silent: the F8 emergency stop and the debugger Stop button.
- **D-09:** Severity split for the existing stop paths. **ALARM:** capture worker crash, input watchdog or backend failure, focus or obscuration lost while armed, calibration invalid while armed, player uncertain while armed, debugger command timeout. **SILENT (pause):** no targets, operator stop, dry-run stops, capture-only stops, probe finished. New stop reasons in later phases must declare a severity.
- **D-10:** The alarm repeats until acknowledged. It never times out by itself.

### After a stop
- **D-11:** The debugger shows a sticky stop banner with severity, a stable reason code, the message, the time and the saved clip path. It stays until the alarm is acknowledged or the bot is re-armed. Every stop also goes into the existing history list with its code.
- **D-12:** After acknowledging, the operator can arm again without re-probing. The existing arm gates still apply: confirmed player, 3 s countdown, calibration. Probes are cleared only when the cause touched input: calibration change, focus or window change, or input backend failure.
- **D-13:** A capture worker crash releases keys and starts the alarm without needing the worker. The debugger stays usable, and Acknowledge works without the dead worker. A fresh worker restarts in IDLE with input disabled and all probes cleared. The operator must recalibrate (or re-verify), probe and arm again.

### Claude's Discretion
- Input threading model: a dedicated input thread, or synchronous with renewable leases on the watchdog. The roadmap defers this to planning, and research recommends leases on the watchdog with input off the capture thread.
- Lease length, the hard per-kind maximum, and the potion-probe effect window. All bounded, all in `config.toml` with validation.
- Policy-only replay diff: what fields count as a difference, the report format, and whether pre-Phase-1 recordings are supported (they lack `PolicyInput`). The user chose not to discuss this.
- Whether arming is refused while an alarm is still unacknowledged. Refusing is the suggested default, because arming with the alarm still sounding would be confusing.
- Stop reason code names and the banner layout.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scope and requirements
- `.planning/ROADMAP.md` §"Phase 1" — goal, success criteria, research flag (threading decision)
- `.planning/REQUIREMENTS.md` — FND-01..06, SAFE-01..03 wording; Out of Scope table
- `.planning/STATE.md` — Blockers/Concerns (Phase 1 threading decision)

### Research
- `.planning/research/SUMMARY.md` — Phase 1 "Determinism and Input Foundation" and "Safety Stop and Alarm" deliverables; extended-key bug (Up sent as numpad 8); winsound usage; input-thread vs synchronous conflict
- `.planning/research/ARCHITECTURE.md` — `PolicyInput`, `ActionOutcome`, policy-only replay, `Decision.stop`/`alarm`, alarm-in-runtime anti-pattern
- `.planning/research/PITFALLS.md` — Pitfall 2 (hold cap / blocking input, per-kind leases), Pitfall 5 (chord order), Pitfall 12 (idempotent safe_stop, alarm outlives dead worker)
- `.planning/research/STACK.md` — PNG encode cost on worker (~64 ms), MSS timing, no new deps

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/CONCERNS.md` — threading model, stop path, conventions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `KeyboardController` (`src/maplebot/keyboard.py`): `enable`, `stop`, `release_all`, `_watch` watchdog thread, `execute_sequence`. Leases and chords extend it. The gates stay as they are.
- `KEYS` (`keyboard.py:17`): has only left/right/a/d/z/ctrl/space/f8. Extend it, and set `KEYEVENTF_EXTENDEDKEY` for the full extended set (arrows, Insert, Delete, Home, End, PgUp, PgDn).
- `ACTIONS` / `KeyHold` / `TimingPlanner` (`src/maplebot/input_timing.py`): jitter stays here, outside the policy. Chords must keep their order under jitter.
- Probe flow (`src/maplebot/runtime.py` ~273-295, 435-460): `probed` set, `probe_wait` mode, 3 s `pending_at`. Generalize it from the fixed 4-key set.
- `SessionRecorder.trigger` (`src/maplebot/recorder.py`): already saves the clip on `_stop`.
- `PotionMonitor` / HP-MP bar readings (`src/maplebot/autopotter.py`): the source for the potion probe auto-check (D-04).
- `app.note` and the history deque: where stop entries go (D-11).

### Established Patterns
- Config: frozen dataclass + `__post_init__` validation + key in `config.toml`. An unknown key raises `TypeError`, so keep them in sync.
- Cross-thread commands go through `Application.commands` with Futures. Acknowledge must work even when the worker is dead (D-13), so it cannot depend only on the worker draining the queue.
- `decision.py` stays pure, with no winsound or keyboard imports. `Decision` carries stop/alarm intent, and runtime acts on it.
- Action result strings ("blocked: duration", "sequence completed", "release") are matched by runtime and tests. Preserve them.

### Integration Points
- `Application._run` (`runtime.py` ~529-600): capture timestamp, per-stage timing, PNG encode currently inline at ~551. Move it off the worker.
- `Application._stop` (`runtime.py:177`): becomes the central idempotent stop with severity, callable from any thread, including the worker's `finally`.
- `agent.step(observation, time.perf_counter())` at ~477: must receive the capture timestamp.
- `debugger.py` / `static/index.html`: add the stop banner, Acknowledge button, timing panel, read-only bindings, and new probe buttons.
- `pyproject.toml` package-data: add the alarm WAV.

</code_context>

<specifics>
## Specific Ideas

- The Up probe's purpose is to prove the extended-key fix: Up must reach the game as the arrow key, not numpad 8.
- The potion probe must not press when the bar is full. It refuses with an operator-action message, in keeping with the "recalibrate / Return to live" style.

</specifics>

<deferred>
## Deferred Ideas

- Pet-food probe: Phase 3, alongside timed feeding (SUST-06).
- Requiring the Up/Down probes for arming: Phase 4. Requiring the potion probes for arming: Phase 3.

</deferred>

---

*Phase: 01-deterministic-input-and-safe-stop*
*Context gathered: 2026-10-24*


## Operator overrides recorded on 2026-10-25

The operator explicitly requested persistent successful probes and standalone live Autopotter after confirming the seven movement/combat/potion controls worked. These later requests supersede the memory-only/reset-all parts of D-02, D-12 and D-13 and the earlier preview-only scope. Matching title/layout/DPI/crop/binding restores control confirmations; each potion also matches its HUD reference. Starting a retest revokes its prior confirmation. Capture verification still resets and input always starts stopped. Standalone live potions require the matching potion confirmations and do not arm combat. Full Phase 3 sustain requirements remain unimplemented. See 01-04-CHECKPOINT.md for current evidence, remaining acceptance and commit-backed implementation details.
