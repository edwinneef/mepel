# Southperry artwork dependencies

Inspected only hash-pinned copies and map `000000060.img`. No installed archive,
game process, download, saved-map write or reserved-map image was accessed.

The map references eight exact logical artwork images:

- `Map/Tile/tile_whiteMarble.img`: 607 placements, 18 unique entries.
- `Map/Obj/obj_acc1.img`: 41 placements, 24 unique entries.
- `Map/Obj/obj_connect.img`: 56 placements, 7 unique entries.
- `Map/Obj/obj_housePT.img`: 8 placements, 8 unique entries.
- `Map/Obj/obj_signboard.img`: 2 placements, 2 unique entries.
- `Map/Obj/obj_vehicle.img`: 8 placements, 7 unique entries.
- `Map/Back/back_grassySoil.img`: 2 placements, 2 unique entries.
- `Map/Back/back_portTown.img`: 5 placements, 4 unique entries.

These are **image records inside archives**, not eight physical `.wz` filenames.
None of `Map/Tile`, `Map/Obj` or `Map/Back` is present in the nine-file copy receipt.
The exact physical archive shards containing these records cannot be established
from the current copies. Do not invent filenames such as `Obj_000.wz` or assume
all referenced canvases occupy the first shard.

Next needed: copied category `.ini` metadata and WZ directory/image-name indexes
for `Map/Tile`, `Map/Obj` and `Map/Back`, with file paths, sizes and SHA-256 receipts.
Then locate these eight images, inspect only their referenced properties, and
follow their `_inlink`/`_outlink` chains to identify exact bitmap archives, including
any additional `_Canvas` shards. Current map data does not contain those artwork
properties, so the transitive bitmap closure remains unknown. Full artwork decoding,
rendering and copying from installed files need a separate scoped request.

The pinned MapleLib source supports the distinction: `WzFileManager.cs` reads per-category
`LastWzIndex` metadata; `WzLib/WzLinkResolver.cs` describes category/image/property
outlinks, including separate `_Canvas` categories. Neither source establishes this
installation's missing shard indexes. Source commit:
`04570d43cd90e1b42f613226dd0be22ce58abd1c`.

Optional scene entities: `Npc/0000012.img`, `Npc/0000013.img`, `Npc/0000014.img`,
`Npc/0000015.img`. They require a separate NPC-artwork dependency trace if included
in a rendered scene. No reactor placements are present. Portal-helper metadata is
available in the existing `MapHelper.img` copy, but this trace does not certify its
bitmap coverage. The eight-image list covers core tile/object/background scenery;
it does not claim all assets for a complete animated game screenshot.

The extractor now preserves Southperry's eight layer records, backgrounds, entity
placements and portal-helper metadata without resolving any additional artwork.
Rebuild it after the source change; earlier parser receipts remain pinned to their
earlier source revisions and bundles are preserved.

Generate the reference report from a new exported bundle:

```powershell
.venv\Scripts\python.exe -m tools.southperry_render_dependencies --bundle artifacts\southperry-dependency-source --output artifacts\southperry-render-dependencies-new.json
```

Local evidence: `artifacts/southperry-render-dependencies.json` lists every referenced
entry and placement, source hashes and copied archives. Source bundle:
`artifacts/southperry-dependency-source/`. Run results and timing:
`artifacts/southperry-render-dependency-verification.md`.

The report does not admit a new corpus map, render a full map, establish native build
identity or independent world positions, unlock input, or resolve the six reserve
bundles and 105 unidentified recording rows.
