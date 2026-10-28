# Passive potion evidence

Normal live potions, combat sustain and navigation sustain now retain evidence when
automatic recording is enabled (`recording.auto`, already enabled by default).
There is no new test, button, recording step or keyboard action. Thresholds,
cooldowns, arbitration, input safeguards and saved confirmations are unchanged.

Each actual queued potion ticket gets a small directory under `data/recordings/`:
`session-<timestamp>-potion-<hp|mp>-t<ticket>` containing:

- `potion-evidence.jsonl`: queued, actual input outcome, and final observation records.
- `decisions.jsonl`: the observations matching the retained images.
- At most two PNGs: a confident pre-input HUD frame and the matching post-input frame.

The collector uses already encoded PNGs and the recorder's asynchronous writer.
It never encodes another image or performs disk I/O on the gameplay decision thread.
The existing recording queue limit and recording age/size limits still apply.
Evidence survives the normal combat recorder stopping; it can observe the short
recovery window while input stays Off. Application shutdown marks unfinished
observations `capture_ended`.

A usable baseline must be focused, unobscured, confidently read, from the same
capture source/view, and captured within 500 ms before both submission and actual
input start. A post-input sample must be captured strictly after key completion,
within the configured potion-effect window (default 2 seconds), with the same
source and confidence checks. Frame timestamps use the capture clock, not the time
the encoder finishes. Repeated old outcomes are ignored.

`observed_bar_gain` means the bar increased by the configured minimum (default
1 percentage point). It does not prove potion causation: regeneration and damage
can affect the bar. `no_observed_gain` also does not prove a failed potion.
Missing/stale baselines, missing readings, source changes, interrupted input,
missing outcomes and overlapping potions have distinct incomplete results.
Another potion of the same resource closes the older window as `superseded`.

The status API exposes the latest 32 records as `potion_evidence`. Numeric evidence
does not guarantee a PNG reached disk: the existing writer can drop images under
load or on an I/O error. Check both referenced PNGs and their matching decision
rows before treating a recording as a complete visual pair. Passive evidence
never confirms a probe or marks native potion recovery as verified automatically.

Focused offline validation:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_potion_evidence.py tests/test_recorder.py tests/test_runtime.py tests/test_navigation_runtime.py -q
```

These checks use synthetic HUDs and a fake input backend. They establish capture
and matching behavior; they do not establish recovery in MapleStory. Existing
native evidence limitations remain documented in [the prior audit](potion-evidence-audit.md).
