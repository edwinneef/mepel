# Farming with pet potions

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
