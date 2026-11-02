<!-- neef:next-prompt:start -->
## Next prompt

End each final reply about this project with one next-prompt direction, including replies to ordinary prompts without a NEEF invocation. The direction is always a copyable NEEF skill command in the current host's syntax, never a bare prose prompt: a mode uses its own hyphenated skill (`/neef-next ...` in Claude Code, `$neef-next ...` in Codex; likewise `neef-shape`, `neef-plan`, `neef-challenge`, `neef-prototype`, `neef-options`), and a plain task uses `/neef ...` or `$neef ...`. Put the concrete request inside the command, for example `/neef add retry with backoff to the upload client and cover it with a test`, followed by a short note on its intended result. Choose the fitting mode (task, shape, plan, challenge, prototype, options, next) from current work and established goals; prefer a specific request over a bare `neef-next`. When waiting for input, put the needed answer in the command, for example `/neef <your answer>`. When only the user can unblock the work, such as approving a host prompt, changing permissions or running a step themselves, name that exact step, then give a NEEF resume command whose placeholders list what NEEF needs reported back, for example `/neef check 1 result: <pass/fail>, <log path>`; never suggest diagnosing or retrying a permission or policy denial. When no useful work remains, say so and suggest `/neef-shape <next goal>` rather than inventing work. Use one closing direction, without repeating it elsewhere.

Suggestions are advisory. Invoke NEEF only when the user explicitly requests it; setup does not authorize automatic workflows or executing suggested prompts.
<!-- neef:next-prompt:end -->

## Research reference

For source-backed bot/CV comparisons, read [the ecosystem research index](docs/research/maplestory-bot-ecosystem/README.md), then only the relevant topic. It includes pinned external source, current architecture, limitations and a ranked backlog; recommendations do not authorize implementation or gameplay.

## Default test loop

Use the offline failure-to-retest workflow for bot changes. Runner options are in
[README.md](README.md#tests-and-reproducible-checks).

- Inspect the saved failure result and clip before editing. Run `tools/dev_cycle.ps1`
  with `-Scope navigation`, `-Scope combat`, `-Scope perception` or `-Scope ui` to
  match the change. Supply `-FailureResult <result.json>`
  when diagnosing a saved failure; policy replay runs automatically. Replay compares
  decisions and does not prove live focus, capture timing, input delivery or hits.
- Select affected tests and lint paths. Reuse passing evidence while its source and
  conditions still match; broaden checks for cross-cutting changes, failures or a
  concrete unresolved risk. Proceed to delivery once affected checks pass.
- For navigation-bundle edits, prefer `-Scope navigation -ReloadNavigation` after
  checks. The existing engine gate requires Bot Off and released, idle input. Changes
  outside that reload bundle require the restart workflow below when authorized.
- Reuse unchanged accepted controls, calibration and map evidence. Every live batch
  still requires operator presence and explicit authorization under the rules below.
- Separate command runtime from investigation, setup, installation and reporting
  overhead. A faster offline check does not establish a faster complete live cycle.

## Engine restarts

Restart the debugger engine only with `tools/restart_engine.ps1` (`-EnableGameplayInput` for
input-capable sessions). Never `Start-Process` `run.ps1` again for a restart: the previous
`-NoExit` launcher window stays open after its engine stops, and repeated restarts left four
terminals open on 2026-10-26. Tell the operator before restarting; it ends any active probe.

## Local start for supervised tests

Default to an operator-clicked local start control for future supervised gameplay
batches. Finish preparation, affected offline checks and safe installation before
handing over the control; chat response time must not determine the start time.
The click starts only the displayed bounded batch, after fresh engine readiness,
map, player and required enemy checks. Keep operator presence, explicit batch
authorization, all safety gates, F8, first-failure stop, key release, saved clip
and alarm requirements. Never automatically retry a failed run. Alarms need no separate
acknowledgement (operator rule, 2026-11-02): starting the next batch or restarting the
engine acknowledges the previous one.
Restore focus only through the engine's guarded focus_game command.

The current Maple Floor Batch control targets only fh66 in Snail Hunting Ground III;
it is not a general map launcher. The operator reported on 2026-11-01 that it did
not work. Treat that as unresolved: inspect its failure and verify the actual
click-to-start path before claiming it works or requesting another gameplay test.
Offline tests and window startup alone do not establish successful local launch.

## Unattended testing

Operator correction, 2026-10-29: live gameplay tests require the operator to be present
and explicitly authorize that batch. Leave the game open on failure; release all keys,
save the clip and sound the alarm, then hand control back immediately so the operator
can move to safety. Do not leave the character exposed while investigating. Offline
work and input-free setup remain authorized. The supervised testing scope includes
restarting the engine and overlay (`tools/restart_engine.ps1
-EnableGameplayInput`, then `tools/start_overlay.ps1 -WaitForEngine`), tracking and importing
maps, control probes, navigation routes (`tools/navigation_check.py --run`), rotation, and
combat checks (`tools/combat_check.py --run`). Read each failure's clip, fix the cause, and
run the checks again.

Limits that still apply:

- Only on the bot-friendly server, and only through the engine's own commands and gates.
  Never weaken, bypass or disable a safety gate, the watchdog, F8 or the overlay lease to
  make a test pass; a test that needs a gate changed goes to the operator.
- Stop a batch at its first failure; never repeat an unchanged failing run.
  Operator exception, 2026-11-02: in a learn_moves farming batch, an unproven move that
  misses but lands the player still on a known platform, with fresh agreeing position
  and all gates intact, is a learning outcome, not a failure: the engine records the
  miss and keeps farming, at most 3 times per batch. Any other miss still stops it.
  Extended the same day: a proven move inside the batch's attempted learning path may miss
  the same way; a proven move that misses twice loses its proof.
- Agents may restore focus to the attached MapleStory window whenever focus is lost,
  including after startup or restart, without asking the operator. Use only the engine's
  guarded `focus_game` command; its verified title-bar click fallback is allowed.
  Stop active gameplay first, confirm focus was restored, and recheck map, player and
  all safety gates before starting input. Focus loss during gameplay still stops input;
  restoring focus does not authorize repeating an unchanged failed run. If the focus
  request fails or is denied, report it and stop; do not loop or bypass the refusal.
  If the map is wrong or the player is not recognized, report it and stop.
- Do not delete recordings, calibration or saved maps; backups stay as they are.
- Report every run in the final reply: what ran, the result, and evidence or clip paths.
