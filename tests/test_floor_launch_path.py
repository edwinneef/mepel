"""Real Tk click and prepared CLI preflight, with no engine or input access."""

import contextlib
import io
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import prepared_floor_check as prepared
from tools.floor_batch_button import main


@pytest.mark.parametrize("scenario,expected", [
    ("ready", "Control returned to operator"),
    ("focus_denied", "Guarded focus failed; no retry"),
    ("wrong_floor", "Stand on recognized floor fh66"),
])
def test_click_runs_guarded_preflight_once(scenario, expected):
    # Each real launcher is a separate process; Tcl cannot reliably recreate roots
    # in this Windows interpreter after the worker-thread lifecycle.
    code = (
        "import runpy,sys; from pytest import MonkeyPatch; "
        "test=runpy.run_path(sys.argv[1]); "
        "patch=MonkeyPatch(); "
        "test['run_click'](patch,sys.argv[2],sys.argv[3]); patch.undo()"
    )
    result = subprocess.run([sys.executable, "-c", code, str(Path(__file__).resolve()),
                             scenario, expected], capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr


def run_click(monkeypatch, scenario, expected):
    calls, batches, inspected, errors = [], [], [], []

    class Api:
        def status(self):
            return {"session_id": "offline", "mode": "capture", "focused": True,
                    "captured_at": time.time(), "alarm": {"active": False},
                    "input_state": {"held_keys": [], "active": False, "queued": False},
                    "position": {"area_id": prepared.AREA,
                                 "surface_id": "fh1" if scenario == "wrong_floor" else "fh66"},
                    "readiness": {"combat": {"ready": True}}}

        def command(self, name, payload):
            calls.append(name)
            assert name == "focus_game", "Unexpected engine command in offline test"
            return {"focused": scenario != "focus_denied"}

    def batch(api, output, **options):
        batches.append(options)
        return {"outcome": "failure", "error": "offline first-failure fixture",
                "after": {"alarm": {"active": True},
                          "input_state": {"held_keys": [], "active": False, "queued": False}}}

    monkeypatch.setattr(prepared, "Debugger", Api)
    monkeypatch.setattr(prepared, "run", batch)
    monkeypatch.setattr("sys.argv", ["prepared_floor_check", "--run", "--focus"])

    def runner(command, **kwargs):
        assert command[1:] == ["-m", "tools.prepared_floor_check", "--run", "--focus"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = prepared.main()
        return subprocess.CompletedProcess(command, code, output.getvalue(), "")

    def ready(window, button, output):
        def click():
            button.invoke()
            button.invoke()  # A disabled button cannot start a duplicate batch.

        def inspect():
            if str(button["state"]) == "disabled":
                window.after(20, inspect)
                return
            try:
                assert expected in output.get("1.0", "end")
                assert window.state() != "withdrawn"
                inspected.append(True)
            except AssertionError as error:
                errors.append(error)
            window.destroy()

        window.after(0, click)
        window.after(20, inspect)
        window.after(5000, window.destroy)

    main(runner=runner, on_ready=ready)
    assert not errors
    assert inspected, "No completed GUI result before timeout"
    assert calls == ["focus_game"]
    if scenario == "ready":
        assert batches == [{"area": prepared.AREA, "single_platform": True,
                            "session_minutes": 1, "consumables": True, "require_enemy": True}]
    else:
        assert not batches
