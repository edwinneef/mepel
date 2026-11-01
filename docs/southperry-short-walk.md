# Installed short Southperry walk

`nav_walk` adds one nearby point target on the current flat platform. It uses
the existing saved position calibration, not the new scenery PNG or automatic
alignment. Southperry's saved revision-3 profile is unchanged.

Versioned engine command: `nav_walk`, payload `{"dx": -80, "opt_in": true}`.
The destination is 80 saved-map pixels left of the freshly observed start.
Distances must be 48-96 pixels. Both endpoints and the stopping corridor must
remain within the same flat, reachable platform, outside blocked zones and the
hunting boundary, with the existing 96-pixel braking allowance beyond the
target/launch bands. The real saved Southperry `fh2` proposal passes this check.

The command keeps the normal three-second countdown. It then confirms a settled
origin and proposes only short left/right pulses of at most 80 ms. It releases
movement inside a 32-pixel arrival band and observes that band for one second.
There is a three-second window from the first pulse, including arrival settling,
and a five-second total budget after the countdown. No progress for one second,
wrong-way motion, overshoot, changed start, changed map/platform, uncertain
identity, stale position or lost focus stops the attempt. It never corrects or
retries a failed arrival, recovers recognition and resumes, or proves an
inter-platform route. Existing potion priority and controller protection remain.

The existing capture-only, saved-position, unverified-automatic-position,
control confirmation, walk-pose coverage, matching map revision, input binding,
fresh versioned command, epoch/session, overlay/control lease, physical window,
watchdog, F8 and Stop gates are retained. Movement feedback must stay fresh
within the existing 0.5-second limit. No gate was relaxed or removed.

## Verification and installation

128 distinct focused short-walk, navigation, command-contract, control-lease and
shutdown checks passed: the initial 127 in 3.84 seconds, then all 22 affected
short-walk checks in 0.48 seconds after tightening stationary arrival. Ruff passed. They use simulated feedback and test
keyboard backends, not the game. Coverage includes point-target countdown
preservation, Stop/key release, refusal of an altered starting point, expired
commands, missing controls/poses/calibration, automatic/capture-only locks,
arrival settling, no-progress/feedback failures, pending-ticket deadlines and
refusal to recover/resume after lost identity.

The editable installation imports the repository source. Before reloading it,
previous source versions were backed up and the config, saved Southperry profile,
recognition coverage and recording inventory were pinned under
`artifacts/southperry-short-walk/`. The managed engine restart uses capture-only
mode; it sends no movement, starts no walk, and does not enable gameplay input.
`activation.json` records the resulting engine mode and preservation checks.
This is installed behavior with offline verification; native arrival remains
untested. Setup/activation time is separate from the reported test runtime.

## First native attempt requires a separate explicit batch

The operator must be present on the bot-friendly server and explicitly approve
the batch. It must load the existing Southperry saved profile, obtain fresh
same-character/platform feedback, verify left/right controls and the live
stopping corridor, and satisfy all existing input gates. If needed, announce
and use `tools/restart_engine.ps1 -EnableGameplayInput`, then
`tools/start_overlay.ps1 -WaitForEngine`. A missing or refused gate ends the
attempt; do not alter it or substitute an automatic position.

Submit exactly one `nav_walk` request with `dx: -80` and `opt_in: true` through
the normal versioned debugger command API. Record the start, travel, stopped
target and one-second settled arrival. First failure: release input, save clip,
alarm, leave the game open and hand control back immediately. No unchanged retry.

No live walk, control probe or native movement test was performed by this task.
Do not interpret the installed command as approval to start one.
