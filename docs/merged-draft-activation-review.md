# Merged draft activation review — 2026-10-26

**Verdict: keep the draft in review. Fix the save-path blocker before activation.**
The active map remains revision 3. No real activation, recording, gameplay input,
draft edit or configuration change was performed during this review.

## Blocking finding: sloped coordinates cannot be saved

`MapTeacher._platforms` fits sloped endpoints with `numpy.polyfit`. Rounding those
values leaves `numpy.float64` objects in eight platforms: P4, P5, P6, P11, P12,
P14, P2 and P3. `profiles.number` deliberately accepts only finite built-in
`int`/`float` values. Consequently, the actual `LivePosition.save_teaching` →
`AreaStore.save_geometry` path rejects this merged draft with:

`Geometry must use finite native-pixel coordinates`

This was reproduced by calling `save_teaching(confirm_partial=True)` on a
temporary copy of the real area, draft and reference image. The copied active
map remained unchanged and the review proposal survived the failure.

JSON-normalizing a copy of the candidate makes profile validation pass. That
isolates the numeric-type problem; it does not repair the real draft or prove
the actual save path works. An exported JSON candidate can conceal this bug
because JSON decoding produces built-in numbers.

Recommended fix: emit built-in floats at the geometry-generation boundary,
retain strict finite-coordinate validation, and add a regression exercising
the actual save path with sloped geometry. Keep activation a separate action.

## P16 warning is justified

Ground floor 2 (P16) is a small, separate floor fragment at x=-10.6–37.3, y=581.
It has 14 ground samples at two distinct marker positions over approximately
2.58 seconds. Its padded width is 47.9 pixels. It is therefore supported by
samples rather than an invented platform.

Its only recorded graph edge is outbound, P16 → Left rope R1. There is no inbound
edge from the reachable map. The main floor starts at x=85, leaving 47.7 pixels
between the two learned extents. Same height and proximity do not establish a
walked connection. Keep the unreachable warning; do not bridge or delete it
silently to obtain a clean graph.

## Other review results

- The draft contains 1,613 samples, 16 platforms, one rope and 33 directed links.
- Left ledge P1 and Left rope R1 have return paths to Ground floor P3. Their
  supporting transitions and source sessions are documented in the route-gap
  diagnosis; no cross-session movement was invented.
- After numeric normalization only, structural validation passes: endpoints are
  in bounds, references and IDs validate, and links target existing surfaces.
  The unreachable P16 and unverified contact/movement warnings remain.
- There are no saved avoid/portal zones, so this candidate removes no zones.
- The boundary and some platforms extend beyond the single saved reference
  image. Partial reference coverage must stay explicit in the UI.
- Geometry review does not establish native platform contact or route execution;
  p6–p8 remain deferred.
- The original review backup and guarded restore tooling remain available.

Evidence: `artifacts/merged-draft-activation-review.json` records counts, affected
platforms, normalized validation warnings and active-map/draft SHA-256s.
