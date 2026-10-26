# Native launch rejection diagnosis

## Finding

The native pilot was blocked by the command-execution layer before PowerShell
started. This was not a Maplebot HTTP error, Python exception or navigation
feedback failure. The tool returned `CreateProcess ... Rejected` and
`rejected: blocked by policy`. No specific rule or reviewer explanation was
returned. The earlier description "automatic approval review" was more specific
than the evidence supports: the execution-policy rejection is confirmed, but
its precise source and rationale remain unknown.

The rejected batch combined backup creation, a P3 precondition, authenticated
engine shutdown, waiting for the old listener to close, and a hidden replacement
process without the capture-only CLI flag. Because the entire command was
rejected before process creation, none of those batch steps ran.

A subsequent read-only diagnostic batch was also rejected with the same generic
message. That batch requested policy/configuration metadata and source/status
reads. Ordinary repository source reads succeeded afterward. This does not
isolate a particular command, path or gameplay-related rule. It gives no basis
for attributing the original rejection specifically to input enablement.

T3 thread metadata reports `runtimeMode: full-access`; that setting alone does
not establish which execution-policy checks allowed or rejected a command.
No policy settings were changed and the rejected launch was not retried.

## Verified boundaries

- The installed engine still reports instance `de2c232f83930ce5c4569bca` and
  session `7e56d70221c84162a2f40f7450102bb8`, matching the pre-attempt engine.
- Read-only status reports `capture_only: true`, `mode: capture`, no active
  control probe and inactive navigation. Zero of the three checks started.
- `run.ps1` defaults to capture-only. The CLI passes that flag to Application;
  a capture-only Application selects DisabledInput. These application guards
  explain why the existing session cannot issue native probes. They do not
  explain the separate shell-policy rejection.
- An input-capable CLI session also starts with controller input disabled;
  controller enablement is a later guarded action. A process launch by itself
  would not establish that any gameplay key was sent.
- User authorization for the three bounded checks is retained. Combat remains
  off. Current diagnosis authorizes no input or launch retry.

## Evidence and remaining blocker

### Local rule check

Codex CLI 0.164.0 evaluated the complete rejected batch as argument data to
`execpolicy check`, with `C:/Users/edwin/.codex/rules/default.rules` supplied.
Both the exact absolute PowerShell invocation and a check with
`--resolve-host-executables` returned `{"matchedRules": []}` with exit code 0.
The target command was not executed. No policy setting or rule was changed.

This rules out a match in the supplied local file under those checker modes;
it does not identify all policy layers used by the live host or establish that
the live launch is permitted. The checked engine instance remained capture-only
and in capture mode. The result is saved in
`artifacts/native-navigation-preflight/execpolicy-check.json`.

### Host diagnostics inspected

The additional inspection kept the engine and policy unchanged:

- T3 provider logs for thread `45085dcd-560f-47a1-a9d8-b06374a5d9ec`, under
  `D:/projects/t3-fork/portable-t3-history/data/t3/userdata/logs/provider/`,
  contain no approval/policy method in the inspected 06:20–06:29 UTC window.
- Codex's `C:/Users/edwin/.codex/logs_2.sqlite` was opened with SQLite `mode=ro`
  and `query_only=ON`. In 06:20–06:35 UTC, the query found no log body containing
  `blocked by policy`, nor a target containing approval, execpolicy or guardian.
  This does not mean no decision happened; it means that query exposes none.
  The relevant conversation is `01a175aa-afc1-7f40-997d-88c61cd5fa54` and turn
  `01a176df-ba65-79c3-adac-3d7262119349`. Tool timing records exist. Their
  `execution_started=true` field describes the outer code-mode tool handler,
  not successful creation of the nested PowerShell process.
- The day's Windows sandbox log, under `C:/Users/edwin/.codex/.sandbox/`,
  exposed startup/availability entries but no matching policy rejection reason.
  An unrelated PowerShell shell-snapshot warning is not evidence of this denial.
- Inspected T3 source `CodexSessionRuntime.ts` maps full-access mode to
  `approvalPolicy: never`, `sandbox: danger-full-access`, and reviewer `user`.
  It also handles auto-review notification names. These source facts are not a
  captured live approval decision, and do not establish that auto-review caused
  the rejection. `CodexAdapter.ts` prefers command text over an optional reason
  in approval display details, but there is no logged approval payload here
  from which a hidden reason could be recovered.

Available local diagnostics are exhausted for this attempt. The actionable
external request is a host-side decision record correlated to the conversation,
turn and original rejected tool call. Do not request another native recording
or another identical local-rule check to obtain that missing record. No new
launch or input attempt is justified by this inspection.

The original tool rejection is in the thread activity. The saved observation is
`artifacts/native-navigation-preflight/launch-blocked.json`; it records the
capture-only engine after rejection, not the policy engine's reason.

The host must expose the specific execution-policy decision/rule to establish
the root cause. No application code fix is justified by the generic denial.
Do not weaken capture, focus, probe, freshness or Stop gates, change host policy,
or repackage the rejected launch through another executor as a workaround.
The native pilot remains pending until this external blocker is resolved.

## One capture-only launch diagnostic

A separately authorized, single diagnostic attempt used `debug --capture-only`,
a free loopback port, an isolated config/data directory with no saved calibration,
and diagnostic-only shutdown/owned-child cleanup. It would not stop or attach
to the existing engine/game. The host rejected the whole batch before PowerShell
started, again with `CreateProcess ... rejected: blocked by policy`.
No child process was created and no retry followed. Original instance/session
IDs were unchanged, capture-only/capture mode remained active, and all seven
protected config/profile files checked retained their hashes.

This establishes that this capture-only launch batch also receives a denial;
it does not isolate a triggering token or prove why the original native launch
was denied. The returned error itself contains a command-truncation marker.
The complete returned tool result and full submitted command are saved in
`artifacts/capture-only-launch-20261026-082659/tool-result.json` and
`submitted-command.txt`, alongside setup and preservation evidence.
