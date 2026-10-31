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

## Calibrate from saved clips

```powershell
.venv/Scripts/python.exe -m tools.calibrate_navigation_physics --output artifacts/navigation-harness/physics.json
.venv/Scripts/python.exe -m tools.navigation_harness --physics artifacts/navigation-harness/physics.json --output artifacts/navigation-harness/physics-run.json
```

Calibration reads saved decision logs only. It records source hashes, deduplicates
overlapping clips by area/capture clock, rejects conflicting copies and gaps, and
uses fresh recognized, focused, calibrated observations. Ballistic fits train on
alternating airborne frames and report error on held-out frames. Promotion needs
two distinct supported flights in one coordinate area and consistent parameters.
This holdout checks interpolation within a flight, not independent gameplay.

The available evidence supports only an approximate jump-height constraint:
two jumps rose about 78 pixels, with a 16-pixel measurement margin for quantization
(not a statistical confidence interval). No ballistic fit passed validation.
Height alone cannot determine gravity and jump speed separately. Horizontal
speed, acceleration and braking remain unidentified: saved input events lack
absolute key start times. Illustrative defaults stay unchanged.

`--physics` applies supported fits, or checks the model's implied jump height
against the recorded constraint before a run. Reports retain fitted fields,
constraints and unidentified fields; they never claim full calibration.
Calibration refuses output within saved data/recordings and never overwrites files.

New diagnostic records include absolute timestamps on successful backend key
calls in `input_timing.events`: `clock` and `finished_clock` bracket the call in
`time.perf_counter()` seconds, matching the frame's `capture_clock` time domain.
`issued_at` is Unix wall time sampled before dispatch. Existing `at_seconds`
remains relative to the current input sequence. These are dispatch observations,
not proof of game receipt or movement. Failed backend calls have no successful
event entry. Repeated frame snapshots may contain the same event; deduplicate by
absolute event clock, never by relative offset alone.

Historical recordings remain unchanged and may omit the new fields. The saved
corpus still lacks these timestamps; full physics calibration remains incomplete.
Timestamps are recorded on future sessions after loading this code. No restart
or gameplay is required to run the offline tests.

Calibration now consumes those fields in `input_alignment`. It deduplicates
repeated events by player/calibration basis, key and absolute clock; conflicting
copies and malformed clocks are rejected. Legacy event snapshots are counted
separately and never assigned invented absolute times. Wall time and relative
offsets do not determine alignment.

Each valid event is matched to the nearest observations before dispatch starts
and after it finishes, within 300 ms on each side and on the same coordinate and
player basis. Missing, unrecognized or incompatible observations produce an
explicit gap. The reported displacement only describes neighboring observations;
it does not establish that a key caused movement. No horizontal parameter is
promoted from timestamp alignment alone. The historical corpus still has no
absolute event clocks, so its calibration remains height-only.
