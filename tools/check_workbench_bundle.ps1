[CmdletBinding()]
param(
    [string]$Installed,
    [string]$Output
)

# Build ui/ into a scratch folder and compare it with the installed workbench bundle.
# Read-only for the installed bundle: exits 1 and lists the drift when they differ.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Installed) { $Installed = Join-Path $root 'src/maplebot/static/workbench' }
if (-not $Output) {
    $Output = Join-Path ([IO.Path]::GetTempPath()) ('workbench-fresh-' + [Guid]::NewGuid().ToString('N'))
}

function Get-Tree([string]$Path) {
    $tree = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $tree }
    $base = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\', '/')
    foreach ($file in Get-ChildItem -LiteralPath $base -File -Recurse) {
        $relative = $file.FullName.Substring($base.Length + 1).Replace('\', '/')
        $tree[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
    return $tree
}

try {
    Push-Location -LiteralPath (Join-Path $root 'ui')
    try {
        $global:LASTEXITCODE = 0
        & npm.cmd run build -- --outDir $Output --emptyOutDir | Out-Host
        if ($global:LASTEXITCODE) { throw ('Fresh UI build failed with exit code ' + $global:LASTEXITCODE) }
    } finally {
        Pop-Location
    }
    $fresh = Get-Tree $Output
    $current = Get-Tree $Installed
    $drift = @()
    foreach ($name in ($fresh.Keys + $current.Keys | Sort-Object -Unique)) {
        if (-not $current.ContainsKey($name)) { $drift += "missing   $name" }
        elseif (-not $fresh.ContainsKey($name)) { $drift += "stale     $name" }
        elseif ($fresh[$name] -ne $current[$name]) { $drift += "differs   $name" }
    }
    if ($drift.Count) {
        Write-Host 'Workbench bundle is stale relative to ui/ (run tools/dev_cycle.ps1 -Scope ui -BuildUi):'
        $drift | ForEach-Object { Write-Host ('  ' + $_) }
        exit 1
    }
    Write-Host ('Workbench bundle matches a fresh build of ui/ (' + $fresh.Count + ' files).')
    exit 0
} finally {
    if (Test-Path -LiteralPath $Output) { Remove-Item -LiteralPath $Output -Recurse -Force }
}
