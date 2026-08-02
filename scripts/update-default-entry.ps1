[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceOnedir,
    [Parameter(Mandatory = $true)][string]$ProductDataBackup,
    [Parameter(Mandatory = $true)][object]$ExpectedBackupManifestSha256,
    [Parameter(Mandatory = $true)][object]$ExpectedCurrentExeSha256,
    [Parameter(Mandatory = $true)][object]$ExpectedSourceExeSha256,
    [Parameter(Mandatory = $true)][object]$ExpectedSourceSchemaSha256,
    [Parameter(Mandatory = $true)][object]$ExpectedSourceFileCount
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "lib\DefaultEntryMaintenance.psm1") -Force

try {
    $result = Invoke-OrchestratoRRRInstallUpdate `
        -SourceOnedir $SourceOnedir `
        -ProductDataBackup $ProductDataBackup `
        -ExpectedBackupManifestSha256 $ExpectedBackupManifestSha256 `
        -ExpectedCurrentExeSha256 $ExpectedCurrentExeSha256 `
        -ExpectedSourceExeSha256 $ExpectedSourceExeSha256 `
        -ExpectedSourceSchemaSha256 $ExpectedSourceSchemaSha256 `
        -ExpectedSourceFileCount $ExpectedSourceFileCount
    $result | ConvertTo-Json -Compress
}
catch {
    $message = $_.Exception.Message
    if ($message -notmatch "^(UPDATE_[A-Z0-9_]+|PRODUCT_DATA_CHANGED_SINCE_BACKUP|TRANSACTION_RESIDUE_FOUND|UPDATED_CODE_NOT_PACKAGED|INSTALLED_PRODUCT_IN_USE|SHORTCUT_STATE_INVALID)$") { $message = "UPDATE_POSTCHECK_FAILED" }
    [Console]::Error.WriteLine($message)
    exit 2
}
