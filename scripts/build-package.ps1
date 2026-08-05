[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$spec = Join-Path $repoRoot "packaging\OrchestratoRRR.spec"
$distRoot = Join-Path $repoRoot "dist"
$outputRoot = Join-Path $distRoot "OrchestratoRRR"
$partialExe = Join-Path $distRoot "OrchestratoRRR.exe"
$workRoot = Join-Path $repoRoot "build\pyinstaller"
$exe = Join-Path $outputRoot "OrchestratoRRR.exe"
$bundleInternal = Join-Path $outputRoot "_internal"
$bundledSchema = Join-Path $bundleInternal "autogame_orchestrator\_resources\run-report-v1.schema.json"

function Assert-ScriptManagedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Expected,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Candidate) -or [string]::IsNullOrWhiteSpace($Expected)) {
        throw "$Label path must not be empty."
    }

    $candidateFull = [System.IO.Path]::GetFullPath($Candidate)
    $expectedFull = [System.IO.Path]::GetFullPath($Expected)
    if (-not [string]::Equals($candidateFull, $expectedFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label path is not the script-managed path."
    }
}

Assert-ScriptManagedPath $outputRoot (Join-Path $repoRoot "dist\OrchestratoRRR") "dist output"
Assert-ScriptManagedPath $partialExe (Join-Path $repoRoot "dist\OrchestratoRRR.exe") "partial dist executable"
Assert-ScriptManagedPath $workRoot (Join-Path $repoRoot "build\pyinstaller") "PyInstaller work"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "Project virtual-environment Python was not found."
    exit 2
}
if (-not (Test-Path -LiteralPath $spec -PathType Leaf)) {
    Write-Error "Version-controlled PyInstaller spec was not found."
    exit 2
}

if (Test-Path -LiteralPath $outputRoot) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
}
if (Test-Path -LiteralPath $partialExe) {
    Remove-Item -LiteralPath $partialExe -Force
}
if (Test-Path -LiteralPath $workRoot) {
    Remove-Item -LiteralPath $workRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $distRoot, $workRoot | Out-Null

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distRoot `
    --workpath $workRoot `
    $spec

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    Write-Error "The expected onedir executable was not generated."
    exit 1
}
if (-not (Test-Path -LiteralPath $bundleInternal -PathType Container)) {
    Write-Error "The expected onedir internal directory was not generated."
    exit 1
}
if (-not (Test-Path -LiteralPath $bundledSchema -PathType Leaf)) {
    Write-Error "The bundled RunReport schema was not generated."
    exit 1
}

Write-Output "OrchestratoRRR onedir build completed."
