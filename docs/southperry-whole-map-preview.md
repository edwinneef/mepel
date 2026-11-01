# Southperry whole-map scenery preview

The complete referenced scenery has been assembled offline at **4724 x 2222**
pixels, covering source bounds **(-652, -1505) to (4072, 717)**. It contains all
**607 tiles, 115 object placements and 7 background placements** in the saved map
layout. No map traversal was needed to obtain the rest of the scene.

Open `artifacts/southperry-whole-map/preview/overview.png` for the composite or
`foreground.png` for transparent terrain/objects at their source coordinates.
`overview-small.png` is the reduced overview. `placements.json` records every
foreground placement, its selected picture, layer, depth, position and flip.

## Copies and picture closure

The newly copied installed files are:

- `Map/Obj/_Canvas/_Canvas_000.wz` (61,310,435 bytes).
- `Map/Obj/_Canvas/_Canvas.ini`.
- `Map/Obj/_Canvas/_Canvas.wz`.

They were copied into a new folder alongside new copies of the nine previously
verified artwork/index files. The combined 12-file set totals **98,820,221 bytes**.
`artifacts/southperry-whole-map/asset-receipt.json` records source-before,
copied-file and source-after SHA-256 values; all match. Prior copies are retained.

The reader opened only the four named copied artwork payloads in Obj, Tile, Back
and Obj/_Canvas. It parsed the eight referenced source images and three linked
Obj/_Canvas images. All **33 links resolve to inline pictures in these copies**;
all **72 required branches** yielded their pictures. No further artwork payload
was needed for these references. The report exports **74 pictures**, including
three frames of one animated ship detail. The preview selects frame zero.

All 74 PNGs were independently reconstructed from their extracted BGRA4444
payloads: **6,754,504 pixels, zero differences** against MapleLib's decoder.
As in the earlier extraction, this validates pixel content; it does not certify
a zlib footer/checksum for streams that do not contain one.

The reader is separate GPL-3.0-only diagnostic tooling, linked to the already
present MapleLib checkout at commit
`04570d43cd90e1b42f613226dd0be22ce58abd1c`. Build restoration used an empty local
feed and the existing package cache only. The pinned reader receipt records
source, binary/dependency and license hashes. No downloads occurred.

## Reproduction

Build a new reader output with the existing local checkout and cache:

```powershell
.\.venv\Scripts\python.exe -m tools.southperry_scenery.build --maplelib-root <existing-pinned-MapleLib-checkout> --package-cache <existing-cache> --output <new-reader-folder>
dotnet <new-reader-folder>/SouthperryScenery.dll artifacts/southperry-whole-map/assets artifacts/southperry-whole-map/request.json <new-picture-folder>
.\.venv\Scripts\python.exe -m tools.render_southperry_scenery --raw artifacts/southperry-dependency-source/raw.json --pictures <new-picture-folder> --receipt artifacts/southperry-whole-map/asset-receipt.json --output <new-preview-folder>
```

The final verified build is in `artifacts/southperry-whole-map/extractor-final/`;
its receipt is `parser-receipt.json`. Extracted pictures and link tracing are in
`pictures-final/pictures.json`. Render checks, source/output pins and
limitations are in `preview/summary.json`. `verification.json` records final
source preservation and repeated-output checks.

Three extractions produced identical metadata, PNGs and compressed payloads.
The repeated renderer produced identical foreground/composite pixels. Six
focused tests and Ruff pass; the tests cover clipping/alpha, flipped origins,
initial-frame selection, depth ordering, independent decode corruption and
picture-path containment. All 12 source and copied files remain unchanged.

## Limits

This is a full scenery preview, not a running client. Backgrounds are drawn as a
static world-zero snapshot; client parallax, scrolling and animation timing are
not reproduced. Initial object-animation frames are used. NPCs, monsters,
reactors, portal effects, client-generated rope/ladder drawings, HUD and player
are outside the requested scenery export. Decorative characters that are part
of a scenery object remain in that object's picture.

Layer/depth composition is diagnostic. The earlier screenshots cover only part
of Southperry, so unseen regions are not claimed as independently pixel-verified
against the client. Complete picture availability does not verify actor origin,
collision, navigation routes, client build identity, or any reserved map.

No game control, live capture, engine restart, saved-map modification or
reserved-map inspection was performed. This work does not unlock gameplay input.
