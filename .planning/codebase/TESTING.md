---
last_mapped_commit: 9370ad5f14eb90e5ce4aeae8e7b52bb5b14ac14d
last_mapped_at: 2026-10-24
---
# Testing Patterns

**Analysis Date:** 2026-10-24

## Test Framework

**Runner:**
- pytest (`pytest>=8,<10` in `[project.optional-dependencies] dev`, `pyproject.toml`). Last run used pytest 9.1.1 (cached bytecode name in `tests/__pycache__`).
- Config: `[tool.pytest.ini_options]` in `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  ```
- No `conftest.py` exists in the repository. Shared fixtures are defined per test module.

**Assertion Library:**
- Built-in `assert` statements. `pytest.raises(..., match=...)` for expected exceptions. `pytest.mark.parametrize` for table-driven cases.

**Linter for tests:**
- Ruff with the same rule set as source (`[tool.ruff.lint]` in `pyproject.toml`). Test files are linted by `ruff check src tests`.

**Run Commands:**

```powershell
.venv\Scripts\python.exe -m pytest -q                 # Run all tests (current: 124 passed in ~2.3 s)
.venv\Scripts\python.exe -m pytest tests/test_decision.py -q   # Single module
.venv\Scripts\python.exe -m pytest -q -k keyboard     # Filter by name
.venv\Scripts\python.exe -m ruff check src tests      # Lint (current: passes)
.venv\Scripts\ruff.exe check src tests tools          # Lint incl. tools (README form)
```

- Watch mode: not configured.
- Coverage: not configured (no `pytest-cov` in dev dependencies).

## Test File Organization

**Location:**
- All unit tests are in a top-level `tests/` directory, separate from `src/`. Do not co-locate tests with source.
- Scripts that need a real Windows desktop are not tests. They live in `tools/` and are not collected by pytest (`testpaths = ["tests"]`). Examples: `tools/input_smoke.py` (sends real `SendInput` events to its own Tk window), `tools/capture_smoke.py`, `tools/debugger_smoke.py`, `tools/synthetic_benchmark.py`, `tools/benchmark_catalog.py`.

**Naming:**
- Files: `tests/test_<module>.py` matching `src/maplebot/<module>.py`.
- Functions: `test_<behavior in words>` describing the observable behavior, not the method name:
  - `test_selects_nearest_same_platform_and_moves_in_short_steps` (`tests/test_decision.py`)
  - `test_watchdog_releases_immediately_on_focus_loss_or_emergency` (`tests/test_keyboard.py`)
  - `test_resize_dpi_and_title_invalidate_calibration` (`tests/test_capture.py`)
  - `test_session_logs_every_decision_but_saves_no_frames_without_incident` (`tests/test_recorder.py`)
- Helper factories: short nouns (`entity`, `scene` in `tests/test_decision.py`).

**Current module coverage (by file presence):**

| Source module | Test file |
|---|---|
| `src/maplebot/autopotter.py` | `tests/test_autopotter.py` |
| `src/maplebot/capture.py` | `tests/test_capture.py` |
| `src/maplebot/catalog.py` | `tests/test_catalog.py` |
| `src/maplebot/decision.py` | `tests/test_decision.py` |
| `src/maplebot/input_timing.py` | `tests/test_input_timing.py` |
| `src/maplebot/keyboard.py` | `tests/test_keyboard.py` |
| `src/maplebot/perception.py` | `tests/test_perception.py` |
| `src/maplebot/recorder.py` | `tests/test_recorder.py` |
| `src/maplebot/replay.py` | `tests/test_replay.py` |
| `src/maplebot/runtime.py` | `tests/test_runtime.py` |
| `src/maplebot/config.py` | none directly (validation exercised via other tests) |
| `src/maplebot/geometry.py` | none directly (`Rect` validation tested in `tests/test_capture.py`) |
| `src/maplebot/windows.py` | none (Win32; covered by `tools/` smoke scripts and fakes) |
| `src/maplebot/debugger.py` | none (HTTP surface untested) |
| `src/maplebot/__main__.py` | none |

**Structure:**

```
tests/
├── test_autopotter.py
├── test_capture.py
├── test_catalog.py
├── test_decision.py
├── test_input_timing.py
├── test_keyboard.py
├── test_perception.py
├── test_recorder.py
├── test_replay.py
└── test_runtime.py
```

## Test Structure

**Suite Organization:**
Flat module-level functions. No test classes are used. Group related behavior by file, not by `class`.

```python
import pytest

from maplebot.config import AgentConfig
from maplebot.decision import Agent, State
from maplebot.geometry import Rect
from maplebot.perception import Detection, Observation

def entity(kind="monster", x=200, y=100, confidence=0.99):
    return Detection(kind, Rect(x, y, 24, 28), confidence)

def scene(monsters=None, player=None, shift=(0, 0)):
    return Observation(
        player or entity("player", 100),
        monsters if monsters is not None else [entity()],
        camera_shift=shift,
    )

def test_selects_nearest_same_platform_and_moves_in_short_steps():
    agent = Agent(AgentConfig())
    agent.start()
    ...
```

**Patterns:**
- Build the system under test with real config dataclasses, overriding only what the test needs: `Config()` then `dataclasses.replace(config, capture=replace(config.capture, data_dir=str(tmp_path)))` (`tests/test_runtime.py`).
- Drive time explicitly: pass a numeric `now` into `Agent.step(observation, now)` and call the step multiple times to simulate a sequence (`tests/test_decision.py`).
- Use the "arrange, act, assert the state and the reason" shape. Decision tests assert on `decision.state`, `decision.action.kind`, and a substring of `decision.reason`:
  ```python
  assert result.state == State.SEARCH
  assert result.action.kind == "release"
  assert "kill unconfirmed" in result.reason
  ```
- Assert exact event sequences for input: `assert backend.events == [("right", True), ("right", False)]` (`tests/test_keyboard.py`).

**Setup/Teardown:**
- Fixtures use `yield` for teardown, closing resources afterward:
  ```python
  @pytest.fixture
  def recorder(tmp_path):
      config = RecordingConfig(buffer_seconds=1, keyframe_seconds=0, post_seconds=0.5)
      recorder = SessionRecorder(tmp_path, config, fps=4)
      yield recorder
      recorder.close()
  ```
  Same pattern in `tests/test_keyboard.py` (`controller` fixture, closes the controller) and `tests/test_runtime.py` (`app` fixture, calls `app.controller.close()`).
- Use `tmp_path` for every filesystem write. Count `tmp_path` usages before adding new fixtures: about 36 occurrences across the suite. Never write to the real `data/` directory from a test.

**Asynchronous/threaded assertions:**
- Use `threading.Event` in test doubles and `Event.wait(timeout)` to wait for a backend action (`Backend.down.wait(1)` in `tests/test_keyboard.py`).
- For background file writers, poll with a deadline instead of fixed sleeps. `flush()` in `tests/test_recorder.py` loops until `recorder.jobs.empty()` or 3 seconds elapse.

**Patterns:**
- Setup: construct fixtures with the real class and a fake collaborator.
- Teardown: close threads and handles in a fixture `yield`.
- Assertion: prefer exact equality on structured output; use `in` for reason substrings.

## Mocking

**Framework:** Hand-written fakes plus pytest `monkeypatch`. `unittest.mock` and `MagicMock` are not used.

**Patterns:**

Fake collaborator classes injected through constructor parameters (preferred):

```python
class Backend:
    def __init__(self):
        self.events = []
        self.down = threading.Event()
        self.released = threading.Event()

    def send(self, key, down):
        self.events.append((key, down))
        (self.down if down else self.released).set()
```

The `InputBackend` protocol in `src/maplebot/keyboard.py` is the injection seam for keys; `Application(config, input_backend=...)` in `src/maplebot/runtime.py` accepts it.

Module-level replacement with `monkeypatch.setattr` for Win32-facing classes:

```python
@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("maplebot.runtime.Windows", FakeWindows)
    monkeypatch.setattr("maplebot.runtime.Win32Input", Backend)
    ...
```

Patch the name where it is looked up (`maplebot.runtime.Windows`), not where it is defined.

Lambda-driven flags for safety callbacks:

```python
flags = {"focus": True, "emergency": False}
controller = KeyboardController(
    backend, InputConfig(), lambda: flags["focus"], lambda: flags["emergency"]
)
```

Mutate `flags` mid-test to simulate focus loss or the emergency key.

**What to Mock:**
- Win32 window and input APIs (`Windows`, `Win32Input`): use `FakeWindows` with a fixed `Window(...)` and a mutable `visible` flag (`tests/test_runtime.py`).
- Keyboard output: always replace `InputBackend` with a recording fake. No test may call `SendInput`.
- Network: the catalog accepts an injected `fetch` callable (`import_catalog(..., fetch=...)` in `src/maplebot/catalog.py`). Pass a fake that returns bytes; never hit `api.dreamms.gg` from a test.
- Clocks: pass `now` explicitly to decision logic; for `KeyboardController` tests use real short sleeps (≤ 0.25 s holds) and `Event` waits.

**What NOT to Mock:**
- `Rect`, `Detection`, `Observation`, and config dataclasses. Construct them directly; they are cheap and frozen.
- OpenCV image operations. Tests in `tests/test_perception.py` use real numpy arrays and real template matching.
- Filesystem. Use `tmp_path`, not mocks of `Path`.

## Fixtures and Factories

**Test Data:**
- Synthetic images are built with numpy in the test body. Use fixed-size zero arrays for the frame and fill regions explicitly:
  ```python
  app.image = np.zeros((768, 1024, 3), dtype=np.uint8)
  ```
- Detections and observations come from small factory helpers (`entity`, `scene`) defined at the top of the test module. Keep factories local to the test file; there is no shared `tests/factories.py`.
- Calibration fixtures: `Calibration("MapleUnity - Unity", 1024, 768, 96, Rect(0, 0, 1024, 768), True, True)` with the positional argument order from `src/maplebot/capture.py`.

**Location:**
- Helpers and fixtures are at the top of each test module. There is no `conftest.py` and no shared fixtures directory.
- Sample screenshots and recordings used for regression live under `data/` or `artifacts/` (gitignored); tests must not depend on them. Use `tools/synthetic_benchmark.py` for generated frames.

## Coverage

**Requirements:** None enforced. No coverage threshold, no `pytest-cov` dependency, no CI gate.

**View Coverage:**

```powershell
.venv\Scripts\python.exe -m pip install pytest-cov   # not in dev extras
.venv\Scripts\python.exe -m pytest -q --cov=maplebot --cov-report=term-missing
```

**Gaps (highest risk first):**
- `src/maplebot/debugger.py`: the HTTP token check, loopback Host check, and request-size limit have no tests. These guard against a browser-origin attack on the local debugger.
- `src/maplebot/__main__.py`: CLI argument wiring has no tests.
- `src/maplebot/windows.py`: Win32 enumeration and the `unobscured` check rely only on manual smoke runs.
- `src/maplebot/config.py`: range validation in `Config.load` is not tested in isolation. Add a test that loads a bad TOML fragment through `tmp_path` and asserts `ValueError`.

## Test Types

**Unit Tests (the bulk of `tests/`):**
- Pure logic: `decision.py`, `geometry.py`, `input_timing.py`, `catalog.py` manifest handling, `config.py` validation.
- Stateful components with injected fakes: `keyboard.py` (`KeyboardController`), `recorder.py` (`SessionRecorder`), `runtime.py` (`Application` command handling, driven without starting the worker thread).
- Image processing on synthetic numpy frames: `perception.py`, `autopotter.py`.

**Integration Tests:**
- No automated cross-process integration tests. `tests/test_runtime.py` exercises `Application` with the real `Agent`, `KeyboardController`, `SessionRecorder` and fake windows, which is the closest equivalent.
- Replay: `tests/test_replay.py` runs the offline replay path over recorded frames in `tmp_path`.

**Manual / Live Smoke (not pytest):**
- `tools/input_smoke.py`: sends real keystrokes to a temporary Tk window it creates, and verifies focus gating and key ordering.
- `tools/capture_smoke.py`, `tools/debugger_smoke.py`: exercise capture and the debugger against a running desktop.
- `tools/synthetic_benchmark.py`, `tools/benchmark_catalog.py`: throughput measurements on generated data.
- Live gameplay verification is documented as incomplete in `docs/VERIFICATION.md` and `README.md` (line ~192). Do not claim gameplay behavior is verified from unit tests alone.

**E2E Tests:**
- Not used. No browser or game-client automation.

## Common Patterns

**Parametrized cases for the same assertion across inputs:**

```python
@pytest.mark.parametrize("x,direction", [(0, "left"), (220, "right")])
def test_moves_towards_target(x, direction):
    ...
```

```python
@pytest.mark.parametrize("flag", ["focus", "emergency"])
def test_watchdog_releases_immediately_on_focus_loss_or_emergency(controller, flag):
    ...
```

Use `parametrize` when several inputs share one assertion. Use separate functions when setup differs.

**Async (threaded) Testing:**

```python
thread = threading.Thread(target=control.execute, args=(Action("left", 0.24),))
thread.start()
assert backend.down.wait(1)
flags[flag] = flag == "emergency"
```

Start the worker in a `threading.Thread`, wait on an `Event` set by the fake backend with a timeout, mutate the shared flag, then `thread.join()`. Always pass a timeout to `Event.wait` so a hang fails the test instead of blocking the run.

**Error Testing:**

```python
with pytest.raises(ValueError, match="Return to live"):
    app._command("probe", {"action": "attack"})
```

- Match on a stable substring of the message. The messages are operator-facing (see `CONVENTIONS.md` error section), so matching a distinctive phrase is intentional.
- For invalid geometry or config, assert the exception type only when the message is incidental: `with pytest.raises(ValueError): Rect(0, 0, 0, 10)` (`tests/test_capture.py`).

**Invariant-style tests for safety:**
- Every input-related test must prove that no key is sent when a gate is closed. Assert `backend.events == []` after the blocked path (`test_emergency_during_countdown_latches_and_never_sends_input`, `test_uncertain_detection_cancels_live_mode_without_key_down` in `tests/test_runtime.py`).
- Assert that held keys are released: `assert not control.held` after a short press.

**File-persistence testing:**

```python
calibration.save(path)
calibration.save(path)
loaded = Calibration.load(path)
assert len(list(tmp_path.glob("*.bak"))) == 1
```

Save twice to verify idempotence and backup creation; inspect `tmp_path` globs for side-effect files.

## Adding New Tests

1. Create `tests/test_<module>.py` next to the existing module tests listed above.
2. Import with absolute `maplebot.*` paths.
3. Build config from `maplebot.config` dataclasses; override only the fields you need with `dataclasses.replace`.
4. Replace `InputBackend`, `Windows`, and network fetchers with fakes. Never let a test call `Win32Input`, `SendInput`, or the live catalog API.
5. Use `tmp_path` for any output directory.
6. Run `.venv\Scripts\python.exe -m pytest -q` and `.venv\Scripts\python.exe -m ruff check src tests` before finishing.

---

*Testing analysis: 2026-10-24*
