# Windows app-server: command rejected by policy without an exposed decision reason

Template: [Other Bug — integrations/components](https://github.com/openai/codex/issues/new?template=4-bug-report.yml).
The sections below match the current template. Local draft only; not submitted.

## What issue are you seeing?

When using Codex through T3 Code on Windows, a nested `exec_command` call was
rejected before PowerShell started. The error exposes no decision ID, matched
rule or explanation beyond `blocked by policy`.

Relevant error, with the command text omitted:

```text
exec_command failed: CreateProcess { message: "Rejected(... rejected: blocked by policy)" }
```

The host itself truncated the command in the returned error. We retained all
returned error text and the full submitted command locally.

The original batch would back up a local game-automation application's data,
verify a safe position, stop its capture-only debugger and launch an input-capable
replacement. A separately authorized single control attempt used **capture-only**
mode, isolated data, a separate loopback port and no game attachment. It received
the same pre-PowerShell denial. No diagnostic process or gameplay input resulted.
The existing capture-only process/session and seven protected file hashes were
unchanged. Some ordinary source/status reads succeeded; a read-only diagnostic
batch also received this generic denial.

## What steps can reproduce the bug?

These are the observed circumstances, **not a verified standalone reproducer**:

1. Use T3 Code with the Codex app-server on Windows; the thread reports full-access.
2. Request a multi-line PowerShell batch through code mode's nested `exec_command`.
   The denied capture-only control batch used `Start-Process -WindowStyle Hidden`
   to launch Python with `-m maplebot --config <isolated-config> debug --capture-only`,
   and included status polling and cleanup of only that diagnostic child.
3. Observe the `CreateProcess` policy rejection before the shell starts.

We have not isolated the triggering token, reproduced this directly in the Codex
TUI, or established which policy layer denied it. No further launch attempt or
policy change was made after the single capture-only control attempt.

## What is the expected behavior?

A denied command should expose an actionable, appropriately redacted decision
reason or correlation ID in the error or diagnostics. Please identify which
policy layer denied these calls. This report does not request removal of safety
checks or assume the commands should have been allowed.

## Additional information

- Environment: Windows, PowerShell 7, T3 Code/Codex app-server, model `gpt-6.1-sol`.
- Diagnostic CLI: `codex-cli 0.164.0`. Exact serving app-server binary/version
  was not captured; the diagnostic CLI version is not proof of that version.
- Native incident window: 2026-10-26 **06:20–06:29 UTC**. Capture-only control
  attempt: approximately **07:27 UTC** on the same day.
- Codex conversation: `01a175aa-afc1-7f40-997d-88c61cd5fa54`
- Codex turn: `01a176df-ba65-79c3-adac-3d7262119349`
- T3 thread: `45085dcd-560f-47a1-a9d8-b06374a5d9ec`
- `codex execpolicy check` evaluated the full original invocation against the
  default local rule file, with and without host-executable resolution. Both
  returned exit 0 and `{"matchedRules": []}`. This does not cover every host layer.
- T3 provider logs expose no approval/policy notification in the original incident
  window. A read-only query of Codex logs for 06:20–06:35 UTC found no matching
  denial body or approval/execpolicy/guardian target. Windows sandbox logs added
  no reason. No claim is made that absence from those logs means no review occurred.
- Outer code-mode tool timings report `execution_started=true`; this must not be
  interpreted as successful creation of the nested PowerShell process.

No credentials, debugger tokens, screenshots, user paths or full session logs
are included in this public-facing draft. This has not been submitted via
`/feedback`, so there is no feedback-upload ID.
