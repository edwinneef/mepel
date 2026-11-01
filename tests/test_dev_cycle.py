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
    assert report["seconds"] >= report["command_seconds"]
    assert report["setup_seconds"] >= 0


def test_focused_scopes_plan_offline_checks_and_reload_after_success(tmp_path):
    source = Path(__file__).resolve().parents[1] / "tools/dev_cycle.ps1"
    failure = tmp_path / "failure.json"
    failure.write_text("{}", "utf-8")
    script = """
        $reports = @()
        $reports += (& $args[0] -Scope navigation -ReloadNavigation -DryRun | ConvertFrom-Json)
        $reports += (& $args[0] -Scope combat -FailureResult $args[1] -ReplayPolicy -DryRun |
            ConvertFrom-Json)
        $reports += (& $args[0] -Scope perception -LintPaths src/maplebot/perception.py -DryRun |
            ConvertFrom-Json)
        ConvertTo-Json -InputObject $reports -Depth 8
    """
    # One PowerShell process covers all three plans without executing a check or reload.
    runner = tmp_path / "plans.ps1"
    runner.write_text(script, "utf-8")
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(runner), str(source), str(failure)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    navigation, combat, perception = json.loads(result.stdout)
    assert [s["name"] for s in navigation["steps"]] == ["engine tests", "lint", "navigation reload"]
    assert "tests/test_navigation_reload.py" in navigation["steps"][0]["arguments"]
    assert [s["name"] for s in combat["steps"]] == ["saved failure", "engine tests", "lint"]
    assert "--replay-policy" in combat["steps"][0]["arguments"]
    assert "tests/test_farming_check.py" in combat["steps"][1]["arguments"]
    assert "tests/test_reacquisition.py" in perception["steps"][0]["arguments"]
    assert perception["steps"][1]["arguments"] == ["check", "src/maplebot/perception.py"]
    assert all("restart" not in [s["name"] for s in r["steps"]]
               for r in (navigation, combat, perception))


def test_rejects_reload_of_other_scopes_or_combined_restart(tmp_path):
    source = Path(__file__).resolve().parents[1] / "tools/dev_cycle.ps1"
    runner = tmp_path / "refusals.ps1"
    runner.write_text("""
        $refusals = 0
        try { & $args[0] -Scope combat -ReloadNavigation -DryRun } catch { $refusals++ }
        try { & $args[0] -Scope navigation -ReloadNavigation -Restart -DryRun }
        catch { $refusals++ }
        try { & $args[0] -ReplayPolicy -DryRun } catch { $refusals++ }
        if ($refusals -ne 3) { exit 1 }
    """, "utf-8")
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(runner), str(source)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
