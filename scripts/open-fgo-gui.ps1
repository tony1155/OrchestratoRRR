[CmdletBinding()]
param([switch]$EditorOnly)

$ErrorActionPreference = "Stop"
$baseDirectory = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$fgoDirectory = Join-Path $baseDirectory "MaaFgo-ORR"
$python = Join-Path $fgoDirectory "python\python.exe"
$launcher = Join-Path $fgoDirectory "agent\battle_editor\launcher.py"

try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "FGO Python is missing: $python"
    }
    if (Test-Path -LiteralPath $launcher -PathType Leaf) {
        $editorArguments = @("-B", "-X", "utf8", $launcher, "--no-takeover")
        if (-not $EditorOnly) {
            $editorArguments += "--no-browser"
        }
        $editorResult = & $python @editorArguments
        if ($LASTEXITCODE -ne 0) {
            if ($EditorOnly) {
                exit $LASTEXITCODE
            }
            Write-Warning "Battle editor could not start. Task settings are still available."
        } elseif ($EditorOnly) {
            Write-Output $editorResult
        }
    } elseif ($EditorOnly) {
        throw "Battle editor is missing: $launcher"
    }
    if (-not $EditorOnly) {
        $gui = Join-Path $fgoDirectory "MaaFgo.exe"
        if (-not (Test-Path -LiteralPath $gui -PathType Leaf)) {
            $gui = Join-Path $fgoDirectory "mxu.exe"
        }
        Start-Process -FilePath $gui -WorkingDirectory $fgoDirectory | Out-Null
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
