# Single-platform combat evidence

28 October 2026; baseline `1ea32c3`, Broadsword / `classic_2h_sword` 0–65.
Scope is supervised movement, facing, attacks and configured potions on a clear
continuous floor. No routes, ladders, jumps or blind movement. The 18-pixel
feet-height check does not establish that terrain between two sprites is continuous.

## Retained evidence

- `session-1793167027665898100-combat`: nine live rows / 2.01 seconds.
  The operator-accepted approach and Ctrl hit remain accepted; see
  [warrior ranges](warrior-ranges.md). Current pixel replay preserves its decisions.
- `session-1793171780713893200-combat`: 152 live rows / 32.35 seconds,
  four completed skill tickets, 23 acquisitions and 21 non-VERIFY target losses;
  ends with F8. The old log labels Forest I; pictures show Forest III. Current
  title and OSMS selection correctly identify III. Replaying observations cannot
  establish how a changed policy would move the character in a new run.
- `session-1793171780951560000-potion-mp-t1`: both pictures and matching rows
  survive. MP is 216/443 before Delete and 236/443 afterward; the latter frame is
  264 ms after key completion. This is paired observed gain, not proof of sole
  potion causation. No passive HP ticket exists in the inspected recordings.

All session paths are under `data/recordings/`. Accepted controls and hits need
no repeat probes. Native basic fallback, HP recovery and changed repeated-loop
behavior remain unverified.

## Offline diagnosis

`artifacts/single-platform-combat-20261028/` retains the audit scripts, complete
frame results, protected-file hashes and the annotated loss sheet. Originals were
not modified. Policy replay explicitly uses 0–65, rather than the config file's
Bowman default. Differences against historical serialized decisions are explained
by runtime stop messages, renewable movement durations and potion/key deferral;
they are not evidence of a pure-policy regression.

Current pixel replay still loses the historical target on 20 of 21 loss frames.
Full-frame inspection found no confident match removed by the player-overlap
filter on these frames. The following classifications distinguish reproduced
causes from visual explanations that remain uncertain:

| Frames | Finding |
| --- | --- |
| 12285, 12300, 12318, 12348, 12392 | Sparse signature pruning rejects a visible target; permitting more proposal samples to disagree recovers a full-mask score of .921–.974, without changing final scoring or confidence. |
| 12280, 12371 | Target crosses the tracked-player search crop boundary; full-frame detection finds it. This is a bounded search-window limitation. |
| 12369, 12402 | Historical target fails the 18-pixel height gate (31 / 60 pixels); keep the gate. On 12369 a newly allowed Slime is near the previous Pig, which does not establish Pig recovery. |
| 12274, 12294, 12315, 12327, 12337, 12340, 12344, 12356, 12359, 12361, 12386, 12396 | No fresh qualifying match for the prior target. Pictures show pet/player/scenery overlap, attack effects or changed pose/position. Exact cause is not established for every frame; do not invent tracking through missing pixels. |

The signature samples at most 24 pixels, chosen by color rather than area. Its
old two-mismatch budget can reject an otherwise strong full-mask match. The
focused change should adjust proposal pruning only. Final masked color/structure
scoring, .90 confidence, map selection, fresh-target requirement and height gate
remain authoritative. Ordinary occlusion and the search boundary remain explicit
limitations; no evidence supports blind pursuit through them.

Baseline validation: 212 decision, runtime, scheduler, replay, potion-evidence
and keyboard tests passed in 6.13 seconds. These use offline/fake input evidence.

## Installation and acceptance

Pending the focused recognition fix and its checks. Preserve all saved settings,
maps, templates, nine control confirmations and unrelated UI changes. Installation
must finish Off; a new native run is not authorized by this evidence report.
