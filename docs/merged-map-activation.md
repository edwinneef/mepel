# Merged map activation — 2026-10-26

The reviewed Over the Wall map was saved as **revision 4** with explicit partial-map
confirmation. It contains 16 platforms, one rope and 33 directed links.

- Ground floor 2 (P16) remains unreachable. No connection was invented or removed.
- The active-map status now recomputes route problems, so the warning remains
  visible after teaching ends. A regression covers warning retention after save.
- Browser verification shows “Map saved”, revision 4, P16's missing-journey warning,
  and “Capture only · input locked”.
- Stop was sent before saving. The resulting stop record is `OPERATOR_STOP`, mode
  is capture, and the capture-only instance cannot send gameplay keyboard input.
- Teaching is no longer recording/reviewing; the used checkpoint was retired with
  its recovery copy retained. The original merged sample evidence remains backed up.

Backups:

- Full pre-activation areas/drafts: `artifacts/map-activation-20261026-050854/areas/`
- Automatic previous-map backup:
  `data/areas/98a20c69939d450fb46e5e9342b83734.r3.1792987774624197900.bak`
- Save response: `artifacts/map-activation-20261026-050854/save-result.json`
- Final receipt: `artifacts/map-activation-20261026-050854/installed.json`

The automatic backup's bytes match the pre-activation revision-3 map. Five unrelated
configuration/other-map hashes are unchanged, as is all pre-existing untracked work.
The warning-retention fix passes 44 targeted tests and Ruff.

Activation saves geometry only. No navigation/combat run was started; p6–p8 remain
deferred. Any future navigation must exclude unreachable P16 until evidence supports
an inbound connection. Partial reference coverage and unverified contact/movement
warnings also remain applicable.

The earlier draft-only restore command intentionally refuses after this active-map
revision change. Any requested rollback now needs to restore the map and review
checkpoint together using the preserved backups, without overwriting newer work.
