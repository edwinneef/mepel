<!-- neef:next-prompt:start -->
## Next prompt

End each final reply about this project with one next-prompt direction, including replies to ordinary prompts without a NEEF invocation. The direction is always a copyable NEEF skill command in the current host's syntax, never a bare prose prompt: a mode uses its own hyphenated skill (`/neef-next ...` in Claude Code, `$neef-next ...` in Codex; likewise `neef-shape`, `neef-plan`, `neef-challenge`, `neef-prototype`, `neef-options`), and a plain task uses `/neef ...` or `$neef ...`. Put the concrete request inside the command, for example `/neef add retry with backoff to the upload client and cover it with a test`, followed by a short note on its intended result. Choose the fitting mode (task, shape, plan, challenge, prototype, options, next) from current work and established goals; prefer a specific request over a bare `neef-next`. When waiting for input, put the needed answer in the command, for example `/neef <your answer>`. When only the user can unblock the work, such as approving a host prompt, changing permissions or running a step themselves, name that exact step, then give a NEEF resume command whose placeholders list what NEEF needs reported back, for example `/neef check 1 result: <pass/fail>, <log path>`; never suggest diagnosing or retrying a permission or policy denial. When no useful work remains, say so and suggest `/neef-shape <next goal>` rather than inventing work. Use one closing direction, without repeating it elsewhere.

Suggestions are advisory. Invoke NEEF only when the user explicitly requests it; setup does not authorize automatic workflows or executing suggested prompts.
<!-- neef:next-prompt:end -->

## Default test loop

For bot changes, follow [AGENTS.md: Default test loop](AGENTS.md#default-test-loop).

## Engine restarts

Restart the debugger engine only with `tools/restart_engine.ps1` (`-EnableGameplayInput` for
input-capable sessions). Never `Start-Process` `run.ps1` again for a restart: the previous
`-NoExit` launcher window stays open after its engine stops, and repeated restarts left four
terminals open on 2026-10-26. Tell the operator before restarting; it ends any active probe.

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
