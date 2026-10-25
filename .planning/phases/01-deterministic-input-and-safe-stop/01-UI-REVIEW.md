# Phase 01 — UI Review

**Audited:** 2026-10-25
**Baseline:** Existing debugger, abstract six-pillar standards and operator-approved simplifications; no UI-SPEC exists.
**Method:** Inline Codex audit. Source plus live browser DOM, computed styles and interaction checks; no independent reviewer or raster screenshot is claimed.
**Interaction captures:** DOM checks only; no video or new gameplay recording.

## Pillar Scores

| Pillar | Score | Evidence |
|---|---|---|
| Copywriting | 3/4 | Explicit action names, recognition/reconnect explanations and exact stop reasons; Restart bot tooltip still describes the older manual confirmation flow. |
| Visuals | 3/4 | Game canvas is the main focal point, sidebar panels collapse, and advanced setup is hidden normally. Live DOM at 1280px has no horizontal overflow; raster appearance was not re-audited. |
| Color | 4/4 | Consistent dark green surfaces, light text and a distinct red alarm surface; severity is also expressed in text. |
| Typography | 3/4 | 14px body, 15px panel headings, 22px page heading and monospace diagnostic values; long JSON remains dense. |
| Spacing | 3/4 | Consistent 8/12/16/20/24px spacing, two-column desktop layout and single-column media rule. Mobile appearance is source-reviewed only. |
| Experience Design | 4/4 | Saved window/crop recognition, persistent confirmations, separate preview/live modes, disabled controls, direct alarm acknowledgement, copy fallback and safe restart states are implemented. |

**Overall: 20/24** (advisory source/DOM assessment).

## Priority Finding

IR-01: `src/maplebot/static/index.html` Restart bot title still says to reattach and confirm capture, although matching windows now reconnect and verify from recognition. Update this help copy in a future UI pass; no runtime behavior is affected.

## State and Interaction Evidence

- Game connection shows recognized/awaiting-recognition/no-window states. Manual confirmation remains under Advanced setup; old section numbers are absent.
- Alarm acknowledgement stays in the header, outside collapsed panels. Browser checks verified displayed incident IDs are sent with acknowledgement requests.
- Copy alarm uses clipboard output and a selection fallback. Repeated identical status updates preserve the selection.
- Collapsible panel preferences survive reload. Frame timing and binding/probe details remain available.
- Preview/live buttons invoke distinct commands; capture-only hides live input controls. Fake-boundary tests cover actual command gates and cancellation.
- Startup/restart remains input-disabled with nine saved probe confirmations restored. No live-potion or combat input was initiated for this review.

## Files Audited

`src/maplebot/static/index.html`, `src/maplebot/debugger.py`, related runtime status/command paths, debugger/runtime tests and the phase context/checkpoint. No third-party component registry is used.
