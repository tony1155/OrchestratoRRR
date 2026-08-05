[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceOnedir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "DEFAULT_ENTRY_INSTALL_WINDOWS_REQUIRED"
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "DEFAULT_ENTRY_INSTALL_LOCALAPPDATA_REQUIRED"
}
if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
    throw "DEFAULT_ENTRY_INSTALL_APPDATA_REQUIRED"
}
if (-not [System.IO.Path]::IsPathRooted($env:LOCALAPPDATA)) {
    throw "DEFAULT_ENTRY_INSTALL_LOCALAPPDATA_REQUIRED"
}
if (-not [System.IO.Path]::IsPathRooted($env:APPDATA)) {
    throw "DEFAULT_ENTRY_INSTALL_APPDATA_REQUIRED"
}

$localAppData = [System.IO.Path]::GetFullPath($env:LOCALAPPDATA)
$appData = [System.IO.Path]::GetFullPath($env:APPDATA)
$source = [System.IO.Path]::GetFullPath($SourceOnedir)
if (-not [System.IO.Path]::IsPathRooted($SourceOnedir)) {
    throw "DEFAULT_ENTRY_INSTALL_SOURCE_MUST_BE_ABSOLUTE"
}
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "DEFAULT_ENTRY_INSTALL_SOURCE_INVALID"
}
$sourceItem = Get-Item -LiteralPath $source -Force
if (($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "DEFAULT_ENTRY_INSTALL_SOURCE_INVALID"
}

$sourceExe = Join-Path $source "OrchestratoRRR.exe"
$sourceInternal = Join-Path $source "_internal"
$sourceSchema = Join-Path $sourceInternal "autogame_orchestrator\_resources\run-report-v1.schema.json"
if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
    throw "DEFAULT_ENTRY_INSTALL_SOURCE_INVALID"
}
if (-not (Test-Path -LiteralPath $sourceInternal -PathType Container)) {
    throw "DEFAULT_ENTRY_INSTALL_SOURCE_INVALID"
}
if (-not (Test-Path -LiteralPath $sourceSchema -PathType Leaf)) {
    throw "DEFAULT_ENTRY_INSTALL_SOURCE_INVALID"
}

$installDirectory = Join-Path $localAppData "Programs\OrchestratoRRR"
$productDirectory = Join-Path $localAppData "OrchestratoRRR"
$configDirectory = Join-Path $productDirectory "config"
$runtimeDirectory = Join-Path $productDirectory "runtime"
$logDirectory = Join-Path $productDirectory "logs"
$reportDirectory = Join-Path $productDirectory "run-results"
$shortcutDirectory = Join-Path $appData "Microsoft\Windows\Start Menu\Programs\OrchestratoRRR"
$shortcutPath = Join-Path $shortcutDirectory "OrchestratoRRR.lnk"

if (Test-Path -LiteralPath $installDirectory) {
    if (-not (Test-Path -LiteralPath $installDirectory -PathType Container)) {
        throw "DEFAULT_ENTRY_INSTALL_TARGET_NOT_EMPTY"
    }
    $installItem = Get-Item -LiteralPath $installDirectory -Force
    if (($installItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "DEFAULT_ENTRY_INSTALL_TARGET_NOT_EMPTY"
    }
    if (@(Get-ChildItem -LiteralPath $installDirectory -Force).Count -ne 0) {
        throw "DEFAULT_ENTRY_INSTALL_TARGET_NOT_EMPTY"
    }
}
if (Test-Path -LiteralPath $shortcutPath) {
    throw "DEFAULT_ENTRY_INSTALL_SHORTCUT_EXISTS"
}

foreach ($directory in @(
    $installDirectory,
    $configDirectory,
    $runtimeDirectory,
    $logDirectory,
    $reportDirectory,
    $shortcutDirectory
)) {
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
}

Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $installDirectory -Recurse
$installedExe = Join-Path $installDirectory "OrchestratoRRR.exe"
$installedInternal = Join-Path $installDirectory "_internal"
$installedSchema = Join-Path $installedInternal "autogame_orchestrator\_resources\run-report-v1.schema.json"
if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf)) {
    throw "DEFAULT_ENTRY_INSTALL_COPY_INVALID"
}
if (-not (Test-Path -LiteralPath $installedInternal -PathType Container)) {
    throw "DEFAULT_ENTRY_INSTALL_COPY_INVALID"
}
if (-not (Test-Path -LiteralPath $installedSchema -PathType Leaf)) {
    throw "DEFAULT_ENTRY_INSTALL_COPY_INVALID"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $installedExe
$shortcut.Arguments = "start"
$shortcut.WorkingDirectory = $runtimeDirectory
$shortcut.Description = "OrchestratoRRR"
$shortcut.Save()

Write-Output "OrchestratoRRR installation and Start Menu shortcut created."
