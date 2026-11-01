[CmdletBinding()]
param(
    [ValidateSet('engine', 'navigation', 'combat', 'perception', 'ui', 'all')]
    [string]$Scope = 'engine',
    [string[]]$PythonTests,
    [string[]]$LintPaths,
    [string[]]$UiTests = @(),
    [string]$FailureResult,
    [switch]$ReplayPolicy,
    [switch]$ReloadNavigation,
    [switch]$BuildUi,
    [switch]$Restart,
    [switch]$EnableGameplayInput,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$total = [Diagnostics.Stopwatch]::StartNew()
$root = Split-Path -Parent $PSScriptRoot
if ($EnableGameplayInput -and -not $Restart) { throw '-EnableGameplayInput requires -Restart.' }
if ($FailureResult -and -not $PSBoundParameters.ContainsKey('ReplayPolicy')) { $ReplayPolicy = $true }
if ($ReplayPolicy -and -not $FailureResult) { throw '-ReplayPolicy requires -FailureResult.' }
if ($ReloadNavigation -and ($Scope -ne 'navigation' -or $Restart)) {
    throw '-ReloadNavigation requires -Scope navigation and cannot combine with -Restart.'
}
$output = Join-Path $root ('artifacts/dev-cycle/' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff'))
$steps = @()
if ($FailureResult) {
    $failurePath = (Resolve-Path -LiteralPath $FailureResult).Path
    $failureArguments = @('-m', 'tools.failure_report', $failurePath,
        '--output', (Join-Path $output 'failure'))
    if ($ReplayPolicy) { $failureArguments += '--replay-policy' }
    $steps += @{ name = 'saved failure'; directory = $root;
        command = "$root/.venv/Scripts/python.exe"; arguments = $failureArguments }
}
if ($Scope -ne 'ui') {
    if (-not $PSBoundParameters.ContainsKey('PythonTests')) {
        $PythonTests = switch ($Scope) {
            'navigation' { @('tests/test_navigation_executor.py', 'tests/test_navigation_runtime.py',
                'tests/test_navigation_reload.py', 'tests/test_navigation_check.py') }
            'combat' { @('tests/test_decision.py', 'tests/test_keyboard.py', 'tests/test_runtime.py',
                'tests/test_farming.py', 'tests/test_farming_check.py') }
            'perception' { @('tests/test_perception.py', 'tests/test_reacquisition.py') }
            default { @('tests/test_dev_cycle.py', 'tests/test_failure_report.py',
                'tests/test_town_check.py', 'tests/test_navigation_check.py',
                'tests/test_navigation_runtime.py', 'tests/test_navigation_harness.py') }
        }
    }
    if (-not $PSBoundParameters.ContainsKey('LintPaths')) {
        $LintPaths = switch ($Scope) {
            'navigation' { @('src/maplebot/navigation.py', 'src/maplebot/navigation_executor.py',
                'src/maplebot/navigation_runtime.py', 'src/maplebot/navigation_reload.py',
                'src/maplebot/short_walk.py', 'tools/navigation_check.py',
                'tools/reload_navigation.py') + $PythonTests }
            'combat' { @('src/maplebot/decision.py', 'src/maplebot/keyboard.py',
                'src/maplebot/runtime.py', 'src/maplebot/farming.py',
                'tools/combat_check.py', 'tools/farming_check.py') + $PythonTests }
            'perception' { @('src/maplebot/perception.py', 'src/maplebot/reacquisition.py') + $PythonTests }
            default { @('src', 'tests', 'tools') }
        }
    }
    if (-not $PythonTests.Count) { throw 'Select at least one Python test.' }
    if (-not $LintPaths.Count) { throw 'Select at least one lint path.' }
    $steps += @{ name = 'engine tests'; directory = $root; command = "$root/.venv/Scripts/python.exe";
        arguments = @('-m', 'pytest', '-q') + $PythonTests }
    $steps += @{ name = 'lint'; directory = $root; command = "$root/.venv/Scripts/ruff.exe";
        arguments = @('check') + $LintPaths }
}
if ($Scope -in @('ui', 'all')) {
    $steps += @{ name = 'UI tests'; directory = "$root/ui"; command = 'npm.cmd';
        arguments = @('test', '--') + $UiTests }
}
if ($BuildUi) {
    if ($Scope -notin @('ui', 'all')) { throw '-BuildUi requires -Scope ui or all so UI tests run first.' }
    $steps += @{ name = 'UI build'; directory = "$root/ui"; command = 'npm.cmd';
        arguments = @('run', 'build') }
}
if ($ReloadNavigation) {
    $steps += @{ name = 'navigation reload'; directory = $root;
        command = "$root/.venv/Scripts/python.exe";
        arguments = @('-m', 'tools.reload_navigation') }
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

$rows = @()
$setupSeconds = $total.Elapsed.TotalSeconds
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
            $global:LASTEXITCODE = 0
            & $step.command @($step.arguments) | Out-Host
            $row.exit_code = $global:LASTEXITCODE
            if ($global:LASTEXITCODE) { throw ($step.name + ' failed with exit code ' + $global:LASTEXITCODE) }
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
        setup_seconds = [Math]::Round($setupSeconds, 3);
        command_seconds = [Math]::Round(($rows | Measure-Object -Property seconds -Sum).Sum, 3);
        seconds = [Math]::Round($total.Elapsed.TotalSeconds, 3) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'result.json')
    Write-Host ('Evidence: ' + (Join-Path $output 'result.json'))
}
