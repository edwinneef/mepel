# Middle Forest III public-layout draft — 2026-10-28

Review-only. The active map (revision 4), teaching checkpoints, calibration and
config were not written. No capture, input or engine restart was involved.

## How it was built

`tools/footholds_diff.py` compared taught revision 4 with the public map data
(`api.dreamms.gg` map 103030200, the catalog's source). Every taught surface
matched within p95 9.4 px (rope x) and 8.7 px (platform height), so the server
uses the public layout. `tools/public_layout_draft.py` then placed the public
footholds, ropes and visible portals into area pixels with that fitted transform:

- Platforms are the public foothold runs, with their slopes. Ends are padded by
  one marker step (~15 px), as the teacher pads walked ends, but never past the
  middle of a gap to a platform at the same height.
- Rope ends snap to the platform at their foot and top, plus half a vertical step.
- Taught IDs and names stay on the surface they cover most. Taught pieces of one
  public platform fold into it.
- Each taught link moves to the surfaces its own recorded launch and landing stand
  on. Links between pieces of one public platform disappear.

## Result

17 platforms, 7 ropes, 1 portal zone (`out00` on the floor). 38 of 59 links
remain; the other 21 were walks between pieces of one platform. With the recorded
moves carried over, 35 edges are usable. Home is the whole floor ("Left ledge").

Needs a decision:

- **Middle ledge 2** is two public platforms with an 11.6 px gap. The operator
  walked across it, so the teacher joined them. While split, Left ledge 8 and
  Public ledge 1 are unreachable until a move across the gap is taught (or the
  halves are joined).
- **Public rope 1** (ladder, x≈848) and **Public rope 2** (rope, x≈1225, down to
  the floor) were never climbed and have no links.
- "Ground floor" still names a middle ledge (y≈719); names were kept as taught.

## Not ready to activate as-is

Route evidence is rebuilt from teaching logs, which only reproduce the taught
shapes. Activated today, the candidate would have **0** usable routes (now 59).
The remapped evidence in the bundle shows what is possible once evidence can
follow a remapped map.

## Bundle

`artifacts/public-layout-draft/middle-forest-3/`: `candidate-profile.json`,
`candidate-evidence.json`, `report.json`, `schematic.png` (taught red, candidate
green, portal orange) and `active-profile-before.json`. Delete it to discard.

```powershell
.venv\Scripts\python.exe tools\footholds_diff.py --source artifacts\footholds-diff\middle-forest-3-public.json --output artifacts\footholds-diff\NEW.json
.venv\Scripts\python.exe tools\public_layout_draft.py --diff artifacts\footholds-diff\NEW.json --output artifacts\public-layout-draft\NEW
```
