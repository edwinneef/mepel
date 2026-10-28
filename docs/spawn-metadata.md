# Spawn metadata

Sprite assets and map populations are independent. `catalog --max-level` downloads
sprites only. `legacy-map-import` explicitly refreshes the old Dream map cache.

Import a reviewed Classic revision from the repository root:

```powershell
.\.venv\Scripts\python.exe -m maplebot spawn-import docs/spawn-metadata/classic-iii.json --dry-run
.\.venv\Scripts\python.exe -m maplebot spawn-import docs/spawn-metadata/classic-iii.json
```

Revisions are immutable and stored under `data/spawn-metadata/<source>/<revision>.json`.
A changed record requires a new revision; previous revisions remain available.
The import does not select the dataset or change sprites, settings or saved maps.

Select `spawn_source = "meowdb-classic"` and `spawn_revision = "20261028-iii"`
in `[perception]` in `config.toml`. Stop the engine before changing selection and
restart with `tools/restart_engine.ps1`, preserving the session's input capability.
Selection is read at startup; it cannot switch during a running session. Template
reload stops input and constructs a fresh filter, discarding OCR and taught sets.

This revision covers only Victoria Road / Kerning City Middle Forest III, public
reference ID `010003052`. This is not a claim about the native client's map ID.
Its eight species are Snail, Blue Snail, Red Snail, Slime, Pig, Orange Mushroom,
Ribbon Pig and Green Mushroom. The JSON records the public URL, source-page hash,
date and explicit species crosswalk. Exact sprite names resolve all installed IDs
for that species; Classic species IDs are never treated as sprite IDs.

Unknown maps, missing metadata and missing sprite coverage pause catalog searches.
Manual examples remain available. There is no fallback to Dream populations or
the complete catalog. Status reports `spawn_source`, `spawn_revision`, `spawn_error`
and `active_map`; existing blocker text explains failures.

Rollback: stop the engine, restore the previous config from
`artifacts/classic-spawn-install-20261028/config.toml.before`, and restart in the
same session mode. Alternatively explicitly select `legacy-dream` with an empty
revision. Leave the imported Classic revision in place; it is inactive.

Installation evidence is in `artifacts/classic-spawn-install-20261028/`.
Six saved frames recover 17 accepted matches at confidence 0.90 using 130 variants,
with approximately 0.27–0.30 seconds per detection on this run. These are matches
across images, not 17 unique monsters or evidence of native combat behavior.
