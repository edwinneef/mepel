# Windows command rejected before execution; policy reason unavailable

**Request:** Identify the policy layer and decision that rejected this command,
and expose a reason/rule identifier in the tool result or host diagnostics.

## Environment and correlation

- Windows, PowerShell 7, T3 Code using the Codex app-server; thread reports
  `full-access`. Diagnostic CLI: `codex-cli 0.164.0`; the exact binary/version
  serving the rejected call was not captured.
- T3 thread: `45085dcd-560f-47a1-a9d8-b06374a5d9ec`
- Codex conversation: `01a175aa-afc1-7f40-997d-88c61cd5fa54`
- Codex turn: `01a176df-ba65-79c3-adac-3d7262119349`
- Incident window: **2026-10-26, 06:20–06:29 UTC**.

## Observed incident

The user authorized three bounded navigation checks in a local game automation
project, with combat off. The proposed PowerShell batch would back up local
configuration, verify a safe position, shut down the capture-only debugger,
wait for its listener to close, and start a hidden input-capable replacement.
The replacement starts with controller input disabled; launching it would not
itself send gameplay keys.

`exec_command` returned a `CreateProcess` rejection ending in:

```text
rejected: blocked by policy
```

PowerShell did not start. No batch steps ran and no native test keys were sent.
The original engine instance remained running in capture-only mode. A later
read-only diagnostic batch also received the generic denial; other source/status
reads succeeded. No minimal reproducer or individual triggering token is known.

## Diagnostics already completed

- Full rejected command checked as data with `codex execpolicy check` against
  the default local rule file, both normally and with host-executable resolution:
  **exit 0, `{"matchedRules": []}`**. This covers that file, not every host layer.
- T3 provider logs expose no approval/policy event in the incident window.
- Codex logs SQLite inspected read-only for 06:20–06:35 UTC: no matching denial
  body or approval/execpolicy/guardian target. Windows sandbox logs add no reason.
- No policy was changed, rejected launch retried, or input enabled.

## Maintainer questions

1. Which policy layer evaluated the rejected nested `exec_command` call?
2. What rule, classification or unavailable-review condition produced the denial?
3. Can its decision ID and explanation be retained in the error/logs? Outer
   code-mode tool timing says `execution_started=true`, which does not indicate
   that the nested PowerShell process started.

Local supporting records: [detailed diagnosis](native-launch-diagnosis.md),
`artifacts/native-navigation-preflight/{launch-blocked,execpolicy-check,host-diagnostics}.json`.
This draft omits credentials, debugger tokens, screenshots and full provider logs.
It has not been submitted externally. Please investigate the existing incident;
do not require another live movement attempt merely to obtain the missing reason.
