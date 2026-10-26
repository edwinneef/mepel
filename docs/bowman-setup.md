# Bowman preparation

Ranged decisions use `[agent].attack_min_range` and `attack_range` in
`config.toml`: horizontal distance between detected player and monster centres,
in native capture pixels. The current 0–65 values remain unchanged in behavior;
they are not measured bowman limits.

Before enabling bowman combat:

1. Teach the new character's name tag through F7 → Recognition and verify fresh
   player detection. Existing saved maps can still be used and new maps taught.
2. Set the actual basic-attack and skill bindings in F7 → Connection. Confirm
   those controls on this character; old-character confirmations do not prove
   the new character's attack works.
3. Choose the bow attack/skill and measure its working distance manually. Use a
   conservative distance interval that works for both basic and skill attacks:
   the bot falls back to basic attack when MP is low or unreadable. No class
   range, projectile travel time, ammunition supply or successful hit is inferred.
4. Put the measured limits in `config.toml`, restart with
   `tools/restart_engine.ps1 -EnableGameplayInput`, and use Decision preview first.

Targets must still be on the same apparent platform. Outside maximum range the
existing short approach steps apply; inside minimum range the bot stops and
requests manual repositioning. Facing is rechecked before attack. There is no
automatic retreat, kiting, cross-platform shooting or obstacle/line-of-sight
inference. The bounded attack-attempt limit and screenshot observation remain.
