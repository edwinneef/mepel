# Bowman preparation

Ranged decisions use `[agent].attack_min_range` and `attack_range` in
`config.toml`: horizontal distance between detected player and monster centres,
in native capture pixels. The current 0–90 values are inherited warrior tuning,
not measured bowman limits. Do not start moving combat with these values merely
because the attack keys have been confirmed.

## Current range method: online research

The operator replaced manual range measurement with online research on 27 October.
See [Bowman range research](bowman-range-research.md) for version-specific sources,
published basic/Arrow Blow reach, targeting geometry and a conservative candidate
preset. The remaining input is the server/version and Eye of Amazon level, not
another target or attack recording. No range preset has been installed yet.
Both accepted hit confirmations stand. Instructions below for collecting range
samples are historical reference and do not request another test.

## Current preparation (27 October 2026)

The installed input-capable engine has **Space** for basic attack, **Ctrl** for
Arrow Blow and **Alt** for jump. Bowcaine is freshly recognized through the saved
name tag. The operator has now confirmed that both **Space** and **Ctrl** fire.
The engine retains both confirmations, plus the seven unchanged controls.
Hits were explicitly **not checked**. Do not repeat control verification.

Evidence: `artifacts/bowman-a5f3aa5147144da1a36fd767c82078a6-3.json`
records skill input completion and the operator's confirmation (probe 3,
generation 20). Every recorded `same_platform_targets` list is empty;
`hit_confirmed` is null. The matching live session also confirmed attack probe 2.
This accepts both key effects but supplies no hit-distance measurement.

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

## Historical hit-range evidence

### Two separately labelled manual checks

The earlier mixed-key recording supplies visible damage (140 on Dark Stump, 48 and
168 on Slime), but does not identify which key produced each hit. See
`artifacts/bowman-visible-hits-20261027.json`. The 111 px slime observation is
not an exact firing distance. Keep the range unchanged until evidence supports it.

**Labelled checks reviewed:** the operator confirmed both hits, and all 101
pictures were saved across the two checks. Space dealt **44 damage to a Stump**
in `artifacts/bowman-hit-space-1793124485357092500/0018.png` (frame 25466).
The matched centres were **196.5 px** apart at visible damage, with a **24 px**
feet-height gap. That gap exceeds the bot's unchanged 18 px platform tolerance;
the hit is accepted, but the bot would reject that positioning.

Ctrl dealt **156 damage to a Slime** in
`artifacts/bowman-hit-ctrl-1793124521371287400/0012.png` (frame 25634).
The earlier arrow-flight picture `0009.png` (frame 25631) has a confident
Slime match **240 px** away, with a **13 px** feet-height gap. Review details:
`artifacts/bowman-labelled-hit-review-20261027.json`. Labels plus the operator's
report establish which check hit; neither distance is a keyboard timestamp or
a minimum/maximum range boundary. Do not repeat either accepted hit confirmation.

The previous proposal to repeat Ctrl near 197 px is superseded by the online
research above. Different observed samples remain recorded as observations;
published mechanics can support choosing a shared preset without repeating them.
Preserve the height gate and saved controls.

Use `tools/bowman_hit_check.ps1` for **one Space attempt and one Ctrl attempt**.
This GET-only helper saves frame-matched pictures, enemy detections and distances
in separate `artifacts/bowman-hit-space-*` / `bowman-hit-ctrl-*` folders. It sends
no input and never changes confirmations. Do not use Verify controls for these
checks: starting an existing probe clears that action's previous confirmation.

Keep the engine/overlay running and Bot activity **Off**. Equip bow/ammo, close
game chat, face one freshly boxed enemy on the same flat platform, and stand still.
In PowerShell from `D:\projects\maple-external-bot`, run the commands separately:

```powershell
.\tools\bowman_hit_check.ps1 -Key Space
.\tools\bowman_hit_check.ps1 -Key Ctrl
```

Each command waits for Enter. Then focus the game, wait three seconds, and press
**only the named key once**. Watch for a damage number over that enemy; stop after
the attempt, or skip it if recognition is lost. Capture ends automatically after
10 seconds. Finish the first command before starting the second. This is at most
20 seconds of capture plus two three-second countdowns; positioning is separate.
Keep gameplay Off afterward and report each result as hit / miss / unclear.
There is no extra recording or download to manage; the agent can inspect these folders.

Labels record the intended manual key, not keyboard telemetry. Pictures and
observations require review to associate the hit with the correct enemy; a missing
or superseded picture is explicit. These checks establish working sample distances,
not the full minimum/maximum range. `-Check` runs a one-second installation check
without requesting a manual attack and labels that evidence accordingly.

The Bot page now contains **Bowman on one platform**, shared engine readiness,
direct **attack** and **skill** probes, and the engine-loaded range. **Movement
and potion controls** retains all other probes and their saved confirmations.
Connection still offers the same controls. Selection never sends a key: F6
starts the existing countdown. Readiness describes preparation; focus and all
other live guards are checked again before input. Unmeasured range remains
explicitly unverified even when controls are confirmed.

**Bot → What happened** retains the last run after Stop, including queued keys,
controller results, manually confirmed probe effects, observed potion-probe bar
gains and the stop reason. **Save run evidence** downloads that run as JSON.
Save each probe before selecting the next run: the log keeps 64 recent events
for the latest run in this engine session. Frame distances are observations
collected alongside events, not proof of the exact keypress or hit distance.
The read-only observer also includes this evidence and engine-loaded tuning.

The demo UI and evidence collection are installed; native acceptance remains
pending. The latest inspected live picture is **Henesys**, correctly recognized
with the catalog running; no attackable monster is visible. Manually move to a
clear single platform with a freshly boxed enemy. Keep all nine valid
control confirmations. The next check measures visible damage and target
distance for both attacks; it does not repeat key verification. Do not enable moving combat until hit-range evidence
has supported and verified replacement of the inherited 0–90 px tuning.

### Unreadable map diagnosis (27 October 2026)

The submitted combat run is retained in
`data/recordings/session-1793117446936591500-combat`. All 186 decision rows
reported an unreadable map and paused catalog, with no OCR exception. Its
uncovered minimap says **Warning Street / The Swamp of Despair I**. Replaying
the original title extraction produced `The Swainp of Despair I`: the brightness
mask discarded antialiased edges of the letter m. The strict fuzzy matcher
correctly rejected this ambiguous text rather than guessing among I, II and III.

`map_filter.py` now retains those edges. The captured-title regression reads the
exact title with Windows OCR; map matching thresholds remain unchanged. Offline
replay of frames 7348 and 7509 recognizes the map, activates 44 template variants
and detects Ligators / Jr. Necki. Results: `artifacts/map-diagnosis-replay.json`.
This establishes restored recognition on saved frames, not attack hits or range.

A live check in **The Forest South of Ellinia** also exposed repeated map
invalidation from moving scenery inside the fixed-width OCR crop. Extraction
now clips to the expanded minimap's solid right border when present. A regression
test changes exterior scenery without invalidating the map, then verifies that
changing the title itself still invalidates it.

The separate stop on frame 7509 remains valid: the player is partly hidden by
foreground grass, no name tag is visible, and neither the recorded detector nor
offline replay finds a confident player. The run queued no gameplay input.
Do not loosen confidence or recalibrate solely because of this obstructed frame;
use a clear platform with fresh player and enemy boxes before measuring range.
The current player is again recognized in Henesys. Both firing confirmations and
the other seven accepted controls remain valid; no repeat probes are needed.

### Completed control checks (reference only)

These two control checks passed. Hits remain untested. No new full recording is needed.
Allow about 30–60 seconds of active testing after positioning; travel/setup is
separate. Keep F8 available, equip the bow and ammunition, and face one visible
monster from a clear position on the same platform, away from an edge.

1. F7 → **Bot → Verify controls → attack**. Close settings with F7,
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
unexpected movement. This final run is pending measured range and hit evidence.

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
