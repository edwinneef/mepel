---
last_mapped_commit: 9370ad5f14eb90e5ce4aeae8e7b52bb5b14ac14d
last_mapped_at: 2026-10-24
---
# Coding Conventions

**Analysis Date:** 2026-10-24

## Naming Patterns

**Files:**
- Python modules are lowercase single words or snake_case: `src/maplebot/runtime.py`, `src/maplebot/input_timing.py`, `src/maplebot/autopotter.py`.
- Tests mirror modules as `tests/test_<module>.py`: `tests/test_keyboard.py` covers `src/maplebot/keyboard.py`. There is no test file for `geometry.py`, `windows.py`, `debugger.py` or `__main__.py`; their behavior is exercised indirectly or through the tools.
- Offline/manual scripts live in `tools/` as `<name>_smoke.py` or `<name>_benchmark.py`: `tools/input_smoke.py`, `tools/synthetic_benchmark.py`.
- Static assets: `src/maplebot/static/index.html` (the debugger UI, packaged via `pyproject.toml` `package-data`).

**Functions:**
- snake_case. Private helpers are prefixed with a single underscore: `Application._command`, `Application._run`, `KeyboardController._send`, `KeyboardController._release_keys`, `KeyboardController._watch`.
- Public command entry points are verb-like and short: `start`, `stop`, `close`, `execute`, `execute_sequence`, `step`, `request`, `snapshot`.
- Module-level factory/helper functions are plain names: `png()` in `src/maplebot/runtime.py`, `annotate()` and `nametag_parts()` in `src/maplebot/perception.py`, `import_catalog()` and `fetch_public_image()` in `src/maplebot/catalog.py`.
- Test helper factories are short names: `entity()` and `scene()` in `tests/test_decision.py`.

**Variables:**
- snake_case throughout. Short local names are common for geometry and image math (`x`, `dx`, `dy`, `w`, `h`, `frame`, `alpha`).
- Constants are UPPER_SNAKE_CASE at module scope: `API`, `STARTER_IDS` in `src/maplebot/catalog.py`, `ACTIONS`, `KEYS` in `src/maplebot/keyboard.py`.
- Dataclass/enum fields use the same snake_case as their config keys: `RecordingConfig.buffer_seconds` maps to `[recording] buffer_seconds` in `config.toml`.

**Types:**
- Classes are PascalCase: `Application`, `KeyboardController`, `TemplateDetector`, `SessionRecorder`, `CaptureConfig`.
- Configuration and value objects are `@dataclass(frozen=True)`: every class in `src/maplebot/config.py`, `Rect` in `src/maplebot/geometry.py`, `Detection`/`Observation` in `src/maplebot/perception.py`, `Action`/`Decision` in `src/maplebot/decision.py`.
- Enumerations use `enum.StrEnum`: `State` in `src/maplebot/decision.py` (`IDLE`, `SEARCH`, `APPROACH`, `ATTACK`, `VERIFY`).
- Protocols are used for swappable collaborators: `Detector` in `src/maplebot/perception.py`, `InputBackend` in `src/maplebot/keyboard.py`.

## Code Style

**Formatting:**
- No formatter is configured (no Black/Ruff-format section). Code is consistently formatted in Ruff/Black style: double quotes, trailing commas on multi-line calls, wrapped at 100 columns.
- Line length is 100: `[tool.ruff] line-length = 100` in `pyproject.toml`.

**Linting:**
- Ruff is the only linter. Config is in `pyproject.toml`:
  ```toml
  [tool.ruff.lint]
  select = ["E", "F", "I", "UP", "B"]
  ```
- Rule families: pycodestyle errors (E), pyflakes (F), isort (I), pyupgrade (UP), flake8-bugbear (B). The current tree passes `ruff check`.
- Run: `.venv/Scripts/python.exe -m ruff check src tests`. The README (`README.md` "Tests and reproducible checks") also lints `tools`; include `tools` when touching scripts in `tools/`.

**Modern Python (requires Python >= 3.12, `pyproject.toml`):**
- PEP 604 unions: `int | None`, `Detection | None` (`src/maplebot/config.py`, `src/maplebot/decision.py`).
- Built-in generics: `dict[str, Any]`, `tuple[int, int]`, `list[...]`, `deque[dict[str, Any]]`, `queue.Queue[tuple[str, dict, Future]]`. Do not import `typing.Optional`, `Union`, `Dict`, `List`.
- `StrEnum` from `enum`, `tomllib` for config parsing.
- No `from __future__ import annotations` is used; forward references are quoted: `-> "Config"` in `src/maplebot/config.py`, `-> "Rect"` in `src/maplebot/geometry.py`.

## Import Organization

**Order (observed in every module, enforced by Ruff `I`):**
1. Standard library (`import json`, `import threading`, `from dataclasses import dataclass`)
2. Third-party (`import cv2`, `import numpy as np`, `import mss`)
3. First-party relative imports within the package (`from .config import Config`)

Example from `src/maplebot/runtime.py`:

```python
import json
import queue
import threading

import cv2

from .autopotter import PotionMonitor
from .capture import Calibration, Capture, Image
from .config import Config
```

Tests import the package by absolute name, with `pytest` first:

```python
import pytest

from maplebot.config import AgentConfig
from maplebot.decision import Agent, State
```

**Path Aliases:**
- None. Use relative imports (`.module`) inside `src/maplebot/` and absolute `maplebot.*` imports in `tests/` and `tools/`.

**Lazy imports:**
- `src/maplebot/__main__.py` imports heavy modules only inside the branch that needs them (`from .catalog import ...`, `from .replay import run_replay`, `import cv2`, `import mss` for `doctor`, `from .runtime import Application` for `debug`). Keep this pattern for CLI subcommands so `maplebot catalog` does not load the capture stack.

## Error Handling

The codebase uses three distinct error styles. Follow the one that matches the situation.

**1. Validation of configuration and user input: `ValueError` with an operator-readable message.**
- `Config.load` in `src/maplebot/config.py` checks ranges after construction:
  ```python
  if not 1 <= config.capture.fps <= 60:
      raise ValueError("capture.fps must be between 1 and 60")
  ```
- Dataclass `__post_init__` validates invariants and raises `ValueError`: `Rect.__post_init__` in `src/maplebot/geometry.py`, `TimingConfig.__post_init__` and `RecordingConfig.__post_init__` in `src/maplebot/config.py`. Use `math.isfinite(value)` alongside the range check for floats.
- Message style: name the config key in dotted form (`timing.reaction_min_seconds`, `recording.buffer_seconds`), state the bound.

**2. Safety/state gating: `RuntimeError` with a message telling the operator what to do.**
- Input and capture gates raise `RuntimeError`: `"Capture-only session: keyboard output is locked"` in `src/maplebot/keyboard.py`, `"Replay cannot enable real keyboard input"`, `"Target not safe/focused, or emergency key held"`.
- Capture guards in `src/maplebot/capture.py` use the same style: `"Window title, size, or DPI changed; recalibrate the Game view"`.
- Messages describe the required operator action ("recalibrate", "Return to live", "verify the Game view"). Keep that phrasing.

**3. Boundary handling: broad `except Exception` only at worker/thread/request edges, and always convert to a visible state.**
- The worker loop in `src/maplebot/runtime.py` (`Application._run`) catches exceptions, calls `self._stop(str(error))`, resets the status dict to `IDLE` with the reason, and keeps running.
- The keyboard watchdog (`KeyboardController._watch`) catches everything and calls `self.stop(f"Input watchdog failure: {error}")`, so it never dies silently.
- `KeyboardController._execute_sequence` stops input before re-raising: `except ValueError: self.stop(...); raise` and `except Exception: self.stop("Keyboard backend failure"); raise`. Always release keys in a `finally` block.
- The HTTP handler in `src/maplebot/debugger.py` converts any exception into `400` with `{"error": str(error)}`.
- Command futures propagate errors to the caller: `future.set_exception(error)` in `Application._drain_commands`.

**Specific exception types** are used when the failure is expected and local:
- `except (OSError, ValueError, KeyError) as error:` with a `warnings.append(...)` for per-item catalog failures (`src/maplebot/catalog.py`). Continue processing other items and report in the result.
- `except (KeyError, ValueError):` mapping to HTTP 404 in `src/maplebot/debugger.py`.
- `except cv2.error:` around OpenCV calls in `src/maplebot/perception.py`.
- `except OSError:` for best-effort file cleanup in `src/maplebot/recorder.py`.
- Convert library timeouts to domain errors: `except TimeoutError: raise RuntimeError("Debugger command timed out; input stopped") from None` in `src/maplebot/runtime.py`.

**Do not** swallow errors silently. The only silent `except` is in `src/maplebot/__main__.py` for `KeyboardInterrupt` during the debugger loop.

**Atomic file writes:** write to a temporary sibling then `replace`, and keep a timestamped `.bak` of the previous content before overwriting (`src/maplebot/catalog.py`, `src/maplebot/capture.py` `Calibration.save`):

```python
temporary = manifest_path.with_suffix(".tmp")
temporary.write_text(content, encoding="utf-8")
temporary.replace(manifest_path)
```

## Logging

**Framework:** None. The `logging` module is not used.

**Patterns:**
- CLI output goes to stdout via `print(json.dumps(result, indent=2))` in `src/maplebot/__main__.py`. Results of `catalog`, `replay`, and `doctor` are JSON documents.
- Runtime status is not logged. It is published as a status dict on `Application.status` and exposed through `GET /api/status` in `src/maplebot/debugger.py`. Add new operator-visible state to that dict, not to `print`.
- Per-decision and per-event history is persisted by the recorder as JSONL (`decisions.jsonl`, `events.jsonl` written by `src/maplebot/recorder.py`).
- Use `app.note(reason)` (in `src/maplebot/runtime.py`) for human-visible notes when a status change should be remembered.

## Comments

**When to Comment:**
- Comments are sparse and explain *why*, not *what`. Examples in the tree:
  - `# Release now, without waiting for a capture/detector operation to finish.` (`src/maplebot/runtime.py`)
  - `# Frozen frames are immutable and bounded; serialize access with worker.` (`src/maplebot/debugger.py`)
  - `# Always face target once at close range, even if previous movement was opposite.` (`src/maplebot/decision.py`)
- Module docstrings state the module's role and its safety boundary, e.g. `"""Deterministic decisions, with no capture or keyboard dependencies."""` (`src/maplebot/decision.py`), `"""Setup-only public sprite import. Live detection reads the local PNG catalog only."""` (`src/maplebot/catalog.py`).

**JSDoc/TSDoc (docstrings):**
- Use triple-double-quoted docstrings on modules and on classes/functions whose contract is non-obvious. Single-line when possible; multi-line with a summary line when needed:
  ```python
  def execute_sequence(self, holds: Sequence[KeyHold]) -> str:
      """Execute one bounded plan. Movement/jump/attack may overlap; opposites may not."""
  ```
- No Sphinx/Google-style `Args:` sections are used. Describe parameters in prose only when needed.

## Function Design

**Size:** Most functions are small helpers. Large orchestration exists and is accepted in `src/maplebot/runtime.py` (618 lines) and `src/maplebot/perception.py` (781 lines). Do not add new large methods to these two files. Put new logic in a focused module and call it from `runtime.py`.

**Parameters:**
- Config objects are passed whole (`Agent(config.agent, config.perception.confidence)`, `KeyboardController(backend, config.input, ...)`), not individual values.
- Injectable collaborators are keyword-only when optional: `Application(config, *, input_backend=None, capture_only=False)` in `src/maplebot/runtime.py`, `import_catalog(templates, ids, *, fetch=...)` in `src/maplebot/catalog.py`.
- Time is passed in explicitly for decision logic (`Agent.step(observation, now)`) so tests can drive it deterministically. Use `time.perf_counter()` only in runtime code.
- Callables are injected for side-effecting checks: `KeyboardController(backend, config, safe_fn, emergency_fn, ...)`.

**Return Values:**
- Dataclasses for structured results: `Decision`, `Action`, `Detection`, `Observation`, `Calibration`.
- Plain `dict` for JSON-serialized payloads (`status`, `import_catalog` result, `run_replay` result). Build them with literal keys.
- Action results from the keyboard controller are short strings: `"blocked: duration"`, `"sequence completed"`, `"release"`. Preserve those strings; the runtime and tests match on them.

## Module Design

**Exports:** No `__all__` is defined. Modules expose their public classes and functions directly. Names starting with `_` are internal.

**Barrel Files:**
- `src/maplebot/__init__.py` is empty (one line). Do not add re-exports. Import from the concrete module (`from maplebot.decision import Agent`).

**Module boundaries (observed, keep them):**
- `decision.py` has no capture or keyboard imports; it imports only `config` and `perception` types.
- `perception.py` reads templates and screenshots only; it does not send input.
- `keyboard.py` owns all key output; no other module calls `Win32Input.send`.
- `runtime.py` is the single orchestrator and owns the worker thread and command queue.
- `windows.py` wraps Win32 APIs; `capture.py` wraps `mss` and calibration.

**Threading conventions:**
- Shared mutable state is guarded by `threading.Lock` (`self.lock`, `self.controller.lock`). Access `self.status` and `self.latest` under `with self.lock:`.
- Cross-thread operations go through `queue.Queue` of `(name, payload, Future)` tuples. Callers await the `Future`; the worker thread executes the command.
- Use `threading.Event` for stop/close signals (`self.closed`, `self.stopped`) and `event.wait(timeout)` instead of `time.sleep` in loops that must stop promptly.
- Threads are created `daemon=True` and named (`name="capture"`, `name="debugger"`).

## Other Patterns

**Configuration:**
- All tunables live in `config.toml` and are mirrored by a frozen dataclass in `src/maplebot/config.py`. To add a setting: add the field with a default to the dataclass, add the validation in `__post_init__` or `Config.load`, and add the key to `config.toml`.
- Unknown TOML sections are ignored by `Config.load`; keys are passed as `**raw.get(name, {})`, so an unknown key raises `TypeError` at load time. Keep `config.toml` in sync with the dataclasses.

**Private data:**
- Runtime data goes under `config.capture.data_dir` (default `data/`) and is gitignored, as are `artifacts/` and `.venv/` (`.gitignore`).
- Do not commit captured screenshots, calibration files, or sprite caches. The catalog stores public reference images with an attribution field in `manifest.json` (`src/maplebot/catalog.py`).

**Safety defaults:**
- Input is off by default. The debugger starts with `--capture-only` unless `run.ps1 -EnableGameplayInput` is passed (`run.ps1`, `src/maplebot/__main__.py`). New features that can send input must check `self.replay`, `self.enabled`, `self.stopped`, and the safety callback before sending, as `KeyboardController._execute_sequence` does.

---

*Convention analysis: 2026-10-24*
