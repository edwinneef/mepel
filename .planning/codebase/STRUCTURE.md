---
last_mapped_commit: 9370ad5f14eb90e5ce4aeae8e7b52bb5b14ac14d
last_mapped_at: 2026-10-24
---
# Codebase Structure

**Analysis Date:** 2026-10-24

## Directory Layout

```
maple-external-bot/
├── src/
│   └── maplebot/              # Installed Python package (all application code)
│       ├── __main__.py        # CLI entry: doctor, debug, replay, catalog
│       ├── runtime.py         # Application orchestrator and worker loop
│       ├── debugger.py        # Localhost HTTP control surface
│       ├── static/index.html  # Debugger UI (token placeholder __TOKEN__)
│       ├── capture.py         # Calibration, Capture (mss)
│       ├── windows.py         # Win32 window enumeration, focus, key state
│       ├── geometry.py        # Rect
│       ├── perception.py      # TemplateDetector, CameraTracker, NameTag, annotate
│       ├── autopotter.py      # PotionMonitor (HP/MP bar readings)
│       ├── catalog.py         # Public sprite import (offline, one-time)
│       ├── decision.py        # Agent FSM, State, Action, Decision
│       ├── keyboard.py        # InputBackend, Win32Input, DisabledInput, KeyboardController
│       ├── input_timing.py    # TimingPlanner, KeyHold, InputSchedule
│       ├── recorder.py        # SessionRecorder (JSONL + frames, background writer)
│       ├── replay.py          # Offline run_replay over saved frames
│       └── config.py          # Config dataclasses and TOML loader
├── tests/                     # pytest suite, one test_<module>.py per module
├── tools/                     # Standalone smoke/benchmark scripts (not imported)
├── docs/                      # BACKLOG.md, VERIFICATION.md (dated evidence)
├── config.toml                # Runtime tunables (capture, perception, agent, input, timing, recording)
├── pyproject.toml             # Build (setuptools, src layout), deps, ruff and pytest config
├── install.ps1                # Creates .venv (Python 3.12) and installs editable with [dev]
├── run.ps1                    # Launches the debugger; capture-only unless -EnableGameplayInput
├── README.md                  # Setup, calibration and operating procedure
├── .gitignore                 # Excludes .venv/, __pycache__/, data/, artifacts/, caches
│
├── data/                      # RUNTIME ONLY (gitignored): templates, calibration, recordings
├── artifacts/                 # SCRATCH OUTPUT (gitignored): replay and benchmark results
├── .venv/                     # Local virtualenv (gitignored)
├── .planning/codebase/        # GSD codebase maps (this document lives here)
├── .claude/, .codex/          # Agent tooling installs (not application code)
└── .git/
```

## Directory Purposes

**`src/maplebot/`:**
- Purpose: The whole application. Flat package, no sub-packages.
- Contains: 16 Python modules and one static HTML file (about 5,000 lines in total across `src/`, `tests/`, `tools/`).
- Key files: `runtime.py` (orchestration), `perception.py` (largest module, 781 lines), `decision.py` (policy), `keyboard.py` (input).

**`src/maplebot/static/`:**
- Purpose: Browser UI served by the debugger.
- Contains: `index.html` only. Included as package data by `pyproject.toml` (`[tool.setuptools.package-data] maplebot = ["static/*.html"]`).
- Key files: `src/maplebot/static/index.html`

**`tests/`:**
- Purpose: Unit and integration tests for each module.
- Contains: `test_autopotter.py`, `test_capture.py`, `test_catalog.py`, `test_decision.py`, `test_input_timing.py`, `test_keyboard.py`, `test_perception.py`, `test_recorder.py`, `test_replay.py`, `test_runtime.py`. No `conftest.py` is tracked.
- Key files: `tests/test_runtime.py` (262 lines, orchestration), `tests/test_perception.py` (352 lines).
- Test discovery: `[tool.pytest.ini_options] testpaths = ["tests"]` in `pyproject.toml`.

**`tools/`:**
- Purpose: Manual verification scripts that exercise real Windows capture, input, debugger or synthetic benchmarks. Not on `sys.path` as a package.
- Contains: `capture_smoke.py`, `debugger_smoke.py`, `input_smoke.py`, `synthetic_benchmark.py`, `benchmark_catalog.py`.
- Key files: `tools/input_smoke.py` (sends real keys to a temporary Tk window; verify before running).

**`docs/`:**
- Purpose: Project notes. Not generated.
- Contains: `BACKLOG.md` (planned work by area, starting with an Autopotter section) and `VERIFICATION.md` (dated, measured evidence, with artifact references under `artifacts/`).

**`data/` (runtime, gitignored):**
- Purpose: Created at startup by `Application.__init__` (`Path(config.capture.data_dir).resolve().mkdir`).
- Layout produced by the code:
  - `data/templates/` player and monster examples (`TemplateDetector` reads `self.data / "templates"`)
  - `data/templates/catalog/` public-sprite catalog plus `manifest.json` (written by `catalog.py`)
  - `data/autopotter.json` HUD bar calibration (`PotionMonitor`)
  - `data/recordings/session-*/` `decisions.jsonl`, `events.jsonl`, frame PNGs (`SessionRecorder`)
  - Calibration JSON (`Calibration.save`), with timestamped backups when replaced
- Generated: Yes. Committed: No.

**`artifacts/` (scratch, gitignored):**
- Purpose: Replay output (`replay --output` default `artifacts/replay`), smoke captures, and synthetic benchmark results referenced in `docs/VERIFICATION.md`.
- Generated: Yes. Committed: No.

## Key File Locations

**Entry Points:**
- `src/maplebot/__main__.py`: CLI dispatch and the debugger run loop.
- `pyproject.toml`: `[project.scripts] maplebot = "maplebot.__main__:main"`.
- `run.ps1`, `install.ps1`: Windows launchers.

**Configuration:**
- `config.toml`: Runtime settings. Sections: `[capture]`, `[debugger]`, `[perception]`, `[agent]`, `[input]`, `[timing]`, `[recording]`. Parsed by `src/maplebot/config.py`.
- `pyproject.toml`: Dependencies (`mss`, `numpy`, `opencv-python-headless`), dev extras (`pytest`, `ruff`), ruff rules (`E, F, I, UP, B`, line length 100).
- `src/maplebot/config.py`: Dataclass definitions and defaults. Adding a setting means adding a field here and a section in `config.toml`.

**Core Logic:**
- `src/maplebot/runtime.py`: Worker loop, command dispatch, input gate.
- `src/maplebot/perception.py`: Detection pipeline.
- `src/maplebot/decision.py`: FSM policy.
- `src/maplebot/keyboard.py`: Key output and emergency release.
- `src/maplebot/capture.py`: Calibration and screen grabs.

**Testing:**
- `tests/`: All automated tests. Run with `.venv\Scripts\python.exe -m pytest` (project dev extra).

## Naming Conventions

**Files:**
- Modules are `snake_case.py` nouns or nouns-plus-noun: `input_timing.py`, `autopotter.py`, `runtime.py`.
- Tests mirror modules: `src/maplebot/<name>.py` -> `tests/test_<name>.py`. No module lacks a test file except `__init__.py`, `__main__.py`, `geometry.py`, `debugger.py`, `windows.py` and `config.py`, which are covered indirectly.
- Tools are `<purpose>_<kind>.py`: `capture_smoke.py`, `input_smoke.py`, `synthetic_benchmark.py`.
- Docs are UPPERCASE: `BACKLOG.md`, `VERIFICATION.md`.

**Classes:**
- PascalCase nouns: `Application`, `TemplateDetector`, `KeyboardController`, `SessionRecorder`. Protocols are named by role (`Detector`, `InputBackend`). Frozen value types use `@dataclass(frozen=True)`: `Action`, `Decision`, `Rect`, `KeyHold`.

**Functions and methods:**
- `snake_case`. Private helpers are prefixed with `_` (`_run`, `_process`, `_stop`, `_input_safe`, `_drain_commands`). Module-level utility functions are unprefixed (`png`, `annotate`, `nametag_parts`, `fill_pixels`).

**Config keys:**
- `snake_case` TOML keys mapped directly to dataclass fields. Command names used by the debugger (`autopotter_calibrate`, `reload_templates`) match `Application._command` branch names and the `POST /api/<name>` path.

**Constants:**
- `UPPER_SNAKE` module-level (`KEYS`, `ACTIONS`, `STARTER_IDS`, `State` members).

## Where to Add New Code

**New detection capability (for example a new object type or HUD element):**
- Implementation: `src/maplebot/perception.py` (extend `TemplateDetector` or add a helper). Keep it free of Win32 and input calls.
- Config fields: `src/maplebot/config.py` (`PerceptionConfig`) and `config.toml` under `[perception]`.
- Tests: `tests/test_perception.py`.

**New decision rule or state:**
- Implementation: `src/maplebot/decision.py` (`State` enum and `Agent.step`).
- Tests: `tests/test_decision.py`. Add a replay case under `tests/test_replay.py` if the rule depends on saved frames.

**New debugger command (UI action):**
- Dispatch: add a branch in `Application._command` (`src/maplebot/runtime.py`).
- Stop-first handling: if it can change input or calibration, add the name to the set in `Application.request`.
- HTTP: no change needed in `src/maplebot/debugger.py` (generic `POST /api/<name>`).
- UI: `src/maplebot/static/index.html`.
- Tests: `tests/test_runtime.py`.

**New input action or key:**
- Key map: `KEYS` in `src/maplebot/keyboard.py`. Action names: `ACTIONS` in `src/maplebot/input_timing.py`.
- Config: `[input]` in `config.toml`, mapped by `InputConfig`.
- Tests: `tests/test_keyboard.py`, `tests/test_input_timing.py`.

**New window or capture source:**
- Implementation: `src/maplebot/windows.py` (enumeration) and `src/maplebot/capture.py` (grab/validation).
- Tests: `tests/test_capture.py`.

**New persisted artifact:**
- Path: under `self.data` (`Path(config.capture.data_dir)`), not hard-coded. Replay output goes to `artifacts/` only through `--output`.
- Recording format: `src/maplebot/recorder.py`.

**New offline tool or benchmark:**
- Location: `tools/<name>_smoke.py` or `tools/<name>_benchmark.py`. Do not import tool scripts from `src/maplebot/`.

**New test:**
- Location: `tests/test_<module>.py` matching the module. Tests do not require a live MapleStory window; inject `DisabledInput` or a fake `InputBackend` through `Application(config, input_backend=...)`.

**Utilities:**
- Geometry: `src/maplebot/geometry.py` (`Rect`). Shared image type alias is `Image` in `src/maplebot/capture.py`.

## Special Directories

**`src/maplebot.egg-info/`:**
- Purpose: Produced by `pip install -e .`. Gitignored (`*.egg-info/`).
- Generated: Yes. Committed: No.

**`src/maplebot/__pycache__/`, `tests/__pycache__/`:**
- Purpose: Bytecode caches. Gitignored.
- Generated: Yes. Committed: No.

**`.pytest_cache/`, `.ruff_cache/`:**
- Purpose: Tool caches at repository root. Gitignored.
- Generated: Yes. Committed: No.

**`data/`:**
- Purpose: Runtime state described above. Never delete or rewrite it from code outside the existing backup and prune paths. The README states that existing screenshots and templates are preserved.
- Generated: Yes. Committed: No.

**`artifacts/`:**
- Purpose: Scratch and evidence output. Gitignored.
- Generated: Yes. Committed: No.

---

*Structure analysis: 2026-10-24*
