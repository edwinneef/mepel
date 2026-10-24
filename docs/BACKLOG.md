# Backlog

## Autopotter

Use HP/MP potions automatically when either bar drops below a configured threshold.

- Read HP and MP from the status bar in the screen capture. Nothing reads them yet, so this has to be built first.
- Config: separate HP and MP thresholds (percent), a potion key for each, and a minimum cooldown between presses.
- Send presses through `KeyboardController` so the existing safety checks, timing realism and `input.max_action_seconds` limits still apply.
- Potion use takes priority over combat actions, but must not interrupt a sequence that holds keys in an unsafe way.
- Stop and alert when bar readings are missing or don't change after a press (out of potions, wrong key, misread bar).
- Tests: bar-reading fixtures from recorded screenshots, plus threshold, cooldown and priority logic against a fake input backend.
