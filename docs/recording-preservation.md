# Recording preservation

`SessionRecorder` no longer deletes existing recording folders when starting a
session, saving a clip, starting full recording, or saving potion evidence.
The old age/size pruning jobs and deletion implementation are removed. Existing
`max_age_days` and `max_total_mb` settings remain readable for configuration
compatibility, but no longer delete files. In-memory buffering and queue limits
still bound capture work; storage cleanup requires an explicit user decision.

The regression test covers all four entry points with expired and oversized
sessions plus an unrelated personal folder. It checks every existing file's
contents after the writer shuts down, and verifies new evidence is still saved.
All four cases failed against the previous deletion behavior and passed after
the fix. Recording, potion evidence and shutdown checks: **28 passed**.

Activation on 2026-11-01 used the editable installation and
`tools/restart_engine.ps1` without `-EnableGameplayInput`. The old engine was idle
and capture-only. Before restarting, all **2,692 existing files / 2,041,363,160
bytes** were copied to a new backup folder with matching SHA-256 hashes. All
original files still existed with identical hashes after activation. The new
engine answered in capture-only/capture mode with no active recording. This was
installation, not another gameplay or capture test.

Evidence: `artifacts/recording-preservation-20261101/before.json`,
`activation.json`, and `backup/`. The verified backup took 9.79 seconds;
the affected tests took 4.20 seconds, excluding investigation and activation.

One older recording already reported missing before this fix,
`session-1793386720435146300-clip/decisions.jsonl`, remains absent. The deletion's
time and cause are not established; this change does not claim to recover it.
