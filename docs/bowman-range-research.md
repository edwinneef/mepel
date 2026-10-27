# Bowman range research - 27 October 2026

## Result

Use published mechanics to choose the range; another manual hit-distance check is
not required. Both accepted Space and Ctrl hits remain accepted. The current
server/version and Eye of Amazon level are not identified in project settings.
Do not combine values from different versions into a claimed exact client range.

## MapleStory Classic World

NiaMeowDB's own targeting research reports a base reach of **300 game pixels for
basic bow/crossbow shots** and **350 for Arrow Blow**. Eye of Amazon adds zero
when unlearned, then `45 + 5 * level` at levels 1-15. Consequently basic shots
reach 300-420 and Arrow Blow 350-470. The shared maximum is the basic attack's
reach, because the bot falls back to Space when MP is low or unreadable.
[Targeting formulas](https://meowdb.com/msclassic/formulas/targeting).

The same research starts basic-shot and ranged-skill targeting bands **65 game
pixels ahead**, centred 28 pixels above the character's feet. The bands widen
with distance. Target selection requires overlapping attack and monster boxes;
65 is therefore a targeting-band start, not a universal minimum distance between
sprite centres. Terrain can also block a projectile.
[Targeting geometry](https://meowdb.com/msclassic/formulas/targeting).

The author reports checking projectile base distances and passive maxima in
August 2026, with matching launch descriptions. This is independent research,
not an official Nexon guarantee or a measurement of Bowcaine's client.
[Measurement method](https://meowdb.com/msclassic/guides/weapon-reach).

The current skill page lists Eye of Amazon's 15 levels, from +50 to +120. Older
eight-level or five-level skill tables must not supply its per-level formula.
[Eye of Amazon](https://meowdb.com/msclassic/skills/bowman/the-eye-of-amazon).

## Why an online 400-pixel value is not interchangeable

The open-source HeavenClient snapshot
`cbb0fe27cf9683a12eca0a569121d8033cdc2a4d` initializes projectile range to 400.
Its range accessor constructs a rectangle with horizontal endpoints -400 and -5
and vertical endpoints -50 and 50. Skills can replace their rectangle or apply
a horizontal multiplier before targeting. This describes that implementation;
it does not establish Classic World's range or Bowcaine's minimum distance.
[CharStats](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Character/CharStats.cpp#L31-L59),
[range accessor](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Character/CharStats.cpp#L246-L249),
[skill overrides](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Gameplay/Combat/Skill.cpp#L187-L216),
[targeting](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Gameplay/Combat/Combat.cpp#L109-L142).

## Translation to this bot

`src/maplebot/decision.py` compares horizontal detection-centre distance with
`attack_min_range` and `attack_range`, shared by basic and skill attacks. The
18-pixel feet-height gate is a separate eligibility rule. `capture.py` retains
native screen pixels; perception restores coarse proposals to native coordinates.
Neither establishes the game's internal render scale. Window width alone is
not a conversion factor, and sprite centres are not the game's targeting origin.

For an identified Classic World client at native 1:1 rendering, **120-250 capture
pixels is a conservative candidate preset**, not a published boundary or measured
guarantee. It leaves 55 pixels above the targeting-band start and 50 below the
unlearned basic-shot reach. Those margins are engineering choices; they do not
prove coverage for arbitrary sprite widths, scaling, scenery or moving enemies.
No Eye bonus is needed for this candidate. Preserve the platform gate, facing
checks, minimum-range stop, input safeguards and attack-attempt limit.

Existing evidence in `artifacts/bowman-labelled-hit-review-20261027.json` records
Space damage at an observed 196.5-pixel separation and Ctrl arrow flight at 240
pixels before confirmed damage. These observations are consistent with the
candidate; they do not establish its endpoints. Space's 24-pixel feet gap still
fails the unchanged 18-pixel eligibility gate.

This research changes documentation only. `config.toml` remains 0-90; no preset
was installed, engine restarted, controls reset or gameplay input sent. The next
configuration decision needs the server/version and, for a maximum-reach preset,
Eye level. It needs no new target, range recording or repeated hit confirmation.
