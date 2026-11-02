"""Exercise the restart script with fake processes and HTTP; never launch the game."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows engine launcher")
def test_restart_starts_engine_and_overlay_unless_told_not_to(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    source = Path(__file__).resolve().parents[1] / "tools/restart_engine.ps1"
    shutil.copyfile(source, tools / source.name)
    (tools / "start_overlay.ps1").write_text(
        "param([switch]$WaitForEngine, [int]$Port)\n"
        "$global:events.Add(\"overlay-start:$Port\")\n", encoding="utf-8")
    runner = tmp_path / "check.ps1"
    runner.write_text(r'''
        param($restart)
        $ErrorActionPreference = 'Stop'
        $global:events = [Collections.Generic.List[string]]::new()
        function Get-NetTCPConnection { param($LocalPort, $State, $ErrorAction)
            if (-not $global:stopped) { [pscustomobject]@{ State = 'Listen' } }
        }
        function Get-CimInstance { param($ClassName, $Filter)
            if ($global:hasOverlay -and $Filter -eq "Name='electron.exe'") {
                [pscustomobject]@{ ProcessId = 123;
                    CommandLine = "$PSScriptRoot\ui\overlay\main.cjs" }
            }
        }
        function Invoke-WebRequest { param($Uri, [switch]$UseBasicParsing)
            [pscustomobject]@{ Content = ('a' * 43) }
        }
        function Invoke-RestMethod {
            param($Uri, $Method, $Headers, $ContentType, $Body, $TimeoutSec)
            if ($Uri -like '*/api/shutdown_bot') {
                $global:stopped = $true
                $global:events.Add('engine-stop')
            } else {
                $global:events.Add('engine-ready')
                [pscustomobject]@{ capture_only = $true; mode = 'capture' }
            }
        }
        function Stop-Process { param($Id, $Confirm, $ErrorAction)
            $global:events.Add('overlay-stop')
        }
        function Start-Process {
            param($FilePath, $WindowStyle, $ArgumentList, $WorkingDirectory, [switch]$PassThru)
            $global:events.Add('engine-start')
            [pscustomobject]@{ Id = 456 }
        }
        function Start-Sleep { param($Milliseconds, $Seconds) }
        $rows = @()
        foreach ($case in @('default', 'no-overlay', 'headless', 'stop-only')) {
            $global:events.Clear()
            $global:stopped = $false
            $global:hasOverlay = $case -ne 'headless'
            if ($case -eq 'stop-only') { $result = & $restart -StopOnly -Port 8877 }
            elseif ($case -eq 'no-overlay') {
                $result = & $restart -NoOverlay -Port 8877
            }
            else { $result = & $restart -Port 8877 }
            $rows += @{ case = $case; events = @($global:events.ToArray());
                result = ($result | ConvertFrom-Json) }
        }
        ConvertTo-Json -InputObject $rows -Depth 5
    ''', encoding="utf-8")
    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(runner), str(tools / source.name)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    default, no_overlay, headless, stopped = json.loads(result.stdout)
    assert default["events"] == ["engine-stop", "overlay-stop", "engine-start", "engine-ready",
                                 "overlay-start:8877"]
    assert default["result"]["overlay_started"] is True
    assert no_overlay["events"] == ["engine-stop", "overlay-stop", "engine-start", "engine-ready"]
    assert no_overlay["result"]["overlay_started"] is False
    # No overlay ran before the restart; one still starts with the new engine.
    assert headless["events"] == ["engine-stop", "engine-start", "engine-ready",
                                  "overlay-start:8877"]
    assert stopped["events"] == ["engine-stop", "overlay-stop"]


