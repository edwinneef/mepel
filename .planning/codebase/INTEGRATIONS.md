---
last_mapped_commit: 9370ad5f14eb90e5ce4aeae8e7b52bb5b14ac14d
last_mapped_at: 2026-10-24
---
# External Integrations

**Analysis Date:** 2026-10-24

## APIs & External Services

**Public sprite reference API (setup-only):**
- Dream MS image API - `https://api.dreamms.gg/api/GMS/latest`
  - Used for: downloading monster names (`{API}/mob/{id}/name`) and transparent stand/move animation frames (`{API}/mob/animated/{id}/{action}?format=png`) for the enemy catalog.
  - Implementation: `src/maplebot/catalog.py` (`API` constant, `fetch_public_image`, `import_catalog`) using `urllib.request.urlopen` with a 15-second timeout and a 2,000,000-byte response cap.
  - Trigger: only the explicit `python -m maplebot catalog` command (`src/maplebot/__main__.py`). Live play never calls it.
  - Auth: none. Request sends a custom `User-Agent: MapleExternalBot/0.1 public-reference catalog`.
  - Cache: downloads stored in `data/templates/catalog/cache/`; provenance (frame hashes, source URLs) in `data/templates/catalog/manifest.json`.
  - Scope limits (per `catalog.py` docstring and README): sprites only; map, stats, and spawn endpoints are never requested.

**Game client (no network integration):**
- MapleStory / MapleUnity Editor is interacted with only through screen pixels and Win32 window geometry. No network calls to the game, no memory access, no Unity APIs (README "Overview").
- `src/maplebot/windows.py` - Window lookup by title, client rect, DPI awareness.
- `src/maplebot/capture.py` - Screen capture through `mss`.
- `src/maplebot/keyboard.py` - Keyboard output via `user32.SendInput` (`Win32Input`), with virtual-key map (`left`, `right`, `ctrl`, `space`, `f8`, and others). Default backend, unlocked only outside capture-only mode.

## Data Storage

**Databases:**
- None. No database client, ORM, or SQL usage.

**File Storage:**
- Local filesystem only, relative to the working directory:
  - `data/templates/` - Player and enemy templates, catalog cache and manifest.
  - `data/recordings/session-*/` - `decisions.jsonl`, `events.jsonl`, PNG frame sequences. Written by `src/maplebot/recorder.py`.
  - `data/screenshots/` - Saved raw and annotated PNGs.
  - `data/autopotter.json` - HUD calibration (timestamped backups on replacement).
  - `artifacts/` - Replay, synthetic, and catalog benchmark output (`src/maplebot/replay.py`, `tools/*.py`).
- Retention: `[recording]` in `config.toml` - `max_age_days = 7`, `max_total_mb = 2048`, enforced by `src/maplebot/recorder.py`.
- Formats: JSON / JSONL (`json` stdlib), PNG (`cv2`), APNG decoding (`cv2.imdecodeanimation`).

**Caching:**
- In-memory frame buffer for recording (`buffer_seconds = 10`, `max_queue_frames = 240` in `config.toml`), managed in `src/maplebot/recorder.py`.
- In-memory player sprite snapshots (reset on restart), per the README perception section.
- Catalog download cache on disk (see above).

## Authentication & Identity

**Auth Provider:**
- None for external services. The catalog API is anonymous.

**Local debugger access control:**
- Implementation: `src/maplebot/debugger.py`.
  - Binds to `127.0.0.1` only.
  - Host header must equal `127.0.0.1:<port>` or `localhost:<port>` (`allowed()`).
  - A per-process token is generated with `secrets.token_urlsafe(32)`, injected into the served HTML (`__TOKEN__` replacement), and required on POST requests as the `X-Debug-Token` header; mismatches return HTTP 403.
  - Response hardening: `X-Content-Type-Options: nosniff`.

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry or similar SDK.

**Logs:**
- Structured JSONL decision and event logs written to disk under `data/recordings/session-*/` (`decisions.jsonl`, `events.jsonl`).
- Console output via `print` in `src/maplebot/__main__.py` (startup banner showing debugger URL and input status).
- Browser debugger status endpoint `GET /api/status` (`src/maplebot/debugger.py`).

## CI/CD & Deployment

**Hosting:**
- Not hosted. Runs locally on the user's Windows machine.

**CI Pipeline:**
- None detected. No `.github/workflows/`, no pre-commit configuration. Verification is manual (README "Verification" commands: `pytest`, `doctor`, `tools/*.py`).

## Environment Configuration

**Required env vars:**
- None.

**Secrets location:**
- No secrets are used. The debugger token is ephemeral, in memory only.

**Required local setup:**
- Python 3.12 available as `py -3.12` (for `install.ps1`).
- Windows desktop session with the MapleStory / MapleUnity Editor window open (for live capture and input).
- Internet access only when running `python -m maplebot catalog`.

## Webhooks & Callbacks

**Incoming:**
- Local HTTP endpoints on `127.0.0.1:8765` (`src/maplebot/debugger.py`), not reachable from other hosts:
  - `GET /` - Debugger HTML.
  - `GET /api/status` - Status JSON.
  - `GET /frame.png` - Latest captured frame.
  - `POST /api/<action>` - Control actions dispatched to `app.request(...)`, requires `X-Debug-Token`.

**Outgoing:**
- Only the catalog fetches to `api.dreamms.gg` during explicit setup (see above). No webhooks.

---

*Integration audit: 2026-10-24*
