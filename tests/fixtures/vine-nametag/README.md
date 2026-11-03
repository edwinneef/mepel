# Vine-obscured name tag

Unscaled, unmodified pixel crops from the saved Tree Dungeon recording listed in
`provenance.json`: clear frame 839, obscured frame 841, recovered frame 845.
The crop is x=560, y=390, width=300, height=150. The original taught name template
and metadata are included. Source image hashes identify the originals; tests do
not need the recording directory or current user configuration.

The foreground vine reduces glyph overlap below 0.85. Without an independent
fresh sprite, the partial name cannot authorize input. A tracked sprite must
remain unconfirmed, and a later clear name cannot extend a queued action's
original 500 ms observation deadline.

This isolates recorded name pixels and safety gates. It does not reproduce the
entire mutable sprite catalog, prove live capture timing, or establish the cause
of the later Level 7 dropout for which no frames were saved.

## Frozen sprite ambiguity

`ambiguity/player` contains the two saved templates sufficient to reproduce the
candidate collision under the current matcher. Their source hashes are in
`provenance.json`; they are not a snapshot of the original runtime's learned poses.
Coordinates below are relative to the unchanged recorded crop.

| Saved template suffix | Confidence | Body x,y | Body size |
| --- | --- | --- | --- |
| 62ccb0dedb8244519644d6b70d29bc74 | 1.000000 | 155,45 | 44x64 |
| 6fa3fe9ed167464f898f0885336b3799 | 0.971711 | 175,17 | 44x64 |

The margin is 0.028289, below the unchanged 0.04 requirement, and body overlap is
below the 0.25 suppression threshold. These are different spatial hypotheses,
not identical duplicate detections. The second template is visibly an off-center
partial body, but that observation does not supply a general safe rule for
discarding it at runtime. The matching regions are different parts of the image.

The partial-name scorer returns zero: its required evidence across both halves
is missing. The 0.776557 full-name score alone is insufficient. Cached identity
for either the operator or another player must not break the candidate tie.

This evidence does not justify lowering margins, broadening duplicate suppression,
or choosing by proximity. A recognition improvement needs additional independent
current-frame evidence; no such discriminator is established by this fixture.
