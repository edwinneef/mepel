# Spawn metadata

Sprite assets and map populations are independent. `catalog --max-level` downloads
sprites only. `legacy-map-import` explicitly refreshes the old Dream map cache.

## Bulk Classic coverage (OSMS)

`python -m maplebot osms-import --dry-run` downloads the publisher's map and monster
JSON at the verified commit and reports covered, empty, and blocked maps without
writing files. Run without `--dry-run` to install the immutable local revision.
Use `--commit <full-lowercase-40-character-SHA>` to explicitly import another revision;
there is no automatic refresh or runtime network request.

The default commit is `17dc5dc14cc1d1f05152362c1bbcffa068e8dc81` from
https://github.com/ohmi69/osms_datamine_dashboard (Public Release). Its 336 map
records yield 335 named maps; one unnamed record is reported and excluded.
IDs are padded to nine digits. Only titles and species are retained; terrain,
spawn coordinates and routes are not imported. The provenance SHA256 covers the
raw maps JSON, a zero byte, and the raw monsters JSON, in that order.

Select `spawn_source = "osms-classic"` and the full commit as `spawn_revision`
in `[perception]` while the engine is stopped, then restart through
`tools/restart_engine.ps1`, preserving session input capability. Import alone
does not activate the revision or modify sprites. Existing revisions remain intact.

Species map by exact sprite name, including multiple source IDs with the same name.
Missing sprites block only maps requiring them; same-title candidates require the
complete union. Valid empty maps select no catalog monsters. An unsupported map
or incomplete coverage never falls back to the full catalog. Recognizing a map
with missing coverage discards any held previous map selection.

With the installed catalog on 2026-10-28, 294 maps have complete coverage (125 are
empty); 41 named maps need sprites. Metadata coverage does not establish native
gameplay behavior or client compatibility for every map. Middle Forest III's
eight species match the previously reviewed record.

Rollback: stop the engine, restore the configuration backed up before activation,
and restart in the same session mode. The previous `meowdb-classic/20261028-iii`
revision remains available; imported OSMS data can remain inactive on disk.

### Missing OSMS sprites

`python -m maplebot osms-sprites --dry-run` finds missing sprite names used by
maps in the selected OSMS revision and validates its standing, movement and flight
animations. Run without `--dry-run` to install. It preserves existing catalog
entries and image bytes, backs up the manifest, then activates additions with an
atomic manifest replacement. Failed downloads or validation do not change the
manifest. Repeating a completed import adds nothing.

OSMS frames use `osms-` filenames and reserved negative asset IDs
(`-1000000000 - source ID`), with provider, revision, URLs and hashes per entry.
WebP decoding requires a row-shaped byte buffer. Identical frame images retain
each distinct species label, so shared Super/Ultra art remains available when
either name is selected by its map. Source names are exact, not guessed aliases.

Restart through `tools/restart_engine.ps1` to load the additions, preserving
session input capability and leaving gameplay Off. To roll back these sprites,
stop the engine and restore the backed-up manifest; extra unlisted PNG files
remain inactive and need not be deleted. Installation evidence and the original
manifest are under `artifacts/osms-sprites-install-20261028/`.
The installation adds 142 labeled frames for 19 names from 35 animations (137
frames before shared-name duplication). All 335 named maps then have sprite
coverage, including 125 empty maps. This is asset/loader coverage, not proof of
native recognition or combat on every map. Existing Middle Forest III replay
still yields 17 accepted matches across six frames with 130 variants.

## Reviewed single-map import

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
