param(
    [switch]$EnableGameplayInput,
    [int]$Port = 8765
)

# Restart the debugger engine in one console window. Starting run.ps1 again for each
# restart leaves every previous -NoExit launcher window open, so this script shuts the
# engine down through its own API and closes run.ps1 launchers that no longer host it.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$base = "http://127.0.0.1:$Port"

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
    if (-not $python) { Stop-Process -Id $launcher.ProcessId -Confirm:$false }
}

$arguments = @('-NoExit', '-File', "$root\run.ps1")
if ($EnableGameplayInput) { $arguments += '-EnableGameplayInput' }
$process = Start-Process pwsh -ArgumentList $arguments -WorkingDirectory $root -PassThru

$deadline = (Get-Date).AddSeconds(120)
$status = $null
while ((Get-Date) -lt $deadline -and -not $status) {
    Start-Sleep -Seconds 1
    try { $status = Invoke-RestMethod "$base/api/status" -TimeoutSec 2 } catch { }
}
if (-not $status) { throw "The engine did not answer on $base within 120 s; check its window" }
[pscustomobject]@{
    window = $process.Id
    capture_only = $status.capture_only
    mode = $status.mode
    url = $base
} | ConvertTo-Json -Compress
