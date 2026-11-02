# fh374 dark-frame regression crops

Source: `data/recordings/session-1793600951542391400-combat`.
These 220x210 crops retain the player, partial name, pet, terrain and chat
around the original recognition losses. `frames.json` records original frame
names, crop origins and capture clocks. Source recordings are untouched.

The player/name reference files are copies of the templates used by that run.
Tests seed identity with bright frame 1321, then require fresh matching in the
dark frames without lowering the production confidence threshold. Cold,
expired, ambiguous, displaced and differently named identities remain refused.
The original full-frame replay remains a separate check of camera and tracking.
