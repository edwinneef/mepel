# Town movement validation

For the prepared follow-up using the saved calibration and accepted controls, use
[the single Henesys Park session bundle](henesys-park-session.md). It is offline
preparation; live work waits for an explicit new session request.

Develop and check changes while the bot is Off. The ordinary offline loop is
`./tools/dev_cycle.ps1`: focused launcher, town-check and navigation tests plus
lint, with no game dependency. Select `-PythonTests` or `-Scope ui -UiTests` to
check a narrower change. UI tests/build run only when selected; restarts require
`-Restart` and use `tools/restart_engine.ps1`. Add `-EnableGameplayInput` for an
input-capable session. Timings and any previous UI build are retained under
`artifacts/dev-cycle/`. A failed check prevents later build/restart steps.

## Map and start spot

Use **Mushroom Park, 100000200**, reached from Henesys. On the lower ground, walk
right past Pia and stop roughly **100 pixels left of the only ladder**. The public
world position is **x3190, y574**; the ladder is at x3291, from y574 to about y334.
The public layout has no listed monsters, seven NPCs and no exit near that ladder.
The live minimap must match; public geometry is not proof of the current server.

Prepare a separate saved area with a real reference view and walk calibration,
then dry-run `python -m maplebot import-map <area-id> --map-id 100000200 --dry-run`.
Import with the engine stopped only after the dry run succeeds. The existing
importer retains a backup of the previous area revision. Existing saved maps,
reference images, calibration, recordings and personal config must be preserved.
Never copy calibration from another map or invent a reference view.

## Bounded check

With the installed engine and overlay running, Bot Off, game already focused and
the character recognized at the start spot:

```powershell
.venv/Scripts/python.exe -m tools.town_check --check
.venv/Scripts/python.exe -m tools.town_check --run
```

`--check` reads status and plans the ladder round trip without commands or file
writes. `--run` first pins the saved area's public ID, revision/hash and engine
session. It requires a fresh confident player, matching minimap marker and a
confirmed platform. All existing engine, overlay, watchdog and F8 gates apply.
The checker does not travel, focus the game, close settings, acknowledge alarms
or change gates. A missing gate or unsupported route is a blocker.

The batch contains six bounded segments: left, right, jump, ladder ascent,
confirmed grip on the same ladder, and descent to the starting platform. Descent
is pinned through the ladder because a direct return route can choose a drop.
Each probe has at most eight seconds including its
three-second countdown; each route retains the engine's 60-second route budget
and the checker's 70-second outer limit. Only observed displacement or jump/landing
confirms a probe. A route to the current platform cannot count as movement.
No combat or manual recording is needed; F8 stops at any point.

Stop the batch at its first failure. Inspect that step's clip and fix the cause
before another run; unchanged failed movement is refused using code, map and
binding hashes. Missing focus, map or player recognition requires an operator
handoff rather than automatic window takeover. The checker finishes by requesting
Stop after any attempted probe/route. Its report records Stop acceptance and final
Off status; those readouts do not independently measure physical keyboard state.

Every run, including a preflight refusal, writes
`artifacts/town-checks/<timestamp>/result.json`. Movement steps link saved clips
and status samples. Setup time and test time are separate; test time includes
countdowns. Offline planner results never count as native acceptance. If live
conditions are unavailable, leave the movement outcome pending and continue
independent offline work without keeping the character exposed.
