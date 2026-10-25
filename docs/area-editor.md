# Review the hunting-area editor

Phase 3 adds saved geometry and fixed reference views. It does not enable automatic
localization, routes or movement. The installed review session is capture-only.
No combat, probes or additional recording is needed.

1. Refresh http://127.0.0.1:8765, open **Navigation**, and click **New area**.
   Input should show as stopped and Start should remain disabled during editing.
2. Give the area a name and click **Capture reference view**. Keep MapleStory
   visible and unobscured during capture. The main image becomes a fixed reference.
3. Choose **Hunt boundary** and drag a rectangle around the area to teach.
   Add **Platform**, **Rope / ladder**, **Avoid zone** or **Portal zone** shapes
   inside that boundary. Ropes stay vertical. Choose **Select**, or use
   **Selected item**, to remove a shape and redraw it.
4. To describe a connection, choose **Link from**, **Link to** and **Link kind**,
   then click **Add directed link**. Links have a direction; the reverse connection
   needs its own link. Unreachable-surface warnings do not prevent saving.
5. Click **Save area**, then **Exit editing**. Select the saved name under
   **Hunting area** and click **Load area**. Confirm the reference, shapes and
   links return. Exit editing again when finished. Gameplay remains stopped.

Report misplaced shapes, missing saved items or confusing controls. Phase 4 stays
pending until this review is resolved.

## Additional scrolling views

Capture another reference when the camera shows another part of the same area.
Under **Align this view manually**, set **View origin X/Y** to the area coordinate
at the image's top-left and set **View scale** (normally 1). Match shared landmarks
before drawing. Scale converts area units into image pixels. Alignment is manual;
it is not evidence of the player's location or contact with a surface.

Use **Hunting boundary dimensions** to expand the boundary beyond one view. The
same area geometry appears in each reference according to its origin and scale.
Geometry outside the hunting boundary must be corrected before saving.

## Saved data and recovery

New profiles live in `data/areas/<id>.json`; immutable reference PNGs live in
`data/areas/frames/`. Profiles use schema version 1 and increasing revisions.
Each update backs up the previous JSON revision before replacing it atomically.
Stale saves, corrupt files and unsupported schemas are rejected without replacing
existing profiles. Other configuration, calibration and saved controls are unchanged.

Closing a tool or ending editing retains its draft in that browser session.
Switching to another area asks before discarding unsaved changes. Reloading or
closing a page with unsaved changes triggers the browser's warning; save first.
If another dashboard ends the edit session, this draft remains available but must
enter stopped editing again before it can change.

Graph checks validate references and directed reachability. They do not establish
whether a jump, climb, rope attachment or safe route is physically possible.
