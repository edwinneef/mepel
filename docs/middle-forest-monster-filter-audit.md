# Middle Forest III monster-filter audit

Audited 2026-10-28 against source commit `4495abe`. Runtime code and saved data
were left unchanged. No gameplay input, recording, restart or download was used.

## Finding

The corrected title reader identifies **Kerning City Middle Forest III**, but its
cached species list excludes five species present in the saved screenshots.
The same installed detector recognizes those sprites when the species filter is
removed in an isolated offline comparison.

The cached `Victoria Road` / `Kerning City Middle Forest III` entry has map ID
`103030200` and monster IDs `2110200`, `2220100`, `9400621`, `9400622`. Its installed
names are Blue Mushroom, Horny Mushroom, Strange Blue Mushroom and Strange Horny
Mushroom. These references remain available; the audit does not establish that
they can never spawn in this client.

The omitted screenshot-backed species are:

- Blue Snail: five matches across five screenshots.
- Red Snail: six matches across four screenshots.
- Pig: three matches across three screenshots.
- Slime: one match in one screenshot.
- Green Mushroom: two matches across two screenshots.

These are **17 detections across overlapping screenshots**, not 17 unique monsters
or a complete spawn census. Scores range from `0.998935` to `1.0`; they are template
similarity scores, not calibrated probabilities. The labeled Black Pig pet is not
among these detections; the Pig matches are the separate pink sprites.

## Comparison

Inputs were the saved reference image
`data/areas/frames/a7e36007ab12f4911e38df41fe36a1c7832938e7bff9409618ab08efda71c39f.png`
and the five `362bc0749cdc41efb045ecc06b483633-miss-*.png` teaching evidence frames.

For each image, the production `TemplateDetector.detect` ran twice with the same
installed templates and configured `0.90` confidence threshold. Tracking, learned
sprite snapshots and camera history were reset before each run so both searched
the full frame. Only the in-memory allowed-species set changed:

- Production III species: zero accepted monsters in all six screenshots;
  44 active template variants, including retained manual examples.
- All installed species: 17 accepted matches in five of six screenshots.
  The reference screenshot yielded no accepted monsters in either run.

The title reader and thresholds were not bypassed or relaxed in the running
engine. Searching all species was an offline diagnostic, not a deployment change.
The combined replay, including template initialization, took 60.39 seconds.

Evidence and the repeatable probe are retained under
`artifacts/middle-forest-monster-audit-20261028/`: `comparison.json`, `audit.py`,
`protected-before.json`. The comparison stores frame hashes, boxes, templates,
scores, below-threshold candidates and per-run timings. Visual inspection of the
saved frames agrees with the accepted species and box locations.

## Cause and scoped follow-up

`src/maplebot/catalog.py:import_map_catalog` imports public map/species metadata;
it does not learn this client's spawn list from screenshots.
`src/maplebot/map_filter.py:MapFilter.match` selects that cached list by title.
`src/maplebot/perception.py:TemplateDetector.detect` excludes catalog templates
whose species are not in the selected list. Thus an installed Slime or Snail
reference cannot be recognized here even when its pixels match exactly.

## Source investigation: cause established

Follow-up investigation on 2026-10-28 confirms a **dataset compatibility bug**:
the bot uses Dream MS's spawn metadata as authoritative for the operator's
Classic-style client. Reusing matching sprite artwork does not establish that
two games use the same map population.

The chain is:

1. `src/maplebot/catalog.py:16` hardcodes
   `https://api.dreamms.gg/api/GMS/latest` for both sprite assets and map metadata.
   Dream MS's own API documentation says requests use `gms/latest` to access
   **Dream MS game assets**. This is not a generic Classic World dataset or an
   automatic selection of the operator's client version.
   [Provider documentation](https://api.dreamms.gg/).
2. `import_map_catalog` copies `detail.mobs[*].id` from that provider into
   `cache/maps/<id>.json` and `catalog/maps.json`. It preserves only the map's
   ID, street, title and monster list; no client-compatibility declaration is
   checked. The cache is keyed by map ID, without a separate dataset identity.
3. The imported entry for `103030200` is named Victoria Road / Kerning City
   Middle Forest III and lists the four mushroom IDs above. A fresh read of
   [the provider's map endpoint](https://api.dreamms.gg/api/GMS/latest/map/103030200)
   returns exactly those same four IDs. The local cache and merged map entry
   agree with it. **The importer did not corrupt the list, and refreshing this
   provider would not resolve the mismatch.**
4. `MapFilter.match` identifies the map from its street and title. Neither that
   match nor the monster-name lookup verifies that the cached spawn metadata
   belongs to the same game dataset as the pixels being observed. This makes
   the incompatible provider entry govern the screenshot detector.

The project's accepted context in `docs/bowman-range-research.md:7-10` is a custom
v83 client/project implementing Classic features, with Classic World as the
intended baseline. The published Classic World counterpart has a different ID,
`010003052`, and these eight species:

- Snail, Blue Snail and Red Snail.
- Slime and Pig.
- Orange Mushroom, Ribbon Pig and Green Mushroom.

All five screenshot-confirmed species are included in that list.
[NiaMeowDB's Classic map entry](https://meowdb.com/msclassic/maps/010003052).
The differing IDs corroborate that these are separate datasets; the actual
custom client's internal map ID and exact server data revision were not read.
The eight-species list is a published baseline, not a new native spawn census.

This rules out the earlier OCR confusion, a stale local list, a corrupted import,
missing installed templates and confidence thresholds as the cause of these
demonstrated filter omissions. The confirmed integration error is choosing
server-specific spawn metadata using a shared human-readable map name, without
checking dataset compatibility. The precise history of Dream MS's customized
map population is outside what these sources establish.

Evidence is retained in `artifacts/middle-forest-import-cause-20261028/`:
`dream-live-map-103030200.json`, `classic-map-page.html`, `source-comparison.json`
and protected-file hashes. Requests only read public sources; runtime code and
filter data remain unchanged.

## Revised follow-up

The earlier five-species supplement recommendation covers only the observed
frames. The source finding supports separating reusable sprite references from
version-specific map spawn metadata, selecting a Classic-compatible source
explicitly and resolving its monster identifiers to the installed sprite names.
A data migration should preserve the imported cache, saved maps, drafts, existing
input safeguards and unrelated work, then replay the saved screenshots.

No filter-data change is authorized by this cause-report task. Plan that source
selection and identifier mapping before applying replacements or supplements.

Do not enable full-catalog live searching or request another recording for this
fix. P4's missing return route is a separate evidence gap and remains unchanged.
