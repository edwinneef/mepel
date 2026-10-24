# Phase 1: Deterministic Input and Safe Stop - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md. This log preserves the alternatives considered.

**Date:** 2026-10-24
**Phase:** 01-deterministic-input-and-safe-stop
**Areas discussed:** New keys: bind & probe, Alarm & acknowledge, After a stop

---

## New keys: bind & probe

| Question | Options | Selected |
|----------|---------|----------|
| Where to bind | config.toml only / Debugger UI saved to disk | config.toml only |
| Probe gate | Only keys the policy can use / All bound keys always / Probe once per binding change | Only keys the policy can use |
| Up probe guard | Operator positions then confirms / Only on a rope / Key-state only | Operator positions then confirms |
| Item probe confirm | Operator confirms / Auto-check HP/MP bar / You decide | Auto-check HP/MP bar |
| Full bar | Refuse until <95% / Fall back to operator confirm / Accept no-change | Refuse until <95% |
| Pet probe | Operator confirms / Skip in Phase 1 | Skip in Phase 1 |
| Effect wait window | You decide / Fixed 2 s configurable | You decide |

---

## Alarm & acknowledge

| Question | Options | Selected |
|----------|---------|----------|
| Sound | Bundled WAV looping / Operator WAV path / System sound only | Bundled WAV looping |
| F8 role during alarm | F8 acknowledges / Debugger button only | F8 acknowledges |
| Operator-caused stop | Silent / F8 alarms, Stop button silent | Silent |
| Severity split | Proposed split / Everything while armed alarms / You decide | Proposed split |

---

## After a stop

| Question | Options | Selected |
|----------|---------|----------|
| Display | Sticky banner + history / History only | Sticky banner + history |
| Re-arm | Arm again, probes kept / Always re-probe / Blocked until acknowledged | Arm again, probes kept |
| Worker crash | Restart worker idle / Stay dead, restart process | Restart worker idle |
| Alarm limit | Never until acknowledged / Give up after N min | Never until acknowledged |

---

## Claude's Discretion

- Input threading model; lease length and caps; potion-probe effect window
- Policy-only replay diff semantics, report format, and support for old recordings (area not discussed)
- Whether arming is refused while an alarm is unacknowledged; stop reason code names; banner layout

## Deferred Ideas

- Pet-food probe: Phase 3
- Up/Down probes required for arming: Phase 4; potion probes required: Phase 3
