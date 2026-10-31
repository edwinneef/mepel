# Farming with pet potions

## First milestone: one platform, no consumables

The engine accepts `arm` with `farming: {single_platform: true,
no_consumables: true, pet_recovery: false, session_minutes: 1}`. This uses the
existing acquire, approach, face, attack and reacquire policy without route
rotation. Other farming starts still require round-trip routes. No settings are
saved over the existing configuration. Calibrated HP/MP bars and all normal
combat, capture, focus, input, watchdog, F8 and overlay-lease gates still apply.
Low or unreadable HP/MP stops input; no food or potion keys are sent.

Use a clear continuous floor on the intended tracked map. Same-height sprite
matching does not prove continuous terrain between sprites. This mode does not
jump, climb, traverse gaps or recover from displacement using navigation.

Offline preparation does not authorize gameplay. After separate authorization,
with the operator present and the intended clear platform verified, the bounded
runner command from the project root is:

```powershell
.venv/Scripts/python.exe -m tools.farming_check --run --area <verified-area-id> --single-platform --session-minutes 1 --bot-friendly-server
```

The runner saves `artifacts/farming-checks/<timestamp>/result.json` and always
sends Stop. `functional_success` requires reaching the session deadline and
completed attack dispatches associated with at least two distinct policy target
acquisitions. Repeated polls, canceled tickets and attacks against only one
acquisition do not satisfy this condition. Dispatch completion never proves a
hit or kill; review the saved clip for native effects. An operator or low-resource
stop is `safe_stop`, not functional success. Missing evidence, recognition or
focus failures, unreadable health, stalls and unconfirmed shutdown are `failure`.
Only functional success exits zero. Stop at the first failure, leave the game
open and hand control back immediately; inspect the clip before any changed rerun.

## Multi-platform pet mode

In the browser workbench, select **Farming (pet potions)** in Run mode.
The pet supplies HP and MP potions; farming never sends either potion key.
Calibrate both bars, track the current map and retain all existing input probes.
Rotation requires at least two platforms connected by proven round-trip routes.

Defaults: 15 minutes per session; 50% HP and MP triggers. These are configurable.
Five seconds continuously at or below either trigger stops with “recovery failed”.
This does not establish that inventory is empty. Empty HP stops as possible death;
unreadable bars stop immediately. Existing combat stall, attack and navigation
budgets remain active. Stop/F8, focus, watchdog and overlay lease gates remain.
Every stop releases input and requires a manual restart.

Enter a feeding interval in seconds before starting. No default has been verified
for this private server. Food uses the existing Home binding, waits for combat
input to finish, and defers until navigation ends. It never catches up missed
feeds with a burst. Queuing food does not prove consumption or pet presence.
Settings apply to this start and are not written over saved potion settings.

Native acceptance remains pending: verify food consumption/timing, pet recovery,
combat-to-navigation-to-combat, session expiry and Stop/F8 on the intended map.
