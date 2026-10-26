# Bounded navigation

Navigation → Routes loads recorded movement evidence for the tracked saved map.
Choose an origin and destination, then Preview route. Every place shows its name
and stable P/R label. Unknown position permits a hypothetical preview, never input.
Teach map retains the teaching review and its unreachable-fragment warning.

Preview is the default after restart. In an input-capable session, Start navigation
also requires explicit supervision, confirmed movement controls, fresh fused origin
feedback, the same map revision/hash, and the existing capture/focus/alarm gates.
It gives three seconds to focus the game. Stop/F8 releases input; it never resumes
automatically. Combat is exclusive. HP/MP preempt movement.

Movement uses fresh feedback and bounded controller pulses/vertical leases.
Limits: eight edges, 60 seconds per route, eight seconds per edge including a
single settled-origin retry, and two settled-surface replans. Destination evidence
must persist at least 300 ms. Rope proximity alone cannot confirm grip. Lost focus,
wrong map, stale/disagreeing feedback, unsafe zones or budget exhaustion stop input.
An inferred platform match is not native contact proof.

## Installed map and offline evidence

Over the Wall revision 4 is unchanged. Its structural home is Ground floor · P3.
Conservative evidence filtering leaves 29 movement links and 14 platforms plus R1.
Ground floor 2 · P16 remains outside the home component. Right ledge · P5 is also
unavailable: its recorded return launch misses the learned surface tolerance.
Another edge has discontinuous observations. These restrictions affect navigation,
not the saved teaching geometry or its retained warnings.

Run the saved-anchor decision smoke without capture or keyboard authority:

```powershell
.venv/Scripts/python.exe tools/navigation_replay.py data/areas/98a20c69939d450fb46e5e9342b83734.json --output artifacts/navigation-replay.json
```

All 29 retained traces and the composed P3→R1→P1 route reached the simulated
destination. The clock, surface labels and same-surface approach connectors are
synthetic; this checks decision compatibility with saved XY anchors.
It does not establish perception quality, collision/contact, grip or live arrival.
Planner, executor and runtime tests separately cover exclusion, revision changes,
stale/focus loss, bounded recovery, potion priority, queued cancellation and Stop.

## Native acceptance remains pending

No native movement is authorized by route preview or installation. The current
installation stays capture-only. A separate operator opt-in is needed for p6.
Audit current capture/recognition/probe evidence before asking for any new test.
There is no requirement for combat or another manual recording.

After that opt-in, allow at most three checks, stopping at the first failure:

1. One existing bounded left/right control probe in the interior of P3, with
   adequate distance from portals and ledge edges. Observe displacement and key
   release; confirm only the matching probe result. This is not a P3→P3 route:
   a route to the current platform intentionally sends no movement.
2. Preview P3→P2 (l33). With fresh P3 feedback and supervision selected, use the
   single header Start navigation, focus the game during its three-second delay,
   and observe settled P2 arrival and released keys within the route/edge budgets.
3. If both previous checks pass, return manually to P3 while navigation is stopped.
   Preview P3→P1 via R1 (l11/l13). Require aligned vertical progress before grip
   inference, then settled P1 arrival/release. Unsupported controls or unclear
   observation block this check; do not bypass a gate or repeat blindly.

Use existing engine status/outcomes for evidence. Record any failure and disable
the unsupported movement before considering further checks. Combat and cutover
remain deferred.

## Install and rollback evidence

`artifacts/navigation-install-path.txt` points to this install's backup folder.
It contains protected data hashes, area/config copies, installed asset hashes,
API preview/status evidence and a ZIP of tracked files from pre-navigation commit
54261a2. Other pre-existing/untracked files are preserved separately in place.
To roll back, stop the engine, compare any later edits, and restore only the
owned code/workbench files from that ZIP. Leave data/config/drafts untouched.
Restart using the default capture-only `run.ps1`; never restore a running state.
