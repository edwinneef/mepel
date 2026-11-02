# Backlog

## Navigation setup cost

Source: navigation challenge of 2026-11-02 (HEAD d942ebf). Setup by hand cost 6 to 34 min per map; proving moves took hours of wall-clock for about 6 armed minutes. Open items, most operator minutes saved first. Rotation no longer needs proofs (fc2ccd2), so the old rebuild-after-proof item is dropped.

- [x] Keep the walk calibration on re-import. Completed in `b4283f2`: imports preserve existing calibration by default; explicit automatic alignment can replace it.
- [x] Hash move proofs over geometry fields only. Completed in `0d3c460`: saves and recalibration preserve proofs when geometry is unchanged; geometry changes invalidate them. Existing old-format hashes are not migrated.
- [x] Auto-create the area from the first confident tracked frame. Completed in `1bf5a90`; saved-frame acceptance in `e56028f` verifies real OCR, cached geometry, alignment, saving/reloading and duplicate preservation in an isolated store. Uncertain frames wait; existing areas and passive walk calibration stay. No live gameplay acceptance claimed.
- Offline move preflight in `tools/navigation_harness.py`: use the `moves.py` constants (555/2000/140), 16 px marker steps and a rope model (the harness uses 310/620/180 at `:40-44` and refuses ropes at `:286-288`). Validate against the 25 proof clips: predicted landings inside the 64 px corridor per move kind. It may order or skip explore moves; live proof stays the only grant of authority.
- Fix stale text: `README.md:155` still says to run walk calibration once, and the `begin_calibration` message points to a button that was removed (`live_position.py:389-392,418-420`).
- Two failing tests that also fail on a clean HEAD: `tests/test_navigation_recovery.py::test_up_is_not_released_when_the_jump_ticket_completes` and `tests/test_meowdb.py::test_classic_routes_replay_at_three_fps`.
- Generalize the WZ extractor (any map ID, generic checks, bot-shaped output behind the subprocess boundary). Gains alignment quality and portals only; build identity is unknown (BMS/779 is not a build, `artifacts/classic-assets-verification.md:43-44`). Low priority.
- Rejected: carrying proofs across maps by move type. Three of Tree Dungeon's four misses sat in classes with proven moves. At most, carry exclusions or order exploration.

## Autopotter

Done (see README "HP/MP autopotter", `src/maplebot/autopotter.py`, `potion_evidence.py`):
HP/MP bar reading with confidence, preview without input, live potions through
`KeyboardController` with thresholds, shared cooldown, HP priority, HUD-missing pause and
stop, potion-key probes, and passive per-ticket evidence recordings
(`docs/passive-potion-evidence.md`).

Open:

- Verify a potion's effect from the bar after a press (out of potions, wrong key, misread
  bar). Passive evidence records observed gain but does not prove causation
  (`docs/potion-evidence-audit.md`).
- Inventory availability and alternative HUD layouts remain unverified live.
