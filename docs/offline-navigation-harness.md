# Offline navigation harness

Run from the project root; neither the game nor engine needs to be running:

```powershell
.venv/Scripts/python.exe -m tools.navigation_harness --seeds 100 --output artifacts/navigation-harness/run-001.json
```

Choose a new output path each time. Existing evidence is never overwritten, and
output inside protected `data/` is refused. The default suite runs seeded round
trips plus lost input, focus loss, Stop, stale feedback, missing recognition, a changed map
and a surface change during the next route's countdown. It exits nonzero if an
experiment differs from its expected arrival or safe stop.

The actual `NavigationRuntime`, `Navigator`, `Arbiter` and `TimingPlanner` run
against a virtual clock, a modeled controller and simple platform physics.
Commands change acceleration, jump/drop motion and collision; route traces do
not supply positions or destination labels. Model key holds expire between
observations and sequence tickets complete after their timing plans. Delayed
feedback reads older modeled observations. Every exit clears modeled input.

`tools/navigation_harness_case.json` preserves the signature and source paths of
the saved 2026-10-30 handoff failure: one arrival followed by an origin change.
The model injects displacement onto an excluded island during the next countdown
and requires the same refusal message. This reproduces the failure class on
synthetic geometry; it does not reconstruct the recording's original dynamics.

For a platform-only route on a saved imported map, add `--profile PATH --origin ID
--feet X Y --targets ID [ID ...]`. Maps are read only. Rope/climb routes are
explicitly unsupported. `--experiment PATH` accepts a JSON object with fields
from `Experiment` in the tool: for example `{"targets":["ledge"],"input_delay":0.4}`.
Other useful fields are `fps`, `seed`, `feedback_delay`, `speed`, `acceleration`,
`braking`, `jump_speed`, `gravity`, `drop_input`, `expected` and `expected_reason`.
An independent deadline check fails an experiment if a pending input ticket
hides an exceeded eight-second edge or 60-second route budget. For example,
`{"targets":["ledge"],"input_delay":10,"expected":"safe_stop"}` now stops through
the runtime's normal navigation failure path, cancels virtual pending keys and
passes without an oracle violation. An arrival expectation still exits nonzero.
This injected stall exceeds normal
timing settings; it is not an observation of a native controller stall.

The default dynamics are illustrative, not a calibrated MapleStory model. Fit
assumptions against existing clips before treating results as a route prediction.
The controller, focus/Stop inputs and observations are modeled; this does not
exercise OS input delivery, capture, pixel recognition, the real watchdog/F8 or
overlay lease, or prove native contact. It cannot write native movement proofs.
Keep the saved-frame recognition checks and existing native-controller tests.
Live gameplay remains deferred until a separately authorized supervised batch.

`tools/dev_cycle.ps1` includes the harness regression tests by default. The
original `tools/navigation_replay.py` remains a saved-anchor compatibility smoke.
