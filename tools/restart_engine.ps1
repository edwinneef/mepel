param(
    [switch]$EnableGameplayInput,
    # Shut the engine down and close its launcher windows without starting a new one.
    [switch]$StopOnly,
    # Browser dashboard owns controls by default; native overlay is an explicit opt-in.
    [switch]$StartNativeOverlay,
    [int]$Port = 8765
)

# Restart the debugger engine in one console window. Starting run.ps1 again for each
# restart leaves every previous -NoExit launcher window open, so this script shuts the
# engine down through its own API and closes run.ps1 launchers that no longer host it.
# Input-capable sessions start the elevated MapleBot task (tools/install_elevated_task.ps1).
# -StopOnly stops there and also closes the overlay, turning the bot off.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$base = "http://127.0.0.1:$Port"
# Close old native renderers before restarting; their former presence does not opt
# the operator into taking the control lease away from the browser dashboard.
$overlays = @(Get-CimInstance Win32_Process -Filter "Name='electron.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Replace('/', '\') -like "*$root\ui\overlay\main.cjs*"
})

function Test-Listening {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-Listening) {
    $html = (Invoke-WebRequest "$base/" -UseBasicParsing).Content
    $token = [regex]::Match($html, '[A-Za-z0-9_\-]{43}').Value
    if (-not $token) { throw "No debugger token found at $base" }
    Invoke-RestMethod -Method Post "$base/api/shutdown_bot" -Headers @{ 'X-Debug-Token' = $token } `
        -ContentType 'application/json' -Body '{}' | Out-Null
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline -and (Test-Listening)) { Start-Sleep -Milliseconds 300 }
    if (Test-Listening) { throw "The engine on port $Port did not stop; check its window" }
}

# Close only launcher windows for this project's run.ps1 that no longer host Python.
$launchers = Get-CimInstance Win32_Process -Filter "Name='pwsh.exe' OR Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*$root\run.ps1*" }
foreach ($launcher in $launchers) {
    $python = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($launcher.ProcessId)" |
        Where-Object Name -eq 'python.exe'
    if (-not $python) {
        try { Stop-Process -Id $launcher.ProcessId -Confirm:$false } catch { }
    }
}

# The engine has released input and stopped. Close only this project's old overlay;
# never carry its queued actions or credentials into the replacement engine.
foreach ($overlay in $overlays) {
    try { Stop-Process -Id $overlay.ProcessId -Confirm:$false -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -ne 'ObjectNotFound') { throw }
    }
}

if ($StopOnly) {
    [pscustomobject]@{ stopped = $true; overlays_closed = @($overlays).Count; url = $base } |
        ConvertTo-Json -Compress
    return
}

if ($EnableGameplayInput -and (Get-ScheduledTask -TaskName 'MapleBot' -ErrorAction SilentlyContinue)) {
    # The elevated task window closes with its engine; wait so the new start is not ignored.
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and (Get-ScheduledTask -TaskName 'MapleBot').State -eq 'Running') {
        Start-Sleep -Milliseconds 300
    }
    & "$root\run.ps1" -EnableGameplayInput | Out-Null
    $process = $null
} elseif ($EnableGameplayInput -and -not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run .\tools\install_elevated_task.ps1 once to register the elevated MapleBot task.'
} else {
    $arguments = @('-NoProfile', '-WindowStyle', 'Hidden', '-File', "$root\run.ps1")
    if ($EnableGameplayInput) { $arguments += '-EnableGameplayInput' }
    $process = Start-Process pwsh -WindowStyle Hidden -ArgumentList $arguments -WorkingDirectory $root -PassThru
}

$deadline = (Get-Date).AddSeconds(120)
$status = $null
while ((Get-Date) -lt $deadline -and -not $status) {
    Start-Sleep -Seconds 1
    try { $status = Invoke-RestMethod "$base/api/status" -TimeoutSec 2 } catch { }
}
if (-not $status) { throw "The engine did not answer on $base within 120 s; check its window" }
if ($StartNativeOverlay) {
    & "$PSScriptRoot/start_overlay.ps1" -WaitForEngine -Port $Port
}
[pscustomobject]@{
    window = if ($process) { $process.Id } else { 'MapleBot task (elevated)' }
    capture_only = $status.capture_only
    mode = $status.mode
    overlay_restarted = [bool]$StartNativeOverlay
    url = $base
} | ConvertTo-Json -Compress
