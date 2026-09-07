[CmdletBinding()]
param(
    [string]$Config,
    [string]$DataDirectory,
    [ValidateRange(1, 86400)]
    [int]$DeadlineSeconds = 7200,
    [switch]$CheckOnly,
    [switch]$ConfirmBeforeRun,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not $Config) {
    $Config = Join-Path $projectRoot "config\orchestrator.local.toml"
}
if (-not $DataDirectory) {
    $DataDirectory = Join-Path (Split-Path -Parent $projectRoot) "orchestrator-data"
}

$exitCode = 2
$launch = $null
$pushed = $false
try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Project Python is missing: $python. See docs/manual/local-source-entry.md."
    }
    Push-Location -LiteralPath $projectRoot
    $pushed = $true
    $metadata = & $python -B -m autogame_orchestrator.local_preflight `
        --config $Config --source-root $projectRoot --data-directory $DataDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Local preflight failed. No workflow was started."
    }
    $launch = $metadata | ConvertFrom-Json
    Write-Host "OrchestratoRRR - source entry"
    Write-Host "Source:  $($launch.source_root)"
    Write-Host "Python:  $($launch.python)"
    Write-Host "Config:  $($launch.config_path)"
    Write-Host "Logs:    $($launch.log_directory)"
    Write-Host "Reports: $($launch.report_directory)"
    Write-Host "Runtime: $($launch.runtime_directory)"
    Write-Host "Deadline: $DeadlineSeconds seconds"
    Write-Host "Administrator required: $($launch.requires_administrator)"
    $index = 0
    foreach ($stage in $launch.stages) {
        $index++
        Write-Host "$index. $stage"
    }
    if ($CheckOnly) {
        Write-Host "Preflight passed. No programs started or run data written."
        $exitCode = 0
    } else {
        if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) {
            throw "An interactive console is required. Use -CheckOnly for noninteractive checks."
        }
        Write-Host "WARNING: This starts real programs and may update MAA or request administrator privileges."
        if ($ConfirmBeforeRun) {
            $confirmation = Read-Host "Type $($launch.confirmation) to continue"
            if ($confirmation -cne $launch.confirmation) {
                throw "Confirmation rejected. No workflow was started."
            }
        } else {
            $confirmation = $launch.confirmation
        }
        foreach ($directory in @($launch.log_directory, $launch.report_directory, $launch.runtime_directory)) {
            [System.IO.Directory]::CreateDirectory($directory) | Out-Null
        }
        Set-Location -LiteralPath $launch.runtime_directory
        & $python -m autogame_orchestrator run `
            --config $launch.config_path `
            --deadline-seconds $DeadlineSeconds `
            --confirm-real-execution $confirmation
        $exitCode = $LASTEXITCODE
        Write-Host "Workflow exit code: $exitCode"
        Write-Host "Run reports: $($launch.report_directory)"
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    if ($pushed) {
        Pop-Location
    }
    if (-not $CheckOnly -and -not $NoPause -and -not [Console]::IsInputRedirected) {
        $null = Read-Host "Press Enter to close"
    }
}
exit $exitCode
