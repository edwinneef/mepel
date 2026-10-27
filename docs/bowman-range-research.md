# Bowman range research - 27 October 2026

## Result

Use published mechanics to choose the range; another manual hit-distance check is
not required. Both accepted Space and Ctrl hits remain accepted. The operator
identifies the game as a **custom v83 private server/project implementing newer
Classic features**. Its project name, range overrides and Eye of Amazon level
are not yet identified. Classic feature parity does not establish that it adopted
Classic World's targeting implementation or skill values.

## v83 baseline and remaining project-specific evidence

Cosmic's author reports reverse-engineering a v83 client and finding a
400-pixel projectile-range stat for bows, crossbows, claws and guns, with
Eye of Amazon range bonuses of 15-120 across its eight levels. The report
describes rectangle overlap with each monster's animation-frame body bounds,
rather than a circular distance test. This is a published disassembly report;
we have not reproduced the disassembly or inspected this project's binary.
[Pinned v83 investigation](https://github.com/67-6f-64/Cosmic/blob/b684bf78588d50512bcd62db9bb7cb85e4f73829/docs/bot/kb/kb_v83_client_combat_internals.md).

Together with HeavenClient's inspectable implementation below, this supports
**400 game pixels as a v83 research baseline**, not a verified range for the
customized client. It does not independently settle Arrow Blow's overrides,
close-range melee substitution or capture-pixel conversion. Use the exact
server/project's public repository or patch documentation to check which
Classic range changes it adopted. Eye level is needed only when using its bonus.
No further target measurement or repeated hit confirmation is requested.

## MapleStory Classic World comparison (not the identified client's baseline)

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
pixels was the conservative candidate preset**, not a published boundary or measured
guarantee. It leaves 55 pixels above the targeting-band start and 50 below the
unlearned basic-shot reach. Those margins are engineering choices; they do not
prove coverage for arbitrary sprite widths, scaling, scenery or moving enemies.
This Classic-derived candidate is not selected for the customized v83 project.
No Eye bonus is needed for that candidate. Preserve the platform gate, facing
checks, minimum-range stop, input safeguards and attack-attempt limit.

Existing evidence in `artifacts/bowman-labelled-hit-review-20261027.json` records
Space damage at an observed 196.5-pixel separation and Ctrl arrow flight at 240
pixels before confirmed damage. These observations are consistent with the
candidate; they do not establish its endpoints. Space's 24-pixel feet gap still
fails the unchanged 18-pixel eligibility gate.

This research changes documentation only. `config.toml` remains 0-90; no preset
was installed, engine restarted, controls reset or gameplay input sent. The next
configuration decision needs the exact v83 server/project name or public source
URL to check its range changes and, for a bonus-dependent preset, Eye level.
It needs no new target, range recording or repeated hit confirmation.
