[CmdletBinding()]
param(
    [ValidateSet('engine', 'ui', 'all')][string]$Scope = 'engine',
    [string[]]$PythonTests = @('tests/test_dev_cycle.py', 'tests/test_town_check.py',
        'tests/test_navigation_check.py', 'tests/test_navigation_runtime.py'),
    [string[]]$UiTests = @(),
    [switch]$BuildUi,
    [switch]$Restart,
    [switch]$EnableGameplayInput,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if ($EnableGameplayInput -and -not $Restart) { throw '-EnableGameplayInput requires -Restart.' }
$steps = @()
if ($Scope -in @('engine', 'all')) {
    if (-not $PythonTests.Count) { throw 'Select at least one Python test.' }
    $steps += @{ name = 'engine tests'; directory = $root; command = "$root/.venv/Scripts/python.exe";
        arguments = @('-m', 'pytest', '-q') + $PythonTests }
    $steps += @{ name = 'lint'; directory = $root; command = "$root/.venv/Scripts/ruff.exe";
        arguments = @('check', 'src', 'tests', 'tools') }
}
if ($Scope -in @('ui', 'all')) {
    $steps += @{ name = 'UI tests'; directory = "$root/ui"; command = 'npm.cmd';
        arguments = @('test', '--') + $UiTests }
}
if ($BuildUi) {
    if ($Scope -eq 'engine') { throw '-BuildUi requires -Scope ui or all so UI tests run first.' }
    $steps += @{ name = 'UI build'; directory = "$root/ui"; command = 'npm.cmd';
        arguments = @('run', 'build') }
}
if ($Restart) {
    $restartArguments = @()
    if ($EnableGameplayInput) { $restartArguments += '-EnableGameplayInput' }
    $steps += @{ name = 'restart'; directory = $root; command = "$PSScriptRoot/restart_engine.ps1";
        arguments = $restartArguments }
}
if ($DryRun) {
    @{ dry_run = $true; steps = $steps } | ConvertTo-Json -Depth 5
    return
}

$output = Join-Path $root ('artifacts/dev-cycle/' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff'))
$rows = @()
$total = [Diagnostics.Stopwatch]::StartNew()
$failure = $null
try {
    foreach ($step in $steps) {
        if ($step.name -eq 'UI build') {
            # Vite replaces these installed assets. Keep the previous version before building.
            $assets = Join-Path $root 'src/maplebot/static/workbench'
            if (Test-Path -LiteralPath $assets) {
                $null = New-Item -ItemType Directory -Path $output -Force
                Copy-Item -LiteralPath $assets -Destination (Join-Path $output 'workbench-backup') -Recurse
            }
        }
        if ($step.name -eq 'restart') {
            Write-Host 'Restarting the engine now; this ends any active probe. It starts Off.'
        }
        Write-Host ($step.name + ': ' + $step.command + ' ' + ($step.arguments -join ' '))
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $row = @{ name = $step.name; seconds = 0; exit_code = $null }
        $rows += $row
        Push-Location -LiteralPath $step.directory
        try {
            $LASTEXITCODE = 0
            & $step.command @($step.arguments) | Out-Host
            $row.exit_code = $LASTEXITCODE
            if ($LASTEXITCODE) { throw ($step.name + ' failed with exit code ' + $LASTEXITCODE) }
        } finally {
            $row.seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3)
            Pop-Location
        }
    }
} catch {
    $failure = $_.Exception.Message
    throw
} finally {
    $null = New-Item -ItemType Directory -Path $output -Force
    @{ scope = $Scope; steps = $rows; failure = $failure;
        seconds = [Math]::Round($total.Elapsed.TotalSeconds, 3) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'result.json')
    Write-Host ('Evidence: ' + (Join-Path $output 'result.json'))
}
