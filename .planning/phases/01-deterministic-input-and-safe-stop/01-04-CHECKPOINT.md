---
phase: 01-deterministic-input-and-safe-stop
plan: 01-04
status: blocking-human
checkpoint: remaining-native-acceptance
---

# Plan 01-04 Checkpoint

## Reconciled on 2026-10-25

Installation is complete. Phase 1 remains at 3/4 completed plans; do not mark 01-04 or the phase complete until the remaining acceptance and phase gates are resolved. The old plan-approval/install-blocked routing is stale: this is an operator acceptance checkpoint, not a request to approve or rerun the plan.

| Evidence | Current result |
| --- | --- |
| Offline install and dependencies | Installed repeatedly from this checkout with no index/dependency fetch; saved configuration and existing data preserved; rollback sources/metadata under artifacts/ |
| Current validation | 235 pytest tests pass; Ruff passes for src, tests and tools; pip check reports no broken requirements (run during this reconciliation) |
| Native control observations | Operator confirmed Left, Right, Attack, Jump, Skill, HP potion and MP potion worked; no repeat of these seven checks is requested |
| Potion full-bar guard | Operator observed no countdown at full HP/MP; runtime showed both at 100%; guard explanation accepted, followed by successful potion report |
| Probe persistence | Seven operator-confirmed controls migrated with an audit under artifacts/probe-confirmation-migration-*.json; restored on the selected MapleStory window after restart |
| Latest alarm | FOCUS_LOSS: actual game was not focused at the countdown deadline; recorded clip exists, acknowledgement=true and active=false; this proves runtime acknowledgement, not audible silence at the speaker |
| Live Autopotter | User-authorized standalone live mode installed; two-frame HP priority/shared cooldown and safe stops tested. Latest native attempt stopped on focus loss before acceptance; live sustain effect remains unverified |
| Phase completion | Pending; no 01-04-SUMMARY.md or phase verification report has been created |

## Remaining operator evidence

Do not restart the full checklist or request another recording. First determine whether these were already included in the operator's earlier successful checks:

1. Up and Down: each reached the game once as the configured arrow, away from portals/ropes, without an unexpected interaction. These two optional probes were not specifically identified in the conversation and were not migrated as confirmed.
2. Alarm acknowledgement after the fix: the debugger Acknowledge alarm button and F8 each silence a repeating alarm. Runtime records show an acknowledged incident, but the exact acknowledgement method and audible result were not separately reported after the fix.

If an item has not been observed, resume only that item with its existing bounded procedure. Stop on the first failure. No Arm/combat run, native worker-crash injection, or repeated gameplay recording is requested here. Own-window keyboard smoke and subsequent phase verification/review gates remain the execute workflow's responsibility; offline tests are not live-game evidence.

After the remaining evidence is resolved, resume `$gsd-execute-phase 1` at 01-04's checkpoint and remaining phase gates. Do not rerun completed plans 01-01 through 01-03. Phase 2 follows only after Phase 1 is actually verified.

## Operator-authorized changes superseding the original plan

- Probe confirmations now persist for matching configured/game title, crop, client dimensions, DPI and individual key binding. Potion confirmations additionally match the HUD reference and rectangle. Binding changes invalidate the matching action; calibration mismatches reject affected confirmations. Re-probing revokes that action until a new success. Capture verification still resets; input never auto-enables after restart. This supersedes the original memory-only/reset-all D-02/D-12/D-13 details and T-01-13 implementation wording, without removing runtime input guards.
- Standalone live Autopotter was explicitly requested after the controls worked. Preview remains input-free; combat stays stopped in live-potion mode. This does not complete Phase 3: combat preemption, independent cooldowns, potion counts/ineffectiveness/critical-HP stops, skill fallback and pet feeding remain deferred.
- Installed follow-ups: unobscured game preview, reliable alarm banner/acknowledgement, gray HUD tracks/anchors, safe dashboard restart, precise probe blockers, input disabled after each probe, Alt binding, collapsible panels, persisted probes and Copy alarm with stable text selection.

## Historical setup notes (superseded where the reconciliation above differs)

## Install prerequisite resolved

The existing `.venv` lacked `setuptools.build_meta`. Restored cached `setuptools==84.0.0` with `uv pip install --python .venv/Scripts/python.exe --offline --no-deps setuptools==84.0.0` after its offline dry run passed. Both the editable-install dry run and `python -m pip install --no-index --no-deps --no-build-isolation -e .` then passed.

Previous installed metadata, editable path, launcher, source commit and protected-file hashes are backed up under `artifacts/install-backup-20261024-223024/`. All 677 existing configuration/data files retained their SHA256 hashes and file count. No package index was contacted and no input session was launched or armed.

Post-install checks: full pytest suite **177 passed**, Ruff **passed**, `pip check` **passed**. Imports resolve to this checkout; packaged debugger HTML and RIFF alarm WAV exist. These checks establish offline code/package evidence, not target-client input reception or audible PC output.

## Resume conditions

### Walkthrough interrupted: 2026-10-25

HUD calibration follow-up: the operator saw both resources waiting for confident frames. Saved rectangles passed border checks; the reader rejected the actual client's gray empty bar tracks because it recognized only dark empty pixels. The input-free reader now accepts neutral gray empty tracks below the pale-border brightness, while preserving the 0.9 confidence, border, color and fill-order guards. Fourteen regression cases cover partial gray tracks and rejection of white/colored interference. Full suite: **196 passed**, Ruff passed. The captured actual frame now reads HP 70.0% and MP 24.5%, each at confidence 1.0, using the unchanged saved rectangles. Offline install passed with 688 existing config/data files unchanged; backup: `artifacts/hud-fix-backup-20261025-010306/`. Automatic approval rejected the running-debugger stop/restart command with `blocked by policy`; no restart occurred. The operator must restart once to load this fix; live post-restart readings remain unverified.

Setup did not pass: the operator reported missing top-of-game pixels, no visible alarm acknowledgment, and F8 not silencing the alarm. Testing stopped before the probe round; no native probe is marked passed.

Confirmed and fixed: the annotated preview painted a 46-pixel status strip over the game; encoder frame publication discarded the stop banner fields; the F8 callback stopped input without acknowledging audio. The debugger now preserves game pixels, publishes stop details from the persistent incident record, and keeps Acknowledge alarm in the header. F8 acknowledges active audio independently of the capture worker, and the direct acknowledge action also handles an alarm without a banner.

Fix verification: five regression tests first reproduced the failures; the full suite then passed **182 tests**, Ruff passed, and browser DOM checks against a silent capture-only screenshot fixture confirmed the visible header button and its acknowledgment API action. Browser screenshot automation timed out; no rendered screenshot or speaker/game effect is claimed. The fixed checkout is installed offline; its previous source/metadata are backed up in `artifacts/debugger-fix-backup-20261025-004840/`, and all 678 existing config/data files are unchanged. Resume with capture-only `./run.ps1`, reset the crop and confirm the full game view before returning to input-capable probes.

The install prerequisite is satisfied. One bounded operator acceptance round from `01-04-PLAN.md` remains. No recording is required. Stop after the first failure; do not click Arm.

1. Start `./run.ps1 -EnableGameplayInput` yourself. Stay unarmed. Attach the MapleStory window, calibrate and verify capture.
2. Probe Left, Right, Attack, Jump and Skill separately. Focus the game during each three-second countdown; expect one short action, then Confirm that probe. Stop on any wrong or repeated key.
3. Stand away from portals and ropes. Probe Up and Down separately; confirm only the expected safe response. Stop on portal/rope interaction or numpad-like behavior.
4. With calibrated HP/MP bars at or above 95%, request each potion probe once. Expect refusal with an actionable message and no key press.
5. Lower HP and MP below 95% in a safe spot, then request each potion probe once. Combat/resource spending is needed only for this setup. Expect one press and the matching bar rising within the configured two-second window; only that matching probe passes.
6. Confirm Pet Food shows a binding but no probe, and the five required manual probes permit Arm without the four optional probes. Do not click Arm.

Completion: all nine offered probes behave once as specified, with no automatic arming or gameplay loop. Report the first failing action and visible result, or the completed observations. Phase 1 remains incomplete pending this evidence and remaining phase gates.

