# Movement bot source research — 2026-10-25

Scope: read the Auto Maple command books and MapleStoryAutoLevelUp state, route,
ladder and stuck-handling code. No movement implementation or native test.

## Source snapshots

- Auto Maple: `5d88510e582784d6992ef72e8664e7df88d392ff`.
- Auto Maple Resources: `16e5180be7812a795d13a4859394121cf72b8db5`.
- LinPolly/MapleStoryAutoLevelUp: `3e19173f8da5aab8405307bb9c6e3741dd3abd6b`.

These were the repositories' `main` commits when inspected. Links below pin the
code to those snapshots; these projects target different MapleStory versions and
classes, so their timings do not establish suitable values for our client.

## Auto Maple: feedback around class-specific movement bursts

The shared `Move` command computes its shortest path **once when the command
starts**, then repeatedly reads the current player position to correct toward
each path point. It alternates horizontal and vertical corrections and spends a
shared default budget of 15 actions. It releases the last direction when leaving
a path point. This corrects the previous claim that it recomputes the path on
every step. [Move source](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/components.py#L229-L287).

The three published command books are Kanna, Adele and Shadower. Kanna's step
uses teleport; Adele and Shadower use flash jump. Their vertical step adds jump
presses when vertical error exceeds a tolerance. These are class-specific
movement bursts surrounded by position feedback, rather than a generic
rope/ladder executor.
[Kanna step](https://github.com/tanjeffreyz/auto-maple-resources/blob/16e5180be7812a795d13a4859394121cf72b8db5/command_books/kanna.py#L43-L60),
[Adele step](https://github.com/tanjeffreyz/auto-maple-resources/blob/16e5180be7812a795d13a4859394121cf72b8db5/command_books/adele.py#L61-L78),
[Shadower step](https://github.com/tanjeffreyz/auto-maple-resources/blob/16e5180be7812a795d13a4859394121cf72b8db5/command_books/shadower.py#L43-L60).

`Adjust` defaults to five corrections. Horizontal correction checks the latest
x position every 50 ms, for at most 60 iterations per correction (approximately
three seconds plus scheduling). Up uses teleport or flash jump; down holds Down
while pressing Jump three times. The books contain no dedicated rope acquisition,
ladder tracking, knockback detector, or confirmed landing state machine.
[Kanna Adjust](https://github.com/tanjeffreyz/auto-maple-resources/blob/16e5180be7812a795d13a4859394121cf72b8db5/command_books/kanna.py#L63-L109),
[Shadower Adjust](https://github.com/tanjeffreyz/auto-maple-resources/blob/16e5180be7812a795d13a4859394121cf72b8db5/command_books/shadower.py#L63-L109).

The shared `Fall` command checks displacement from its starting position between
down-jumps, with six attempts. Displacement is not proof of arrival on a specific
platform. Also, `Point` executes its attached commands after `Move` returns; the
shown code does not require a successful arrival result before those commands.
Therefore, a bounded loop alone is not a verified move contract.
[Fall](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/components.py#L337-L360),
[Point](https://github.com/tanjeffreyz/auto-maple/blob/5d88510e582784d6992ef72e8664e7df88d392ff/src/routine/components.py#L71-L100).

## MapleStoryAutoLevelUp: spatial route commands and ladder heuristics

In hunting mode, every frame selects route commands, checks the route goal,
adds mob-based attack decisions, then applies stuck recovery if necessary.
This is not playback of elapsed keyboard timings. Patrol is a separate,
simpler mode; it does not describe the whole navigation system.
[Hunting state](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/states/hunting.py#L23-L40),
[Patrol state](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/states/patrol.py#L22-L60).

Route following searches around the player's global map position for the nearest
action-colored pixels by Manhattan distance. It searches ordinary actions and
Up/Down markers separately. The configured search radius is 10 pixels. Knockback
can change which nearby command is selected, but this does not guarantee recovery
if the player lands outside all route markers. With neither marker present,
`update_cmd_by_route` contains no branch that clears previous commands.
[Nearest marker search](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L568-L618),
[Route command selection](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L1441-L1477),
[Route defaults](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/config/config_default.yaml#L170-L195).

There **is explicit ladder-end handling**. While classified as on a ladder, the
bot combines the nearest ordinary route command and the nearest Up/Down marker
to fill a missing movement axis. This lets a horizontal exit command overlap
with continued climbing at the ladder top. The classification itself is crude:
screen-position change with `dx < 3` and nonzero `dy` sets `is_on_ladder`; a later
`dx > 3` clears it. Inference: jumps, knockback and camera motion can satisfy
parts of this heuristic; it is not verified rope attachment.
[Ladder command merging](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L1441-L1461),
[Ladder classification](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L1624-L1637).

The keyboard thread holds Up or Down according to the latest command and releases
them when that axis becomes `none` or `stop`. It does not use a per-climb deadline
or landing acknowledgement in this code.
[Vertical input](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/input/KeyBoardController.py#L249-L267).

## Exact stuck detection and recovery

The watchdog compares the current global map position with its stored reference.
Manhattan displacement **greater than 10 pixels** resets the reference and timer.
Otherwise, elapsed time **greater than 10 seconds** reports stuck and resets the
watchdog. Recovery independently picks horizontal Left/Right/None, vertical
Down/None and Jump/None; it excludes Up and teleport. This can select no action.
Hunting, patrol and finding-rune states invoke this fallback; near-rune instead
has a state timeout that returns to finding-rune.
[Watchdog](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L964-L997),
[Defaults](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/config/config_default.yaml#L197-L207),
[Random fallback](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L1523-L1531),
[Finding rune](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/states/finding_rune.py#L55-L72),
[Near rune](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/states/near_rune.py#L19-L28).

I found no explicit knockback event detector or per-incident retry budget in
these movement/state paths. Position feedback may compensate for displacement;
the source does not establish reliable recovery after being knocked off a
platform or rope.

## Implications for this project

Keep the established Phase 2/4/5 design: teach geometry and transition goals,
localize the current platform/rope, correct from fresh observations, confirm
arrival after key release, and budget recovery. Spatial route teaching can be
useful; raw timed key playback is insufficient. The inspected bots themselves
mix feedback with short scripted actions, so the previous blanket description
that neither uses recorded/scripted actions was too strong.

The useful ladder lesson is to model approach, attachment, climb and exit
separately and allow an exit transition to overlap the ladder top. That is an
inference for our design, not an executor copied from these sources. Preserve
our portal exclusions, hold leases and explicit unknown-location stop rather
than adopting sustained Up or random recovery. See
[ROADMAP.md](../.planning/ROADMAP.md), Phase 2 localization, Phase 4 move
confirmation and Phase 5 recovery budgets. This note does not authorize or
implement those phases.
