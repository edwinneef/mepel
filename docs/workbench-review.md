# Workbench review before area teaching

Open http://127.0.0.1:8765 and refresh once. The installed review session is
capture-only: keyboard output is locked. The previous debugger remains at
http://127.0.0.1:8765/legacy.

This review needs no combat, control probes or new recording. Leave the run mode
on **Preview**. Do not change the crop, teach templates or save settings just to
review the layout.

1. **Overview:** the game preview should use the available width, with Start,
   Pause and Stop visible. Player recognition, current action and the reason
   should be understandable. A stale or disconnected feed must say so.
2. **Focused tools:** open Tracking, Combat, Navigation, Potions and Settings
   individually. Only one dock should open. Close it with its close button or
   Overview; the preview should expand again. Navigation deliberately has no
   area editor yet; that is the next phase.
3. **Existing setup:** check that Settings still shows the connection, saved
   bindings and control confirmations, and Potions shows your existing
   thresholds and calibration. Settings also contains recording controls;
   Diagnostics contains timings, failures and recent decisions. Report missing or confusing controls;
   there is no need to press probes or process-control buttons.
4. **Selection:** keep the game unobscured so the capture shows its pixels.
   With a game frame visible, click Freeze & select, then drag
   over an easily recognized object. The rectangle should stay under your
   pointer even when the preview is scaled. Return to live view without
   applying the selection.

Report anything cramped, missing, hard to find, or incorrectly aligned, naming
the tool and control. Phase 3 stays pending until this review is resolved.

The UI build and automated checks establish interface and command behavior.
They do not establish actual potion effects, movement, climbing or recovery.

## Development and fallback

The shipped bundle is served by Python; Node is only needed to rebuild it:

```powershell
npm --prefix ui ci
npm --prefix ui run build
npm --prefix ui test
```

The build output is packaged under `src/maplebot/static/workbench/`. The legacy
page is retained at `src/maplebot/static/index.html`; no saved settings are
migrated merely by opening either interface.
