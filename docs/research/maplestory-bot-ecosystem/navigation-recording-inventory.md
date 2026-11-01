# Saved navigation recording inventory — 2026-11-01

Metadata inventory of all 88 immediate directories in `data/recordings`; source recordings unchanged. Machine-readable report: `artifacts/research-roadmap/p7/recording-inventory.json`.

55 directories have decisions.jsonl; 33 do not. There are 1,429 missing frame references across historical logs (references, not unique images). These incomplete logs cannot be treated as complete action-aligned footage. Parsing found no malformed decision records.

Only session-1793536812861464100-clip contains non-null navigation_step payloads: 27 steps with all 117 referenced frames present. This is the already accepted successful route, not an additional failure sample. session-1793536119944800100-clip has the navigation_step key but no non-null steps; key presence alone is insufficient.

The remaining recordings may support visual annotations, but cannot supply recorded Navigator pre/post state retroactively. This inventory does not independently label contact, landing, localization error, grip failure, trajectory failure or input delivery. No missing runtime state was inferred from pictures or newer code. Existing successful replay evidence remains valid; no replay or gameplay was rerun.

P7 remains partial: no additional action-aligned real failure sequence was found. Independent visual landing labels and effect attribution remain unestablished. P4 reserved-map corpus and P9 combat acceptance are unchanged. A separate visual annotation pass can assess historical image sequences, but cannot close the missing-state requirement. Any new live batch still requires explicit authorization and operator presence; do not induce failures solely to fill coverage.
