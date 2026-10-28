# Classic warrior operating ranges

Choose **Bot > Weapon range > Classic weapon**, then **Apply weapon range**.
Applying stops input and saves the choice in `data/combat-range.json`; it survives
engine restarts. Equipment and character changes are not detected automatically.
Config defaults use `[agent].range_profile`; a saved UI choice overrides it.
`custom` restores the startup operating band. To use other numeric limits, set
the config profile to `custom` with those limits and restart the engine.

| Preset ID | Shortest standing animation | Operating band |
| --- | ---: | ---: |
| classic_1h_sword | 73 | 0-60 |
| classic_1h_sword_short | 64 | 0-50 |
| classic_1h_axe | 73 | 0-60 |
| classic_1h_blunt | 69 | 0-55 |
| classic_2h_sword | 75 | 0-65 |
| classic_2h_sword_long | 86 | 0-75 |
| classic_2h_axe | 84 | 0-70 |
| classic_2h_blunt | 84 | 0-70 |
| classic_spear | 111 | 0-100 |
| classic_polearm | 111 | 0-100 |

These are native-pixel centre-distance bands with engineering margins, not exact
hitboxes. Standing animation extents come from the author's Classic data
[reach research](https://meowdb.com/msclassic/guides/weapon-reach), checked
28 October 2026. The code retains each normal animation's far extent and uses
at least ten pixels inside the shortest, excluding crouch and Final Attack.
Level-100 extended attacks do not enlarge these conservative presets.

The short 1H sword set covers Long Sword, Beginner's Long Sword, Gladius, Old
Gladius, Hero's Gladius, Traus, Jeweled Katar and both Sky Blue/Yellow Umbrellas.
The long 2H sword set covers Scimitar, Lion's Fang, Sparta and Doombringer.

Power Strike uses weapon reach. Slash Blast requires an initial target within
weapon reach before its expanded area applies; its secondary area does not
extend approach distance. [Targeting research](https://meowdb.com/msclassic/formulas/targeting).
Higher-job skills with separate hitboxes are not covered by these shared presets.

The same band governs basic-attack fallback. The 18-pixel platform gate, facing,
fresh detections, input safeguards and attack limit remain active. Warrior skills
and outcomes remain unverified in-game. See [Bowman research](bowman-range-research.md)
for Classic mismatch reports; report actual evidence rather than assuming parity.

Installed 28 October: 241 focused Python tests, 81 UI tests, Ruff and UI build
passed. In a browser preview of the overlay with its desktop bridge stubbed,
the live engine accepted Spear 0-100 then Bowman 120-250; both left input Off
and retained nine confirmations. This checks settings, not native attacks.
The 51 existing protected profile files retained their hashes. Backups, build
and installation evidence: `artifacts/weapon-ranges-install-20261028-000927/`.
The installed UI includes pre-existing overlay work preserved from the checkout;
those unrelated source/generated changes are excluded from this task's commit.

## First Bowman run

Keep Bowman selected. Minimize the console/other windows covering the game and
keep the minimap visible. On a clear flat platform, wait for fresh player and
enemy boxes; keep bow/ammo equipped and game chat closed. Do not repeat the
accepted control or hit-range checks.

1. F7 > Bot > Activity > Decision preview. Close settings with F7, focus the
   game and press F6. Preview sends no keys. Check the intended same-platform
   target, then press F8. If recognition/capture is blocked, stop here.
2. F7 > Bot > Activity > Combat + configured potions. Close settings, focus the
   game and press F6. The existing three-second countdown runs first. Allow at
   most **10 seconds of combat**, then F8; stop earlier after the first clear
   approach/attack/hit sequence or unexpected movement. Setup/travel time is
   separate. Inside 120 px, a manual-reposition stop is expected.
3. Finish Off. Report hit/miss/unclear, movement direction and stop reason from
   **Bot > What happened**. Existing automatic evidence is sufficient; no extra
   recording is requested. Potion gain is only an outcome if a potion was
   actually needed; full bars do not establish a failed potion.

## Broadsword run - 28 October 2026

One API-driven run used the existing three-second countdown and stopped after
the first completed skill input: about two seconds of observed live combat,
5.7 seconds including countdown. The bot finished Off. No computer use or
range/binding changes occurred.

Frames show ScrollAddict approaching left. At frame 112089, the requested skill
was 45 px from the matched target centre, inside the 0-65 band. Ctrl completed;
the saved HUD shows MP 386/443 before and 374/443 afterward, supporting skill
use. Frame 112091 also shows incoming 65 damage and HP falling 727 to 662.
No outgoing damage number is clear enough to establish a hit. Brief target loss
during overlap is not a kill. The target was matched as Axe Stump in this run.

No potion was requested: both bars remained above the configured 50% thresholds.
Approach and skill-use evidence do not establish hit success, basic fallback,
or a potion recovery effect. This is a partial native result, not a demonstrated
Classic/v83 parity defect; keep the source-informed range unchanged.

Evidence: `artifacts/broadsword-combat-1793167024160166000/result.json` and 24
saved frame pictures, plus the existing automatic clip
`data/recordings/session-1793167027665898100-combat/` (including 112091).
The outstanding observation is whether the operator saw outgoing damage on the
stump. No repeat run or extra recording is requested to answer that question.
