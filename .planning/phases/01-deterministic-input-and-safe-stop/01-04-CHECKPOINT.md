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
| HP/MP probe confirmation | Complete and tested; local editable install blocked |

## Blocking install error

The existing `.venv` has no `setuptools`, so `python -m pip install --no-index --no-deps --no-build-isolation -e .` cannot load `setuptools.build_meta`. No install claim is made and no user configuration or data was changed.

## Resume conditions

1. Restore `setuptools.build_meta` in the existing project venv without fetching dependencies, then re-run the no-index editable install and package/import checks.
2. Only after the safe install succeeds, run the one bounded operator acceptance round from `01-04-PLAN.md`; stop after the first failure and do not click Arm.

