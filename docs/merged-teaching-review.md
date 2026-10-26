# Reversible merged teaching review

Prepared 2026-10-26 from the two saved Over the Wall sessions. The app now loads
the merged checkpoint in **review**, with recording and gameplay input stopped.
The active map remains revision 3; no `teach_save` or map activation was performed.

- 1,613 samples and 2,129 historical checks retained.
- 16 platforms, one rope, 33 directed links.
- Left ledge P1, Ground floor P3 and Left rope R1 retain their names/identities.
- Both missing-return warnings clear. Ground floor 2 (P16) remains unreachable
  and must stay flagged during review.
- Historical unreadable checks remain in the report; the merge does not rewrite
  them as successful readings after the minimap fix.

The original checkpoint is backed up byte-for-byte at:

`artifacts/teaching-merge-install-20261026-044816/backup/before.json`

The same directory contains `candidate.json`, source hashes and `receipt.json`.
Six protected map/configuration hashes remain unchanged. The original 508-sample
draft is preserved in the backup. All pre-existing untracked files are untouched.

## Restore the previous review

Stop the debugger first; the tool refuses to mutate a checkpoint while its port
is listening. Then run:

```powershell
.venv\Scripts\python.exe tools\merge_teaching_draft.py `
  --restore artifacts\teaching-merge-install-20261026-044816\backup
.\run.ps1
```

Restore uses a new checkpoint revision, keeps a copy of the merged checkpoint,
and preserves the active map. It tolerates normal recovery timestamp rebasing
but refuses new teaching evidence, changed backups or a changed active map.
Do not copy the backup over newer teaching work manually.

## Reproduce preparation

```powershell
# Read-only dry run (the installed merge will be refused if applying it again).
.venv\Scripts\python.exe tools\merge_teaching_draft.py
# With the debugger stopped and an unmerged matching review:
.venv\Scripts\python.exe tools\merge_teaching_draft.py --apply `
  --backup artifacts\A_NEW_BACKUP_DIRECTORY
```

Preparation verifies source hashes, calibration, original sample/log retention,
geometry reproduction, and checkpoint revision before replacing only the draft.
Backup and receipt are written before the atomic checkpoint save. A failed save
leaves the original checkpoint and its backup intact.

Validation: 29 targeted tests and Ruff pass. A temporary copy of the real data
loaded the merged review and restored the original after a simulated restart.
The installed browser shows the merged places and keeps the P16 warning; the
capture-only server reports review, 1,613 samples and active map revision 3.
