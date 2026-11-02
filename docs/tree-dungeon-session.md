# Tree Dungeon acceptance

Target: Tree Dungeon, Forest Up North I, area
`88e5606b858844c0a26658c004db9acc`, revision 4. No live batch has passed.

## Saved failure audit (2026-11-02)

Read all decision rows and inspected frames at the action/stop boundaries:

- `artifacts/farming-checks/prepared-single-fh333-1793600906588736300/result.json`:
  212 decision frames in `data/recordings/session-1793600909944728000-combat`.
  No attacks; SEARCH from frame 1052 through the end. Frames 1052 and 1143 show
  enemies on the ledges above the player. Same-platform rejection is appropriate;
  single-platform mode cannot leave the empty ledge. Do not loosen target gates.
- `prepared-single-fh374-1793600948197124200/result.json`: 273 decision frames in
  `session-1793600951542391400-combat`. Two completed attacks across two acquisitions;
  no hit/kill proof. Frame 1420 shows close enemy contact, then recognition pauses
  and the player settles on fh361 at 1428. Frame 1453 confirms the lower ledge and
  operator stop. Single-platform mode cannot navigate back after displacement.
- `prepared-farm-fh325-1793597515304265300/result.json`: 213 decision frames in
  `session-1793597518631248800-combat`. fh325 -> fh315 arrived, then the next movement
  departed its corridor at frame 2263. Frames 2251/2263 show launch and falling
  below the ledge, with damage visible at failure. The clip does not isolate
  knockback from a missed move. Preserve the corridor stop; exclude this segment
  from the first acceptance circuit rather than claiming an executor fix.
- `prepared-farm-fh320-1793596874200884000/result.json`: 671 decision frames in
  `session-1793596879336498200-combat`. Two attacks, then exploration and a safe
  landing on fh278. Frame 879 confirms this landing. The historical refusal says
  "reachable round-trip map over proven moves"; current computed-route planning
  no longer requires proof. Retest this distinction offline, not by replaying
  unchanged live failures.

## First circuit

The geometry has 36 platforms and 123 computed moves. A looping fh308 <-> fh315
draft compiles in both directions as direct drop/jump moves; saved geometry and
proofs support it. This avoids the failing rope/upper segment. It remains a native
acceptance candidate, not a proven farming loop. Fresh map/player/enemy gates
still decide whether a batch can start.

The existing `Whole map` saved circuit has a stale geometry fingerprint. Preserve
it; do not silently rebind it or auto-start it. Save the small candidate separately.

## Acceptance still required

Finish offline circuit/sustain start integration, then safely install it. With the
operator present and separately authorizing each batch, use the local control for
one minute, then fifteen minutes. Require combat -> movement -> combat, observed
HP/MP recovery when needed, and Off/disabled/released input at expiry. Stop at the
first hard failure, save the clip, sound the alarm and hand control back. Setup
time is separate from active gameplay. No unattended testing is authorized.
