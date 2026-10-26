# Saved route-gap diagnosis — 2026-10-26

Diagnosis and offline candidate only. The active map, recoverable draft, samples,
calibration and running capture-only process were not changed.

## Latest draft

The latest log (`1792976752344706900.jsonl`) reproduces three platforms, one rope,
four links, and the two missing-return warnings: Left ledge (P1) and Left rope
(R1) cannot reach Ground floor (P3) through its recorded directed graph.

The only recognized-surface transition rejected by the six-second link limit is
P1 → P3: t=117214.183770 to 117300.327816, **86.144 seconds**, with **187 unreadable
position checks** between those endpoints. The intervening saved samples do not
establish a continuous return journey. Raising the link timeout would invent a
connection across lost evidence. The reader fix cannot recover coordinates from
log rows that have no marker or corresponding retained image.

The last recognized platform is P1, but the session does not simply end there:
its final three `ground` samples are at approximately (1686.6, 181.0). They have no
horizontal span, so they do not form a platform under the 24-pixel minimum-width
rule. In total seven ground/slope samples are unassigned. A stationary reading
does not establish a usable ledge or a return route.

## Earlier evidence can supply return paths

The earlier log (`1792974870718327400.jsonl`) has 1,105 samples; the latest has
508. Both reproduce their stored platform/rope coordinates with the current
saved calibration. This validates their coordinate alignment for an offline
merge. Each log retains its original timestamps; no link crosses sessions.

Replaying their combined 1,613 samples produces a candidate with **16 platforms,
one rope and 33 directed links**. It preserves the draft identities/names for
Left ledge P1, Ground floor P3 and Left rope R1. Both missing-return warnings
clear in this candidate graph.

The shortest candidate return from Left ledge uses these separately observed
moves in the earlier session. This is a graph assembled from recorded moves,
not one uninterrupted recorded journey:

| From → to (candidate IDs) | Seconds | Unreadable checks during move |
| --- | ---: | ---: |
| Left ledge P1 → Left ledge 3 P7 | 1.246 | 0 |
| Left ledge 3 P7 → Left ledge 2 P4 | 0.773 | 0 |
| Left ledge 2 P4 → Right ledge P5 | 2.921 | 0 |
| Right ledge P5 → Right ledge 5 P12 | 0.896 | 0 |
| Right ledge 5 P12 → Right ledge 6 P14 | 0.639 | 0 |
| Right ledge 6 P14 → Ground floor P3 | 1.128 | 0 |
| Left rope R1 → Ground floor P3 | 0.187 | 0 |

The latest session supplies the width needed to recognize the left ledge as a
platform. That lets previously unassigned earlier samples on the same ledge
contribute their recorded outbound moves. The earlier session also supplies the
rope's lower extent and its floor transition. This is more than adding links:
the rope extends from y=481 to y=581, and the main floor expands from approximately
x=100.9–1806.2 to x=85.0–1885.9. Candidate IDs P4 and higher are not IDs from the
old log or active map; the report records endpoints and provenance explicitly.

## Remaining limits

- One fragment remains unreachable from the main floor: candidate Ground floor 2
  (P16), x=-10.6–37.3, y=581. It has an outbound rope link but no recorded inbound
  path. Do not silently join it to the main floor or remove the warning.
- The old log's saved warning metadata identifies its upper P1 as home. Current
  replay correctly chooses the lowest, widest floor (old-session P16). Recompute
  warnings rather than copying that historical problem list.
- These are the existing teacher's sample-derived classifications. They do not
  prove platform contact, validate a gameplay route executor, or authorize p6.
- The candidate changes substantially more geometry than the three-platform
  draft. It needs a reversible draft merge and review before any map activation.
  No additional recording is needed to prepare that review.

## Artifacts and reproduction

- `artifacts/route-gap-diagnosis/verified-report.json`: both sessions, transition
  gaps, return-path witnesses, unassigned samples and source SHA-256s.
- `artifacts/route-gap-diagnosis/candidate-geometry.json`: the offline candidate;
  it has not been written into `data/areas` or activated.

```powershell
.venv\Scripts\python.exe tools\teaching_route_diagnosis.py `
  --output artifacts\route-gap-diagnosis\NEW_REPORT.json
```

The command refuses an existing output and verifies unchanged source hashes.
It also refuses mismatched coordinates/calibration, overlapping session times,
ambiguous surface matching, or links without same-session timing witnesses.
Repeated diagnosis is deterministic. The eight map-teacher/identity tests and
Ruff pass. Original draft samples and all pre-existing untracked work remain intact.
