# Backlog

## Navigation setup cost

Source: navigation challenge of 2026-11-02 (HEAD d942ebf). Setup by hand cost 6 to 34 min per map; proving moves took hours of wall-clock for about 6 armed minutes. Open items, most operator minutes saved first. Rotation no longer needs proofs (fc2ccd2), so the old rebuild-after-proof item is dropped.

- Keep the walk calibration on re-import. `import_map` defaults `automatic=True` (`map_import.py:40`) and `build_area` then drops `minimap_calibration` (`public_map.py:437-439`), against `map_import.py:3-4` and `docs/meowdb-maps.md:24`. The CLI never passes `automatic` (`__main__.py:86-89`).
- Hash move proofs over geometry fields only. `map_hash` covers the whole profile including `revision` (`navigation.py:71-72`), and every save bumps it (`profiles.py:335-347`), so recalibration or re-import wipes a map's proofs (`move_proofs.py:39`).
- Auto-create the area from the first tracked frame: OCR title to map ID (`map_filter.py:70`, dropped at `:134-140`), cached public geometry, automatic alignment, the current frame as reference view. Areas are only created by `area_save` today (`runtime.py:378-379`). Walk calibration stays, learned passively (20 pairs, p95 within one marker pixel, `live_position.py:36-39`).
- Offline move preflight in `tools/navigation_harness.py`: use the `moves.py` constants (555/2000/140), 16 px marker steps and a rope model (the harness uses 310/620/180 at `:40-44` and refuses ropes at `:286-288`). Validate against the 25 proof clips: predicted landings inside the 64 px corridor per move kind. It may order or skip explore moves; live proof stays the only grant of authority.
- Fix stale text: `README.md:155` still says to run walk calibration once, and the `begin_calibration` message points to a button that was removed (`live_position.py:389-392,418-420`).
- Two failing tests that also fail on a clean HEAD: `tests/test_navigation_recovery.py::test_up_is_not_released_when_the_jump_ticket_completes` and `tests/test_meowdb.py::test_classic_routes_replay_at_three_fps`.
- Generalize the WZ extractor (any map ID, generic checks, bot-shaped output behind the subprocess boundary). Gains alignment quality and portals only; build identity is unknown (BMS/779 is not a build, `artifacts/classic-assets-verification.md:43-44`). Low priority.
- Rejected: carrying proofs across maps by move type. Three of Tree Dungeon's four misses sat in classes with proven moves. At most, carry exclusions or order exploration.

## Autopotter

Use HP/MP potions automatically when either bar drops below a configured threshold.

- Read HP and MP from the status bar in the screen capture. Nothing reads them yet, so this has to be built first.
- Config: separate HP and MP thresholds (percent), a potion key for each, and a minimum cooldown between presses.
- Send presses through `KeyboardController` so the existing safety checks, timing realism and `input.max_action_seconds` limits still apply.
- Potion use takes priority over combat actions, but must not interrupt a sequence that holds keys in an unsafe way.
- Stop and alert when bar readings are missing or don't change after a press (out of potions, wrong key, misread bar).
- Tests: bar-reading fixtures from recorded screenshots, plus threshold, cooldown and priority logic against a fake input backend.
