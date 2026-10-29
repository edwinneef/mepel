# Classic geometry exports

Use the accessible MeowDB map page's floor overlay as the Classic geometry source.
For map 000000042, `https://meowdb.com/_data/map-terrain/000000042.json`
contains 196 foothold segments and ten ladder/rope tuples (schema version 2).
All 206 segments were checked against the page's SVG. The original minimap is
200 by 101 pixels; its world origin is (299, 1045), magnification 4. Registration
against the saved game reference places it at approximately (2.02, 0.03) inside
the 204 by 101 captured canvas. Do not stretch the picture to the captured canvas.

The local export combines `id`, `name`, `terrain` (the untouched compact JSON),
`miniMap` (base64 PNG `canvas`, `centerX`, `centerY`, `magnification`), and `portals`
(with world x/y and type). Keep source URLs in the export for provenance. Obtain
these through permitted access; do not retry a denied request through another client.

Preview with the engine's existing import command:

```powershell
.venv/Scripts/python.exe -m maplebot import-map <area> --map-id 42 --meowdb-source <export.json> --dry-run
```

Inspect alignment with the saved reference before importing. Stop the engine using
`tools/restart_engine.ps1 -StopOnly`, then repeat without `--dry-run`. AreaStore
backs up the prior area revision. The reference and walk calibration are retained.
The import records the provider and SHA-256 of the complete export; it does not
overwrite DreamMS caches. Restart through the standard script after validation.

MeowDB is the better candidate for this Classic server: this layout matches the
saved scene; the examined legacy 40002 layout does not. This does not establish
coverage or accuracy for every future map. Compact MeowDB geometry omits foothold
IDs and adjacency; the adapter joins only unique, exactly touching floor endpoints
and rejects unsupported collision modifiers. DreamMS supplies explicit adjacency
and remains the default for existing legacy maps. Check each map's version,
minimap, portals and scene alignment before choosing either source. No automatic
provider fallback or gameplay acceptance follows from an import.
