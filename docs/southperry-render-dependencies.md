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

## Installed artwork indexes checked, 2026-11-01

The operator subsequently authorized installed artwork **index/header reads only**.
The following physical files are now confirmed under
`C:\Nexon\Library\maplestorycw\appdata\Data\Map`:

- `Tile\Tile_000.wz` (1,332,173 bytes): `tile_whiteMarble.img`.
- `Obj\Obj_000.wz` (16,290,735 bytes): all five required object image records.
- `Back\Back_000.wz` (19,886,518 bytes): both required background image records.

Their eight Southperry image entries were found without parsing image properties.
The three associated category `.ini` files each declare `LastWzIndex|0`.
This resolves the main container filenames; none has been copied or decoded yet.

These associated bitmap containers also exist and each has a `_Canvas.ini` declaring
`LastWzIndex|0`:

- `Obj\_Canvas\_Canvas_000.wz` (61,310,435 bytes): its directory contains
  `obj_acc1.img`, `obj_connect.img` and `obj_signboard.img`.
- `Tile\_Canvas\_Canvas_000.wz` (200,748 bytes): no directory entry named
  `tile_whiteMarble.img`.
- `Back\_Canvas\_Canvas_000.wz` (18,819,698 bytes): no directory entries named
  `back_grassySoil.img` or `back_portTown.img`.

The last two facts do not prove the containers unnecessary. Artwork may be inline or
link to differently named shared records. Even matching names in the object bitmap
container do not prove which Southperry property uses them. **The complete required
bitmap file list remains unverified** until the referenced artwork properties and their
links are traced. That exceeds the current indexes-only authorization.

Evidence: `artifacts/southperry-installed-artwork-indexes.json`; repeated index report
is byte-identical. Reads used pinned MapleLib BMS/779 archive conventions, never native
build identification, executable/key discovery, `ParseImage`, or pixel decoding.
No `Map/Map` archive or reserved-map image was opened in this index run. File size and
modification timestamp stayed unchanged during each read. Whole-archive SHA-256 values
were not computed because this operation was limited to indexes/headers.

The opt-in diagnostic command is separate from copied-asset export:

```powershell
dotnet artifacts\classic-assets-parser-indexes-pinned\ClassicAssetExtractor.dll --artwork-indexes C:\Nexon\Library\maplestorycw\appdata\Data\Map artifacts\southperry-installed-artwork-indexes-new.json
```

It reads only the fixed `Tile`, `Obj`, `Back` categories and their `_Canvas` indexes;
it does not perform a whole-installation search. The output must be new. All C# sources
are now included in parser build/source receipts. Run details:
`artifacts/southperry-installed-index-verification.md`.

Recommended next action: copy the **three confirmed main archives** and their category
index metadata to a new folder with SHA-256 receipts, then inspect only the eight
referenced Southperry artwork entries offline. That will identify which bitmap archive
copies are actually necessary before copying the larger bitmap containers.
