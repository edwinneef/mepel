# Existing potion evidence audit - 28 October 2026

Audit completed without another test, replay, gameplay input, computer use,
restart or settings change. Existing recordings and artifacts were read; the
running engine was queried with GET only.

## What is already accepted

HP and MP potion controls remain confirmed. The saved Insert/Delete bindings
and both HUD fingerprints match the current calibrated references. Preserve
these confirmations; this audit supplies no reason to repeat accepted probes.
`artifacts/probe-confirmation-migration-1792887373926106700.json` also records
historical operator acceptance of potion probes, but belongs to an older
1024-pixel layout and is not fresh recovery evidence for the current warrior.

## What the saved native runs establish

- MP: a live-potions run completed Delete, ticket 1/generation 20, at
  `1793119907.035137`. The last earlier saved frame is `00008515.png` in
  `session-1793119903300541800-clip`; it shows MP 211/465. The first later frame
  `00008754.png` in `session-1793119972952218000-clip` shows 353/465, but was
  captured **42.405 seconds after completion**. Recovery is visible across the
  interval; the missing window prevents assigning it solely to that press.
- HP: ticket 2/generation 27 completed Insert. The last earlier frame
  `00018631.png` in `session-1793122834921318900-clip` shows HP 310/586. The
  next clip, `session-1793122897654601600-clip`, starts with `00018820.png` at
  HP 321/586, approximately 31 seconds after completion. This is not a paired
  immediate recovery observation.
- HP again: ticket 3/generation 77 completed Insert at `1793123594.9802723`.
  Frames `00021228.png` and `00021230.png` in
  `session-1793123595420938900-clip` show HP 268/586 then 257/586. The final
  picture was captured only **0.003 seconds after the completion event**;
  the preceding HUD reading was uncertain and the run then stopped on window
  occlusion. No recovery is established; this does not demonstrate potion failure.
- Broadsword combat requested no potion because both bars stayed above 50%.
  Its accepted hit and MP cost provide no potion-recovery evidence.

These are older **live-potions** runs, not evidence that a potion restored a
resource while the warrior's combat policy was active. The saved native files
contain no `observed_bar_gain` event. That absence does not invalidate the saved
operator confirmations.

## Source evidence and limits

`runtime._start_sustain` enables calibrated, confirmed resources with nonzero
thresholds. The combat arbiter prioritizes HP, then MP, then combat, and waits
for an in-flight potion key. This is source evidence; no automated tests were run.
`runtime` deliberately labels a completed live potion key's effect unconfirmed.
Its fresh-bar-gain confirmation path applies to dedicated potion probes.

`input_sent: true` means the key completed. `action_outcome` and `last_action`
can retain the same old ticket across many subsequent rows, including capture
mode; those rows are not additional presses or evidence of recovery.

The audit examined 17 recording directories (13 with decision logs) and the
saved JSON/JSONL artifacts. Machine findings, source hashes and cropped existing
HUD pictures are in `artifacts/potion-evidence-audit-20261028/`. No original
recording, calibration or confirmation file was changed.

## Result

Accepted controls and historical automatic key delivery are supported. A tightly
paired automatic HP/MP recovery observation during combat remains missing.
Keep that outcome pending rather than calling it passed or failed. Do not run
another test merely to close this report. The useful next improvement is passive
retention of frame-matched before/after potion evidence during ordinary use.
