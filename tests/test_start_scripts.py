"""The root start, restart and stop scripts with a stubbed restart_engine.ps1; never launches."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher scripts")
def test_start_restart_and_stop_launch_engine_overlay_and_dashboard(tmp_path):
    for name in ("start.ps1", "restart.ps1", "stop.ps1"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/restart_engine.ps1").write_text(
        "param([switch]$EnableGameplayInput, [switch]$StopOnly, [switch]$NoOverlay, [int]$Port)\n"
        "$global:events.Add(\"engine input=$([bool]$EnableGameplayInput) stop=$([bool]$StopOnly)"
        " overlay=$(-not $NoOverlay) port=$Port\")\n", encoding="utf-8")
    runner = tmp_path / "check.ps1"
    runner.write_text(r'''
        param($root)
        $global:events = [Collections.Generic.List[string]]::new()
        function Get-NetTCPConnection { param($LocalPort, $State, $ErrorAction)
            if ($global:running) { [pscustomobject]@{ State = 'Listen' } } }
        function Invoke-RestMethod { param($Uri, $TimeoutSec)
            if (-not $global:running) { throw 'not running' }
            [pscustomobject]@{ capture_only = $global:captureOnly } }
        function Start-Process { param($FilePath) $global:events.Add("browser $FilePath") }
        $rows = [ordered]@{}
        function Run($name, [scriptblock]$block) {
            $global:events.Clear()
            try { & $block; $rows[$name] = @($global:events.ToArray()) }
            catch { $rows[$name] = @("error: $($_.Exception.Message)") }
        }
        $global:running = $false
        Run 'start' { & "$root\start.ps1" }
        Run 'start-input-bare' {
            & "$root\start.ps1" -EnableGameplayInput -NoOverlay -NoBrowser -Port 8800 }
        $global:running = $true; $global:captureOnly = $false
        Run 'start-while-running' { & "$root\start.ps1" }
        Run 'restart-keeps-input' { & "$root\restart.ps1" -NoBrowser }
        Run 'restart-forced-capture' { & "$root\restart.ps1" -CaptureOnly -NoBrowser }
        $global:captureOnly = $true
        Run 'restart-keeps-capture' { & "$root\restart.ps1" -NoBrowser }
        Run 'restart-both-flags' { & "$root\restart.ps1" -CaptureOnly -EnableGameplayInput }
        Run 'stop' { & "$root\stop.ps1" }
        $rows | ConvertTo-Json -Depth 4
    ''', encoding="utf-8")
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(runner), str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert rows["start"] == ["engine input=False stop=False overlay=True port=8765",
                             "browser http://127.0.0.1:8765/"]
    assert rows["start-input-bare"] == ["engine input=True stop=False overlay=False port=8800"]
    assert "already running on port 8765" in rows["start-while-running"][0]
    assert rows["restart-keeps-input"] == ["engine input=True stop=False overlay=True port=8765"]
    capture = ["engine input=False stop=False overlay=True port=8765"]
    assert rows["restart-forced-capture"] == capture
    assert rows["restart-keeps-capture"] == capture
    assert "not both" in rows["restart-both-flags"][0]
    assert rows["stop"] == ["engine input=False stop=True overlay=True port=8765"]
