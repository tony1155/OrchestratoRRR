[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DestinationRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "lib\DefaultEntryMaintenance.psm1") -Force

try {
    $result = Invoke-OrchestratoRRRProductDataBackup -DestinationRoot $DestinationRoot
    $result | ConvertTo-Json -Compress
}
catch {
    $message = $_.Exception.Message
    if ($message -notmatch "^BACKUP_[A-Z0-9_]+$") { $message = "BACKUP_COPY_FAILED" }
    [Console]::Error.WriteLine($message)
    exit 2
}
