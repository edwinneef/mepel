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

The implementation task performed no live walk or control probe. The separately
approved native verification is recorded below; it grants no further attempts.

## First supervised native pass: 2026-11-01

The operator explicitly authorized setup, necessary controls and exactly one
80-pixel left walk. One managed input-capable restart and overlay start completed;
the existing Southperry revision-3 saved calibration was loaded. The engine
accepted its restored left/right confirmations, so **zero new probes** were
needed. Guarded focus restored the unobscured game view before movement. Fresh
same-character `fh2` feedback and the real stopping corridor passed preflight.

**One walk attempted, passed, no retries.** `nav_walk` was requested at
05:01:02.770 UTC. The batch ended at 05:01:09.621 UTC, taking **6.91 seconds**
including countdown, movement, settled arrival and cleanup; startup/setup time
is additional. Dispatch history contains exactly **six left key-down/up pairs**
and no other keys, spanning 1.33 seconds from first press to last release.

The saved-position estimate moved from X 644.523 to 565.414 (79.109 pixels left),
against target X 564.523, while Y remained 549 and the surface remained `fh2`.
The reported target residual is 0.891 pixels in that saved coordinate system;
the quantized minimap estimate is not an independent claim of subpixel world
accuracy. The fresh player box separately moved 81 screen pixels left. Saved
before/after images visibly show the character move left relative to the NPC.

The engine reported `arrived`, `Short walk arrived; keys released`, with trusted
fresh same-platform feedback. Dispatch key releases balance every key-down.
Stop returned the engine to capture/Off; no active alarm or further input was
reported. The game remains open and under operator control.

Evidence: `artifacts/southperry-walk-native-20261101T045858Z/summary.json`,
`result.json`, `before.png`, `after.png` and `walk.mp4`. Original recording:
`data/recordings/session-1793509262768236300-manual/`. The summary pins its decision
log by SHA-256. All evidence is retained. This passes one saved-calibration flat
walk only; automatic alignment, jumps, ladders and multi-platform routes remain
unverified. Another live batch needs a new explicit operator-present request.
