# Bowman preparation

Ranged decisions use `[agent].attack_min_range` and `attack_range` in
`config.toml`: horizontal distance between detected player and monster centres,
in native capture pixels. The current 0–90 values are inherited warrior tuning,
not measured bowman limits. Do not start moving combat with these values merely
because the attack keys have been confirmed.

## Current preparation (27 October 2026)

The installed input-capable engine has **Space** for basic attack, **Ctrl** for
Arrow Blow and **Alt** for jump. Bowcaine is freshly recognized through the saved
name tag. Attack and skill are correctly unconfirmed after the binding changes;
the seven unchanged movement/potion confirmations remain saved.

The first inspected picture was **Hidden Street / Utah's Pig Farm**. Offline OCR reads
`Utah's Pig Fann`, leaving catalog matching paused. Its cached map profile also
references monster ID 9100007, which is absent from the installed sprite catalog.
That picture had no recognized same-platform target. The snail beside Bowcaine is a pet;
do not teach it as an enemy. Recognition of the player alone is insufficient to
start combat. Use a location where a real same-platform monster receives a fresh
enemy box, or teach a tight example of that monster through Recognition first.

The final live check recognized **The Forest East of Henesys**, unpaused the
catalog and found same-platform pigs at 83.5 and 186.5 px from Bowcaine. No new
templates or recognition changes were needed. Evidence is in
`artifacts/bowman-readiness-20261027.jsonl`; these are observed distances, not hits.

## Two attack checks before the combat run

Combat effects are required for these two checks. No new full recording is needed.
Allow about 30–60 seconds of active testing after positioning; travel/setup is
separate. Keep F8 available, equip the bow and ammunition, and face one visible
monster from a clear position on the same platform, away from an edge.

1. F7 → **Connection → Verify controls → attack**. Close settings with F7,
   focus the game and press F6. After the three-second countdown, observe the
   single Space press. Reopen F7 and choose **Confirm observed effect** only if
   the basic attack actually occurred. A projectile alone confirms the key effect,
   not hit range; range evidence needs visible damage or a hit on that monster.
2. Repeat once with **skill** for Ctrl / Arrow Blow. Record whether the skill
   occurred and whether it hit. If either probe fails, reject it and stop this
   round; do not repeatedly press F6. Do not repeat the seven unchanged probes.

The read-only observer below can run alongside those checks. It makes only GET
requests, sends no gameplay keys and never confirms a probe. It reports fresh
same-platform centre distances and the active probe so observed hits can be
associated with a distance. Distances alone do not establish hits or a continuous
working range. Existing output files are never overwritten.

```powershell
.venv\Scripts\python.exe -m maplebot.combat_readiness
.venv\Scripts\python.exe -m maplebot.combat_readiness --seconds 60 --output artifacts\bowman-probes.jsonl
```

Use a new output filename for another round. If `same_platform_targets` is empty,
resolve monster recognition/positioning before range measurement. File range
settings are labelled separately because they do not prove what a running engine
loaded. Report the two observed effects/hits and the JSONL path; choose and install
a conservative interval shared by both attacks from the resulting evidence.

After range installation, select F7 → **Bot → Activity → Decision preview**,
close settings and press F6. Verify that the intended monster is selected at the
measured distance. Then select **Combat + configured potions** and run at most
10 seconds, stopping with F8 after the first clear attack/hit sequence or any
unexpected movement. This final run is pending the two probe results and range.

Before enabling bowman combat:

1. Teach the new character's name tag through F7 → Recognition and verify fresh
   player detection. Existing saved maps can still be used and new maps taught.
2. Set the actual basic-attack and skill bindings in `config.toml`. Confirm
   those controls on this character; old-character confirmations do not prove
   the new character's attack works.
3. Choose the bow attack/skill and measure its working distance manually. Use a
   conservative distance interval that works for both basic and skill attacks:
   the bot falls back to basic attack when MP is low or unreadable. No class
   range, projectile travel time, ammunition supply or successful hit is inferred.
4. Put the measured limits in `config.toml`, restart with
   `tools/restart_engine.ps1 -EnableGameplayInput`, and use Decision preview first.

Targets must still be on the same apparent platform. Outside maximum range the
existing approach policy applies; inside minimum range the bot stops and
requests manual repositioning. Facing is rechecked before attack. There is no
automatic retreat, kiting, cross-platform shooting or obstacle/line-of-sight
inference. The bounded attack-attempt limit and screenshot observation remain.
