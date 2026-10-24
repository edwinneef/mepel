---
phase: 01-deterministic-input-and-safe-stop
plan: 01-04
status: blocking-human
checkpoint: local-install-and-operator-acceptance
---

# Plan 01-04 Checkpoint

| Task | Status |
| --- | --- |
| Guarded debugger probes | Complete and tested |
| HP/MP probe confirmation | Complete and tested |
| Offline local editable install | Complete; protected configuration/data unchanged |
| Target-client probe acceptance | Pending operator observation; do not Arm |

## Install prerequisite resolved

The existing `.venv` lacked `setuptools.build_meta`. Restored cached `setuptools==84.0.0` with `uv pip install --python .venv/Scripts/python.exe --offline --no-deps setuptools==84.0.0` after its offline dry run passed. Both the editable-install dry run and `python -m pip install --no-index --no-deps --no-build-isolation -e .` then passed.

Previous installed metadata, editable path, launcher, source commit and protected-file hashes are backed up under `artifacts/install-backup-20261024-223024/`. All 677 existing configuration/data files retained their SHA256 hashes and file count. No package index was contacted and no input session was launched or armed.

Post-install checks: full pytest suite **177 passed**, Ruff **passed**, `pip check` **passed**. Imports resolve to this checkout; packaged debugger HTML and RIFF alarm WAV exist. These checks establish offline code/package evidence, not target-client input reception or audible PC output.

## Resume conditions

The install prerequisite is satisfied. One bounded operator acceptance round from `01-04-PLAN.md` remains. No recording is required. Stop after the first failure; do not click Arm.

1. Start `./run.ps1 -EnableGameplayInput` yourself. Stay unarmed. Attach the MapleStory window, calibrate and verify capture.
2. Probe Left, Right, Attack, Jump and Skill separately. Focus the game during each three-second countdown; expect one short action, then Confirm that probe. Stop on any wrong or repeated key.
3. Stand away from portals and ropes. Probe Up and Down separately; confirm only the expected safe response. Stop on portal/rope interaction or numpad-like behavior.
4. With calibrated HP/MP bars at or above 95%, request each potion probe once. Expect refusal with an actionable message and no key press.
5. Lower HP and MP below 95% in a safe spot, then request each potion probe once. Combat/resource spending is needed only for this setup. Expect one press and the matching bar rising within the configured two-second window; only that matching probe passes.
6. Confirm Pet Food shows a binding but no probe, and the five required manual probes permit Arm without the four optional probes. Do not click Arm.

Completion: all nine offered probes behave once as specified, with no automatic arming or gameplay loop. Report the first failing action and visible result, or the completed observations. Phase 1 remains incomplete pending this evidence and remaining phase gates.

