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

The cache/client coverage mismatch is demonstrated. Its upstream cause and the
complete native spawn list are not established by these screenshots.

Recommended separate implementation: add a local supplement for this exact map
containing the five screenshot-backed species, preserving the imported cache and
existing III species. Keep other maps, confidence thresholds, same-platform and
input gates unchanged. Verify with these saved frames before installation.

Do not enable full-catalog live searching or request another recording for this
fix. P4's missing return route is a separate evidence gap and remains unchanged.
