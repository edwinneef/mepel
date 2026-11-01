# Saved navigation recording inventory — 2026-11-01

Metadata inventory of all 88 immediate directories in `data/recordings`; source recordings unchanged. Machine-readable report: `artifacts/research-roadmap/p7/recording-inventory.json`.

55 directories have decisions.jsonl; 33 do not. There are 1,429 missing frame references across historical logs (references, not unique images). These incomplete logs cannot be treated as complete action-aligned footage. Parsing found no malformed decision records.

Only session-1793536812861464100-clip contains non-null navigation_step payloads: 27 steps with all 117 referenced frames present. This is the already accepted successful route, not an additional failure sample. session-1793536119944800100-clip has the navigation_step key but no non-null steps; key presence alone is insufficient.

The remaining recordings may support visual annotations, but cannot supply recorded Navigator pre/post state retroactively. This inventory does not independently label contact, landing, localization error, grip failure, trajectory failure or input delivery. No missing runtime state was inferred from pictures or newer code. Existing successful replay evidence remains valid; no replay or gameplay was rerun.

P7 remains partial: no additional action-aligned real failure sequence was found. Independent visual landing labels and effect attribution remain unestablished. P4 reserved-map corpus and P9 combat acceptance are unchanged. A separate visual annotation pass can assess historical image sequences, but cannot close the missing-state requirement. Any new live batch still requires explicit authorization and operator presence; do not induce failures solely to fill coverage.


## Visual assessment

Inspected overview samples every ten frames from complete clips session-1793536119944800100 and session-1793536812861464100. The earlier clip shows the player on the upper small platform at sampled times; another character crossing the scene is not the tracked player. Sparse samples do not exclude motion between them.

Inspected every frame 97–116 of the successful clip, plus full-size frame116. Frames97–108 show an upper-platform pose;109–112 show downward transition;113–116 show a stable lower-platform pose. These are visual observations, not collision-state truth. Exact contact onset and world-coordinate geometry remain unknown. Detail crops truncate the lower platform, so the final pose was checked against the full-size source image.

Saved frame hashes, annotation method, confidence and exclusions in `artifacts/research-roadmap/p7/visual-landing-labels.json`; overview/detail sheets are alongside it. Labels were assigned from images rather than detector coordinates, but the successful outcome was already known: this is neither blind annotation nor a held-out accuracy result. Do not promote it to physical proof or close p7. No runtime changes, deployment or gameplay occurred. Pillow was unavailable; sheets were produced with existing OpenCV without installing dependencies.


## Prospective evaluation reservation

`artifacts/research-roadmap/p7/landing-evaluation-split.json` pins all referenced image hashes and decision-log hashes for38 complete clips.50 incomplete/empty directories are excluded. Connected components combine clips within30 minutes by recording identifier or sharing an exact image hash; seven groups remain. The lexicographically first eligible group hash reserves six clips;32 clips remain development data. Groups containing the two known-reviewed clips are excluded from reservation. No outcome or prediction was used to choose the reserved group.

Validation passed:38 clips assigned once, with zero identical image hashes across splits. Hashing/grouping/check runtime was11.35 seconds, excluding investigation and reporting. Timestamp proximity and exact hashes do not prove independence of long sessions or near-duplicate images.

This freezes a prospective split, not a historically blind test. Earlier exposure is unknown. The manifest specifies raw-image-only annotation, ambiguous/occluded labels, frozen labels before prediction disclosure, and no tuning on reserved data. An annotator must not receive decisions, predicted locations or run outcomes. No reserved footage was visually inspected during selection. Physical contact and world XY remain unknown; visual support-pose labels cannot substitute for them.

The six reserved clips have no recorded Navigator step payloads. Thus even completed visual annotations cannot satisfy action-aligned failure replay. P7 requires additional independent labels and compatible real failure evidence; p4 still lacks reserved-map data and p9 still needs authorized supervised combat. No gameplay or runtime change was made. A broad artifact-name listing encountered access-denied historical test directories; they were not retried or accessed, and the split uses only the readable recording inventory and source frames.

## Reserved visual labels — 2026-11-01

A separate annotation agent reviewed all 720 reserved raw frames in sequence without reading predictions, decision logs or reported outcomes. Display sheets used opaque R1–R6 IDs; source paths and the split manifest were available for provenance, so this is not a fully metadata-blind study. Historical exposure remains unknown.

Frozen labels: `artifacts/research-roadmap/p7/reserved-visual-labels.json` (SHA256 `6cabba51c16874582a46ff0e2926bd0db5dba22af8572d10d5ccc0b8b9ffd22b`). Inspection sheets: `artifacts/research-roadmap/p7/reserved-annotation/`. The single annotator classified 664 stationary ladder frames as ambiguous under the grass-support taxonomy, 28 descending frames as transition, and 28 as lower grass-support pose. Transition includes ladder descent, not an airborne-physics claim. No upper-support or occluded frames were labeled. Physical contact and world XY remain unknown throughout; no second-rater agreement was measured.

Validation: all 720 raw image hashes match the frozen split (0.95s); label coverage, uniqueness, hashes, interval counts and unknown-contact fields pass (0.012s). Report: `artifacts/research-roadmap/p7/reserved-label-validation.json`. These command times exclude visual review, startup and reporting. Labels were frozen before prediction disclosure; no reserved-data tuning occurred.

This completes the available reserved visual annotation step, not p7 acceptance. These clips still lack Navigator step payloads; pictures cannot recover action-aligned real failure states or causal input effects. P4 independent reserved-map XY data and p9 supervised combat acceptance also remain missing. No runtime change, deployment, engine restart or gameplay batch occurred.
