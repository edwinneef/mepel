import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows development launcher")


@pytest.fixture
def cycle(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    source = Path(__file__).resolve().parents[1] / "tools" / "dev_cycle.ps1"
    shutil.copyfile(source, tools / source.name)
    (tools / "restart_engine.ps1").write_text(
        "Add-Content -LiteralPath $env:DEV_CYCLE_LOG -Value 'restart'\n", encoding="utf-8")
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "npm.cmd").write_text(
        '@echo off\necho %*>>"%DEV_CYCLE_LOG%"\nexit /b %DEV_CYCLE_EXIT%\n',
        encoding="utf-8")
    assets = tmp_path / "src/maplebot/static/workbench"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("previous UI", encoding="utf-8")

    def run(*args, exit_code=0):
        env = {**os.environ, "DEV_CYCLE_LOG": str(tmp_path / "commands.txt"),
               "DEV_CYCLE_EXIT": str(exit_code), "PATH": str(ui) + os.pathsep + os.environ["PATH"]}
        return subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(tools / source.name),
             "-Scope", "ui", "-BuildUi", "-Restart", *args],
            env=env, capture_output=True, text=True, timeout=30)

    return tmp_path, run


def test_dry_run_has_no_commands_or_artifacts(cycle):
    root, run = cycle
    result = run("-DryRun")
    assert result.returncode == 0, result.stderr
    assert [s["name"] for s in json.loads(result.stdout)["steps"]] == [
        "UI tests", "UI build", "restart"]
    assert not (root / "commands.txt").exists()
    assert not (root / "artifacts").exists()


def test_failed_check_prevents_build_backup_and_restart(cycle):
    root, run = cycle
    result = run(exit_code=7)
    assert result.returncode != 0
    assert (root / "commands.txt").read_text().splitlines() == ["test --"]
    evidence = next(root.glob("artifacts/dev-cycle/*/result.json"))
    report = json.loads(evidence.read_text())
    assert report["steps"][0]["exit_code"] == 7
    assert report["failure"]
    assert not list(root.glob("artifacts/dev-cycle/*/workbench-backup"))


def test_success_backs_up_ui_before_explicit_restart(cycle):
    root, run = cycle
    result = run()
    assert result.returncode == 0, result.stderr
    assert (root / "commands.txt").read_text().splitlines() == ["test --", "run build", "restart"]
    evidence = next(root.glob("artifacts/dev-cycle/*/result.json"))
    assert (evidence.parent / "workbench-backup/index.html").read_text() == "previous UI"
    report = json.loads(evidence.read_text())
    assert report["failure"] is None
    assert all(row["exit_code"] == 0 and row["seconds"] >= 0 for row in report["steps"])
