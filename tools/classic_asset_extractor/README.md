# Copied-asset Southperry diagnostic exporter

This separate local console tool requires Windows, .NET SDK 10, a clean local
`lastbattle/MapleLib` checkout at `04570d43cd90e1b42f613226dd0be22ce58abd1c`,
and an already populated NuGet cache for that checkout. It never downloads dependencies.
The bot and UI do not depend on it.

MapleLib is GPL-3.0; `Program.cs` is GPL-3.0-only. Its linked Spine 2.1.25 dependency
has the separate **Spine Runtimes Software License, Version 2.2**, including personal/internal
use and redistribution conditions. Read both checkout license files before building.
The build receipt records their SHA-256 values. No third-party code, binaries, game
archives or recordings are redistributed here. This tool is for local diagnostics;
the receipt does not grant a distribution license.

From the project directory, build with explicit local paths:

```powershell
.venv\Scripts\python.exe tools\classic_asset_extractor\build.py --maplelib-root C:\copies\MapleLib --package-cache C:\copies\nuget-cache --output D:\diagnostics\classic-parser
```

Then run one offline export (both output directories must be new; their parent must exist):

```powershell
.venv\Scripts\python.exe tools\export_classic_assets.py --source-root C:\copies\assets --receipt C:\copies\asset-receipt.json --map-id 60 --output D:\diagnostics\southperry --extractor D:\diagnostics\classic-parser\ClassicAssetExtractor.dll
```

The receipt is an array of `{relative, original, copy, sha256, bytes}` records. `copy`
must be the absolute path under the explicit copied-assets root. `original` is provenance
only and is never opened. Include the four required archives named in `REQUIRED` in
`export_classic_assets.py` and any existing pinned companion copies. All copies are hashed
before staging and after parsing. A private staging tree prevents parser link resolution
from reaching unreceipted source files. Junctions, symlinks, traversal, saved-data and
installed/source destinations, overwrite, unsupported formats and unresolved links fail
closed. Only Southperry is supported; reserve maps are never extracted.

Limits: 32 receipt rows, 64 MiB total input, 30 second parser deadline, 16 output files,
16 MiB published output, one million pixels per canvas, 100,000 properties/directory
visits, property depth 32 and link depth 16. These are parser/size limits, not an OS sandbox
for arbitrary executable code. Use only the locally built, hash-pinned extractor.

`raw.json` preserves original section properties, IDs, modifiers and links.
`geometry.json` adds normalized IDs without dropping original values. PNGs and original
compressed payloads accompany the manifest. Python independently inflates BGRA4444
and compares every pixel with MapleLib's PNG. These archives lack a final deflate end
marker; exact packed lengths and receipt hashes are checked, **not a zlib footer checksum**.
Identical pinned inputs and parser yield deterministic bundle bytes.

The recorded-footage checker is separate: `tools/check_classic_footage.py --bundle BUNDLE
--reference-root COPIED_REFERENCE --output NEW_REPORT.json`. It consumes only copied,
hash-pinned frames and the prior cache, and writes a diagnostic JSON report.
Nine frames cover 210x138 at 1:1, leaving 85 right columns unobserved. Marker overlap
exceptions remain visible. Recorded UI placement does not establish a WZ canvas origin.
The canvas origin remains null; the declared user origin is (6,6).

This bundle remains evaluation-only: no full-world render, independent actor placements,
native build identity, XY/contact/grip proof or fixture admission. Six reserve bundles and
105 unnamed recording rows remain unresolved. It does not import saved maps, change
alignment-corpus requirements, alter gameplay gates or authorize capture/live testing.

Southperry artwork placement records are also retained in `raw.json` for dependency
tracing. See `docs/southperry-render-dependencies.md` for the exact referenced images
and the missing physical-archive indexes; these records do not contain the artwork.
