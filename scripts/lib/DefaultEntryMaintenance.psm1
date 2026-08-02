Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProductDirectories = @("config", "runtime", "logs", "run-results")
$script:SchemaRelativePath = "_internal/autogame_orchestrator/_resources/run-report-v1.schema.json"
$script:MaximumManifestFiles = 10000

function Throw-MaintenanceError {
    param([Parameter(Mandatory = $true)][string]$Code)
    throw [System.InvalidOperationException]::new($Code)
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$ErrorCode = "UPDATE_PATH_POLICY_INVALID")
    if ([string]::IsNullOrWhiteSpace($Path) -or -not [System.IO.Path]::IsPathRooted($Path) -or $Path.StartsWith("\\", [System.StringComparison]::Ordinal) -or $Path.StartsWith("//", [System.StringComparison]::Ordinal)) {
        Throw-MaintenanceError $ErrorCode
    }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        $root = [System.IO.Path]::GetPathRoot($full)
        if ([string]::IsNullOrWhiteSpace($root) -or $root -notmatch "^[A-Za-z]:\\$") { Throw-MaintenanceError $ErrorCode }
        if ([string]::Equals($full, $root, [System.StringComparison]::OrdinalIgnoreCase)) { return $root }
        return $full.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    }
    catch {
        Throw-MaintenanceError $ErrorCode
    }
}

function Test-PathEqual {
    param([string]$Left, [string]$Right)
    return [string]::Equals((Get-NormalizedPath $Left), (Get-NormalizedPath $Right), [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-PathWithin {
    param([string]$Candidate, [string]$Parent)
    $candidateFull = Get-NormalizedPath $Candidate
    $parentFull = Get-NormalizedPath $Parent
    if (Test-PathEqual $candidateFull $parentFull) { return $true }
    $candidateRoot = [System.IO.Path]::GetPathRoot($candidateFull)
    $parentRoot = [System.IO.Path]::GetPathRoot($parentFull)
    if (-not [string]::Equals($candidateRoot, $parentRoot, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    $candidateParts = @($candidateFull.Substring($candidateRoot.Length).Trim("\", "/").Split("\") | Where-Object { $_ -ne "" })
    $parentParts = @($parentFull.Substring($parentRoot.Length).Trim("\", "/").Split("\") | Where-Object { $_ -ne "" })
    if ($candidateParts.Count -lt $parentParts.Count) { return $false }
    for ($index = 0; $index -lt $parentParts.Count; $index++) {
        if (-not [string]::Equals($candidateParts[$index], $parentParts[$index], [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
    }
    return $true
}

function Test-PathsRelated {
    param([string]$Left, [string]$Right)
    return (Test-PathWithin $Left $Right) -or (Test-PathWithin $Right $Left)
}

function Assert-OrdinaryDirectory {
    param([string]$Path, [string]$ErrorCode)
    if (-not [System.IO.Directory]::Exists($Path)) { Throw-MaintenanceError $ErrorCode }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        Throw-MaintenanceError $ErrorCode
    }
}

function Assert-OrdinaryFile {
    param([string]$Path, [string]$ErrorCode)
    if (-not [System.IO.File]::Exists($Path)) { Throw-MaintenanceError $ErrorCode }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        Throw-MaintenanceError $ErrorCode
    }
}

function Assert-NoReparseAncestors {
    param([string]$Path, [string]$ErrorCode)
    $current = Get-NormalizedPath $Path $ErrorCode
    while ($true) {
        if (Test-Path -LiteralPath $current -PathType Any) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { Throw-MaintenanceError $ErrorCode }
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or (Test-PathEqual $parent $current)) { break }
        $current = Get-NormalizedPath $parent $ErrorCode
    }
}

function Assert-ValidHash {
    param([object]$Value)
    if ($Value -isnot [string] -or [string]$Value -notmatch "^[0-9A-Fa-f]{64}$") {
        Throw-MaintenanceError "UPDATE_ARGUMENT_INVALID"
    }
    return ([string]$Value).ToUpperInvariant()
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-MaintenancePaths {
    param([string]$EnvironmentErrorCode = "UPDATE_ENVIRONMENT_INVALID")
    if ($env:OS -ne "Windows_NT" -or [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA) -or [string]::IsNullOrWhiteSpace($env:APPDATA)) {
        Throw-MaintenanceError $EnvironmentErrorCode
    }
    $localAppData = Get-NormalizedPath $env:LOCALAPPDATA $EnvironmentErrorCode
    $appData = Get-NormalizedPath $env:APPDATA $EnvironmentErrorCode
    Assert-NoReparseAncestors $localAppData $EnvironmentErrorCode
    Assert-NoReparseAncestors $appData $EnvironmentErrorCode
    Assert-OrdinaryDirectory $localAppData $EnvironmentErrorCode
    Assert-OrdinaryDirectory $appData $EnvironmentErrorCode
    $install = Get-NormalizedPath (Join-Path $localAppData "Programs\OrchestratoRRR")
    $product = Get-NormalizedPath (Join-Path $localAppData "OrchestratoRRR")
    if (Test-PathsRelated $install $product) { Throw-MaintenanceError "UPDATE_PATH_POLICY_INVALID" }
    Assert-NoReparseAncestors $install $EnvironmentErrorCode
    Assert-NoReparseAncestors $product $EnvironmentErrorCode
    return [pscustomobject]@{
        LocalAppData = $localAppData
        AppData = $appData
        Install = $install
        InstallParent = Get-NormalizedPath (Split-Path -Parent $install)
        Product = $product
        Runtime = Get-NormalizedPath (Join-Path $product "runtime")
        Shortcut = Get-NormalizedPath (Join-Path $appData "Microsoft\Windows\Start Menu\Programs\OrchestratoRRR\OrchestratoRRR.lnk")
    }
}

function Convert-ToRelativePath {
    param([string]$Root, [string]$Path, [string]$ErrorCode = "BACKUP_MANIFEST_INVALID")
    $rootFull = Get-NormalizedPath $Root
    $pathFull = Get-NormalizedPath $Path
    if (-not (Test-PathWithin $pathFull $rootFull) -or (Test-PathEqual $pathFull $rootFull)) {
        Throw-MaintenanceError $ErrorCode
    }
    return $pathFull.Substring($rootFull.Length + 1).Replace("\", "/")
}

function Assert-SafeRelativePath {
    param([string]$RelativePath, [string]$ErrorCode)
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [System.IO.Path]::IsPathRooted($RelativePath) -or $RelativePath.Contains("\") -or $RelativePath.Contains(":")) {
        Throw-MaintenanceError $ErrorCode
    }
    $parts = $RelativePath.Split("/")
    if ($parts.Count -eq 0 -or @($parts | Where-Object { [string]::IsNullOrEmpty($_) -or $_ -eq "." -or $_ -eq ".." }).Count -ne 0) {
        Throw-MaintenanceError $ErrorCode
    }
}

function Get-RegularTreeFiles {
    param([string]$Root, [string]$ErrorCode)
    Assert-OrdinaryDirectory $Root $ErrorCode
    $results = New-Object System.Collections.Generic.List[object]
    $stack = New-Object System.Collections.Generic.Stack[string]
    $stack.Push((Get-NormalizedPath $Root))
    while ($stack.Count -gt 0) {
        $directory = $stack.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { Throw-MaintenanceError $ErrorCode }
            if ($item.PSIsContainer) {
                $stack.Push($item.FullName)
            }
            elseif ($item -is [System.IO.FileInfo]) {
                $results.Add($item)
                if ($results.Count -gt $script:MaximumManifestFiles) { Throw-MaintenanceError $ErrorCode }
            }
            else {
                Throw-MaintenanceError $ErrorCode
            }
        }
    }
    return @($results | ForEach-Object { $_ })
}

function Get-TreeManifest {
    param([string]$Root, [string]$ErrorCode = "UPDATE_SOURCE_INVALID")
    $entries = @()
    $seen = @{}
    foreach ($file in Get-RegularTreeFiles $Root $ErrorCode) {
        $relative = Convert-ToRelativePath $Root $file.FullName $ErrorCode
        $key = $relative.ToUpperInvariant()
        if ($seen.ContainsKey($key)) { Throw-MaintenanceError $ErrorCode }
        $seen[$key] = $true
        $entries += [ordered]@{
            relative_path = $relative
            size = [int64]$file.Length
            sha256 = Get-FileSha256 $file.FullName
        }
    }
    return @($entries | Sort-Object { $_.relative_path.ToUpperInvariant() })
}

function Get-ProductDataState {
    param([string]$ProductDirectory, [string]$ErrorCode = "BACKUP_SOURCE_UNSAFE")
    Assert-OrdinaryDirectory $ProductDirectory $ErrorCode
    $states = [ordered]@{}
    $files = New-Object System.Collections.Generic.List[object]
    foreach ($name in $script:ProductDirectories) {
        $directory = Get-NormalizedPath (Join-Path $ProductDirectory $name)
        if ([System.IO.File]::Exists($directory)) { Throw-MaintenanceError $ErrorCode }
        $present = [System.IO.Directory]::Exists($directory)
        $states[$name] = $present
        if (-not $present) { continue }
        Assert-OrdinaryDirectory $directory $ErrorCode
        foreach ($file in Get-RegularTreeFiles $directory $ErrorCode) {
            $files.Add([ordered]@{
                relative_path = Convert-ToRelativePath $ProductDirectory $file.FullName
                size = [int64]$file.Length
                sha256 = Get-FileSha256 $file.FullName
            })
            if ($files.Count -gt $script:MaximumManifestFiles) { Throw-MaintenanceError $ErrorCode }
        }
    }
    return [pscustomobject]@{
        DirectoryStates = $states
        Files = @($files | Sort-Object { $_.relative_path.ToUpperInvariant() })
    }
}

function Test-ManifestEntriesEqual {
    param([object[]]$Left, [object[]]$Right)
    if ($Left.Count -ne $Right.Count) { return $false }
    for ($index = 0; $index -lt $Left.Count; $index++) {
        if (-not [string]::Equals([string]$Left[$index].relative_path, [string]$Right[$index].relative_path, [System.StringComparison]::Ordinal) -or
            [int64]$Left[$index].size -ne [int64]$Right[$index].size -or
            -not [string]::Equals([string]$Left[$index].sha256, [string]$Right[$index].sha256, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }
    return $true
}

function Test-DirectoryStatesEqual {
    param([object]$Left, [object]$Right)
    foreach ($name in $script:ProductDirectories) {
        if ([bool]$Left.$name -ne [bool]$Right.$name) { return $false }
    }
    return $true
}

function Copy-NewFile {
    param([string]$Source, [string]$Destination, [string]$ErrorCode = "BACKUP_COPY_FAILED")
    Assert-OrdinaryFile $Source $ErrorCode
    if ([System.IO.File]::Exists($Destination) -or [System.IO.Directory]::Exists($Destination)) { Throw-MaintenanceError $ErrorCode }
    $parent = Split-Path -Parent $Destination
    if (-not [System.IO.Directory]::Exists($parent)) { [System.IO.Directory]::CreateDirectory($parent) | Out-Null }
    $sourceStream = [System.IO.File]::Open($Source, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    try {
        $destinationStream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try { $sourceStream.CopyTo($destinationStream); $destinationStream.Flush($true) }
        finally { $destinationStream.Dispose() }
    }
    finally { $sourceStream.Dispose() }
}

function Write-NewUtf8File {
    param([string]$Path, [string]$Content)
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $writer = [System.IO.StreamWriter]::new($stream, $encoding)
        try { $writer.Write($Content); $writer.Flush(); $stream.Flush($true) }
        finally { $writer.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Remove-OwnedTree {
    param([string]$Path, [string]$ExpectedParent, [string]$ExpectedName)
    $full = Get-NormalizedPath $Path
    if (-not (Test-PathEqual (Split-Path -Parent $full) $ExpectedParent) -or -not [string]::Equals((Split-Path -Leaf $full), $ExpectedName, [System.StringComparison]::Ordinal)) {
        Throw-MaintenanceError "UPDATE_CLEANUP_FAILED"
    }
    if ([System.IO.Directory]::Exists($full)) {
        Assert-OrdinaryDirectory $full "UPDATE_CLEANUP_FAILED"
        [System.IO.Directory]::Delete($full, $true)
    }
    elseif ([System.IO.File]::Exists($full)) {
        Throw-MaintenanceError "UPDATE_CLEANUP_FAILED"
    }
}

function Assert-BackupDestination {
    param([string]$DestinationRoot, [object]$Paths)
    $destination = Get-NormalizedPath $DestinationRoot "BACKUP_DESTINATION_UNSAFE"
    if ($destination.StartsWith("\\", [System.StringComparison]::Ordinal)) { Throw-MaintenanceError "BACKUP_DESTINATION_UNSAFE" }
    if ((Test-PathsRelated $destination $Paths.Product) -or (Test-PathsRelated $destination $Paths.Install)) { Throw-MaintenanceError "BACKUP_DESTINATION_UNSAFE" }
    Assert-NoReparseAncestors $destination "BACKUP_DESTINATION_UNSAFE"
    if (-not [System.IO.Directory]::Exists($destination)) {
        $parent = Split-Path -Parent $destination
        Assert-OrdinaryDirectory $parent "BACKUP_DESTINATION_UNSAFE"
        [System.IO.Directory]::CreateDirectory($destination) | Out-Null
    }
    Assert-OrdinaryDirectory $destination "BACKUP_DESTINATION_UNSAFE"
    return $destination
}

function Read-BackupManifest {
    param([string]$Bundle, [string]$ExpectedHash, [string]$ErrorCode = "UPDATE_BACKUP_INVALID")
    Assert-OrdinaryDirectory $Bundle $ErrorCode
    $manifestPath = Join-Path $Bundle "manifest.json"
    $hashPath = Join-Path $Bundle "manifest.sha256"
    Assert-OrdinaryFile $manifestPath $ErrorCode
    Assert-OrdinaryFile $hashPath $ErrorCode
    $actualHash = Get-FileSha256 $manifestPath
    $recordedHash = ([System.IO.File]::ReadAllText($hashPath)).Trim().ToUpperInvariant()
    if ($actualHash -ne $ExpectedHash -or $recordedHash -ne $ExpectedHash) { Throw-MaintenanceError $ErrorCode }
    try { $manifest = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json }
    catch { Throw-MaintenanceError $ErrorCode }
    $formatVersion = $manifest.format_version
    if ($formatVersion -is [bool] -or $formatVersion -isnot [byte] -and $formatVersion -isnot [int16] -and $formatVersion -isnot [int32] -and $formatVersion -isnot [int64] -and $formatVersion -isnot [uint16] -and $formatVersion -isnot [uint32] -and $formatVersion -isnot [uint64]) { Throw-MaintenanceError $ErrorCode }
    if ([int64]$formatVersion -ne 1 -or $null -eq $manifest.directory_states -or $null -eq $manifest.files -or $manifest.files -isnot [array]) { Throw-MaintenanceError $ErrorCode }
    $expectedStateNames = @($script:ProductDirectories)
    $actualStateNames = @($manifest.directory_states.PSObject.Properties.Name)
    if ($actualStateNames.Count -ne $expectedStateNames.Count -or (@($actualStateNames | Sort-Object) -join "|") -ne (@($expectedStateNames | Sort-Object) -join "|")) { Throw-MaintenanceError $ErrorCode }
    foreach ($name in $expectedStateNames) {
        if ($manifest.directory_states.PSObject.Properties[$name].Value -isnot [bool]) { Throw-MaintenanceError $ErrorCode }
    }
    $manifestNames = @($manifest.PSObject.Properties.Name)
    $expectedManifestNames = @("format_version", "created_at_utc", "directory_states", "files")
    if ($manifestNames.Count -ne $expectedManifestNames.Count -or (@($manifestNames | Sort-Object) -join "|") -ne (@($expectedManifestNames | Sort-Object) -join "|") -or $manifest.created_at_utc -isnot [string] -or [string]::IsNullOrWhiteSpace($manifest.created_at_utc)) { Throw-MaintenanceError $ErrorCode }
    $seen = @{}
    $entries = @()
    foreach ($entry in @($manifest.files)) {
        if ($null -eq $entry) { Throw-MaintenanceError $ErrorCode }
        $entryNames = @($entry.PSObject.Properties.Name)
        $expectedEntryNames = @("relative_path", "size", "sha256")
        if ($entryNames.Count -ne $expectedEntryNames.Count -or (@($entryNames | Sort-Object) -join "|") -ne (@($expectedEntryNames | Sort-Object) -join "|")) { Throw-MaintenanceError $ErrorCode }
        $relative = [string]$entry.relative_path
        Assert-SafeRelativePath $relative $ErrorCode
        $first = $relative.Split("/")[0]
        if ($first.ToUpperInvariant() -notin @($script:ProductDirectories | ForEach-Object { $_.ToUpperInvariant() })) { Throw-MaintenanceError $ErrorCode }
        $key = $relative.ToUpperInvariant()
        $sizeIsInteger = $entry.size -is [byte] -or $entry.size -is [int16] -or $entry.size -is [int32] -or $entry.size -is [int64] -or $entry.size -is [sbyte] -or $entry.size -is [uint16] -or $entry.size -is [uint32] -or $entry.size -is [uint64]
        if ($seen.ContainsKey($key) -or [string]$entry.sha256 -notmatch "^[0-9A-Fa-f]{64}$" -or $entry.size -is [bool] -or -not $sizeIsInteger -or [int64]$entry.size -lt 0) { Throw-MaintenanceError $ErrorCode }
        $seen[$key] = $true
        $file = Join-Path $Bundle $relative.Replace("/", "\")
        Assert-OrdinaryFile $file $ErrorCode
        if ((Get-Item -LiteralPath $file).Length -ne [int64]$entry.size -or (Get-FileSha256 $file) -ne ([string]$entry.sha256).ToUpperInvariant()) { Throw-MaintenanceError $ErrorCode }
        $entries += [ordered]@{ relative_path = $relative; size = [int64]$entry.size; sha256 = ([string]$entry.sha256).ToUpperInvariant() }
    }
    $actualBusiness = @(
        Get-RegularTreeFiles $Bundle $ErrorCode |
            ForEach-Object { Convert-ToRelativePath $Bundle $_.FullName $ErrorCode } |
            Where-Object { $_ -notin @("manifest.json", "manifest.sha256") } |
            Sort-Object { $_.ToUpperInvariant() }
    )
    $listed = @($entries | ForEach-Object { $_.relative_path } | Sort-Object { $_.ToUpperInvariant() })
    if (($actualBusiness -join "`n") -ne ($listed -join "`n")) { Throw-MaintenanceError $ErrorCode }
    return [pscustomobject]@{ Manifest = $manifest; Entries = @($entries | Sort-Object { $_.relative_path.ToUpperInvariant() }); Hash = $actualHash }
}

function Invoke-OrchestratoRRRProductDataBackupCore {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [hashtable]$TestHooks = @{}
    )
    $paths = Get-MaintenancePaths "BACKUP_ENVIRONMENT_INVALID"
    Assert-OrdinaryDirectory $paths.Product "BACKUP_SOURCE_UNSAFE"
    $destination = Assert-BackupDestination $DestinationRoot $paths
    $state = Get-ProductDataState $paths.Product "BACKUP_REPARSE_POINT_FOUND"
    $guid = [guid]::NewGuid().ToString("N")
    $bundleName = "OrchestratoRRR-product-data-backup-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))-$guid"
    $stagingName = ".$bundleName.staging"
    $staging = Join-Path $destination $stagingName
    $bundle = Join-Path $destination $bundleName
    if ([System.IO.Directory]::Exists($staging) -or [System.IO.Directory]::Exists($bundle) -or [System.IO.File]::Exists($staging) -or [System.IO.File]::Exists($bundle)) { Throw-MaintenanceError "BACKUP_DESTINATION_UNSAFE" }
    try {
        [System.IO.Directory]::CreateDirectory($staging) | Out-Null
        foreach ($entry in $state.Files) {
            $source = Join-Path $paths.Product ([string]$entry.relative_path).Replace("/", "\")
            $target = Join-Path $staging ([string]$entry.relative_path).Replace("/", "\")
            Copy-NewFile $source $target "BACKUP_COPY_FAILED"
            if ((Get-Item -LiteralPath $target).Length -ne [int64]$entry.size -or (Get-FileSha256 $target) -ne [string]$entry.sha256) { Throw-MaintenanceError "BACKUP_VERIFICATION_FAILED" }
        }
        $stateAfterCopy = Get-ProductDataState $paths.Product "BACKUP_VERIFICATION_FAILED"
        if (-not (Test-DirectoryStatesEqual $state.DirectoryStates $stateAfterCopy.DirectoryStates) -or -not (Test-ManifestEntriesEqual $state.Files $stateAfterCopy.Files)) { Throw-MaintenanceError "BACKUP_VERIFICATION_FAILED" }
        Invoke-TestHook $TestHooks "BeforeBackupManifest" $staging
        $manifest = [ordered]@{
            format_version = 1
            created_at_utc = [DateTime]::UtcNow.ToString("o")
            directory_states = $state.DirectoryStates
            files = @($state.Files)
        }
        $manifestText = $manifest | ConvertTo-Json -Depth 8
        $manifestPath = Join-Path $staging "manifest.json"
        Write-NewUtf8File $manifestPath $manifestText
        $manifestHash = Get-FileSha256 $manifestPath
        Write-NewUtf8File (Join-Path $staging "manifest.sha256") ($manifestHash + "`n")
        $verified = Read-BackupManifest $staging $manifestHash "BACKUP_VERIFICATION_FAILED"
        if (-not (Test-ManifestEntriesEqual $state.Files $verified.Entries) -or -not (Test-DirectoryStatesEqual $state.DirectoryStates $verified.Manifest.directory_states)) { Throw-MaintenanceError "BACKUP_VERIFICATION_FAILED" }
        [System.IO.Directory]::Move($staging, $bundle)
        $totalBytes = [int64]0
        foreach ($entry in $state.Files) { $totalBytes += [int64]$entry.size }
        return [pscustomobject]@{
            status = "success"
            backup_directory = $bundle
            manifest_sha256 = $manifestHash
            file_count = $state.Files.Count
            total_bytes = $totalBytes
            runtime_directory_present = [bool]$state.DirectoryStates.runtime
        }
    }
    catch {
        if ([System.IO.Directory]::Exists($staging)) {
            try { Remove-OwnedTree $staging $destination $stagingName }
            catch { Throw-MaintenanceError "BACKUP_CLEANUP_FAILED" }
        }
        throw
    }
}

function Invoke-OrchestratoRRRProductDataBackup {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$DestinationRoot)
    return Invoke-OrchestratoRRRProductDataBackupCore -DestinationRoot $DestinationRoot
}

function Assert-NoTransactionResidue {
    param([object]$Paths)
    Assert-OrdinaryDirectory $Paths.InstallParent "UPDATE_CURRENT_INSTALL_INVALID"
    foreach ($item in Get-ChildItem -LiteralPath $Paths.InstallParent -Force) {
        if ($item.Name -imatch "^OrchestratoRRR\.__((staging)|(backup)|(failed))__\.[0-9a-f]{32}$") { Throw-MaintenanceError "TRANSACTION_RESIDUE_FOUND" }
    }
}

function Assert-ShortcutState {
    param([object]$Paths)
    Assert-NoReparseAncestors $Paths.Shortcut "SHORTCUT_STATE_INVALID"
    Assert-OrdinaryFile $Paths.Shortcut "SHORTCUT_STATE_INVALID"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Paths.Shortcut)
    $target = Get-NormalizedPath $shortcut.TargetPath "SHORTCUT_STATE_INVALID"
    $working = Get-NormalizedPath $shortcut.WorkingDirectory "SHORTCUT_STATE_INVALID"
    if (-not (Test-PathEqual $target (Join-Path $Paths.Install "OrchestratoRRR.exe")) -or
        -not [string]::Equals([string]$shortcut.Arguments, "start", [System.StringComparison]::Ordinal) -or
        -not (Test-PathEqual $working $Paths.Runtime) -or
        -not [string]::Equals([string]$shortcut.Description, "OrchestratoRRR", [System.StringComparison]::Ordinal)) {
        Throw-MaintenanceError "SHORTCUT_STATE_INVALID"
    }
}

function Get-InstalledProcessCount {
    param([string]$Executable)
    $escaped = $Executable.Replace([string][char]92, ([string][char]92 + [string][char]92)).Replace("'", "''")
    return @(Get-CimInstance -ClassName Win32_Process -Filter "ExecutablePath = '$escaped'" | Where-Object { $_.ExecutablePath -and (Test-PathEqual $_.ExecutablePath $Executable) }).Count
}

function Copy-TreeCreateNew {
    param([string]$Source, [string]$Destination, [object[]]$Manifest)
    [System.IO.Directory]::CreateDirectory($Destination) | Out-Null
    foreach ($entry in $Manifest) {
        $sourceFile = Join-Path $Source ([string]$entry.relative_path).Replace("/", "\")
        $destinationFile = Join-Path $Destination ([string]$entry.relative_path).Replace("/", "\")
        Copy-NewFile $sourceFile $destinationFile "UPDATE_STAGING_FAILED"
    }
}

function Invoke-TestHook {
    param([hashtable]$Hooks, [string]$Name, [object]$Value = $null)
    if ($null -ne $Hooks -and $Hooks.ContainsKey($Name)) { & $Hooks[$Name] $Value }
}

function Assert-ProductMatchesBackup {
    param([object]$Paths, [object]$Backup)
    $current = Get-ProductDataState $Paths.Product "PRODUCT_DATA_CHANGED_SINCE_BACKUP"
    if (-not (Test-DirectoryStatesEqual $current.DirectoryStates $Backup.Manifest.directory_states) -or -not (Test-ManifestEntriesEqual $current.Files $Backup.Entries)) {
        Throw-MaintenanceError "PRODUCT_DATA_CHANGED_SINCE_BACKUP"
    }
}

function Invoke-OrchestratoRRRInstallUpdateCore {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SourceOnedir,
        [Parameter(Mandatory = $true)][string]$ProductDataBackup,
        [Parameter(Mandatory = $true)][object]$ExpectedBackupManifestSha256,
        [Parameter(Mandatory = $true)][object]$ExpectedCurrentExeSha256,
        [Parameter(Mandatory = $true)][object]$ExpectedSourceExeSha256,
        [Parameter(Mandatory = $true)][object]$ExpectedSourceSchemaSha256,
        [Parameter(Mandatory = $true)][object]$ExpectedSourceFileCount,
        [hashtable]$TestHooks = @{}
    )
    $backupHash = Assert-ValidHash $ExpectedBackupManifestSha256
    $currentHash = Assert-ValidHash $ExpectedCurrentExeSha256
    $sourceHash = Assert-ValidHash $ExpectedSourceExeSha256
    $schemaHash = Assert-ValidHash $ExpectedSourceSchemaSha256
    $fileCountText = [string]$ExpectedSourceFileCount
    $sourceFileCount = 0
    if ($ExpectedSourceFileCount -is [bool] -or $fileCountText -notmatch "^[1-9][0-9]*$" -or -not [int]::TryParse($fileCountText, [ref]$sourceFileCount)) { Throw-MaintenanceError "UPDATE_ARGUMENT_INVALID" }
    $paths = Get-MaintenancePaths
    Assert-OrdinaryDirectory $paths.Product "UPDATE_PATH_POLICY_INVALID"
    Assert-OrdinaryDirectory $paths.Install "UPDATE_CURRENT_INSTALL_INVALID"
    Assert-NoTransactionResidue $paths
    $source = Get-NormalizedPath $SourceOnedir "UPDATE_SOURCE_INVALID"
    $backupPath = Get-NormalizedPath $ProductDataBackup "UPDATE_BACKUP_INVALID"
    Assert-OrdinaryDirectory $source "UPDATE_SOURCE_INVALID"
    Assert-OrdinaryDirectory $backupPath "UPDATE_BACKUP_INVALID"
    Assert-NoReparseAncestors $source "UPDATE_SOURCE_INVALID"
    Assert-NoReparseAncestors $backupPath "UPDATE_BACKUP_INVALID"
    if ((Test-PathsRelated $source $paths.Product) -or (Test-PathsRelated $source $paths.Install) -or
        (Test-PathsRelated $backupPath $paths.Product) -or (Test-PathsRelated $backupPath $paths.Install) -or (Test-PathsRelated $backupPath $source)) {
        Throw-MaintenanceError "UPDATE_PATH_POLICY_INVALID"
    }
    $backup = Read-BackupManifest $backupPath $backupHash
    Assert-ProductMatchesBackup $paths $backup
    $currentExe = Join-Path $paths.Install "OrchestratoRRR.exe"
    $currentSchema = Join-Path $paths.Install $script:SchemaRelativePath.Replace("/", "\")
    Assert-OrdinaryFile $currentExe "UPDATE_CURRENT_INSTALL_INVALID"
    Assert-OrdinaryFile $currentSchema "UPDATE_CURRENT_INSTALL_INVALID"
    if ((Get-FileSha256 $currentExe) -ne $currentHash) { Throw-MaintenanceError "UPDATE_CURRENT_INSTALL_INVALID" }
    $currentManifest = Get-TreeManifest $paths.Install "UPDATE_CURRENT_INSTALL_INVALID"
    $sourceExe = Join-Path $source "OrchestratoRRR.exe"
    $sourceSchema = Join-Path $source $script:SchemaRelativePath.Replace("/", "\")
    Assert-OrdinaryFile $sourceExe "UPDATE_SOURCE_INVALID"
    Assert-OrdinaryFile $sourceSchema "UPDATE_SOURCE_INVALID"
    $sourceManifest = Get-TreeManifest $source "UPDATE_SOURCE_INVALID"
    if ((Get-FileSha256 $sourceExe) -ne $sourceHash -or (Get-FileSha256 $sourceSchema) -ne $schemaHash -or $sourceManifest.Count -ne $sourceFileCount) { Throw-MaintenanceError "UPDATE_SOURCE_INVALID" }
    if ($sourceHash -eq $currentHash) { Throw-MaintenanceError "UPDATED_CODE_NOT_PACKAGED" }
    if ((Get-InstalledProcessCount $currentExe) -ne 0) { Throw-MaintenanceError "INSTALLED_PRODUCT_IN_USE" }
    Assert-ShortcutState $paths
    $guid = [guid]::NewGuid().ToString("N")
    $stagingName = "OrchestratoRRR.__staging__.$guid"
    $backupName = "OrchestratoRRR.__backup__.$guid"
    $failedName = "OrchestratoRRR.__failed__.$guid"
    $staging = Join-Path $paths.InstallParent $stagingName
    $installBackup = Join-Path $paths.InstallParent $backupName
    $failed = Join-Path $paths.InstallParent $failedName
    $oldMoved = $false
    $newActivated = $false
    try {
        Copy-TreeCreateNew $source $staging $sourceManifest
        $stagingManifest = Get-TreeManifest $staging "UPDATE_STAGING_VERIFICATION_FAILED"
        if (-not (Test-ManifestEntriesEqual $sourceManifest $stagingManifest)) { Throw-MaintenanceError "UPDATE_STAGING_VERIFICATION_FAILED" }
        Invoke-TestHook $TestHooks "AfterStaging" $staging
        if (-not (Test-ManifestEntriesEqual $sourceManifest (Get-TreeManifest $source "UPDATE_SOURCE_INVALID"))) { Throw-MaintenanceError "UPDATE_SOURCE_INVALID" }
        if ((Get-InstalledProcessCount $currentExe) -ne 0) { Throw-MaintenanceError "INSTALLED_PRODUCT_IN_USE" }
        $backup = Read-BackupManifest $backupPath $backupHash
        Assert-ProductMatchesBackup $paths $backup
        if (-not (Test-ManifestEntriesEqual $currentManifest (Get-TreeManifest $paths.Install "UPDATE_CURRENT_INSTALL_INVALID"))) { Throw-MaintenanceError "UPDATE_CURRENT_INSTALL_INVALID" }
        if (-not (Test-ManifestEntriesEqual $sourceManifest (Get-TreeManifest $staging "UPDATE_STAGING_VERIFICATION_FAILED"))) { Throw-MaintenanceError "UPDATE_STAGING_VERIFICATION_FAILED" }
        if (-not (Test-ManifestEntriesEqual $sourceManifest (Get-TreeManifest $source "UPDATE_SOURCE_INVALID"))) { Throw-MaintenanceError "UPDATE_SOURCE_INVALID" }
        Assert-ShortcutState $paths
        [System.IO.Directory]::Move($paths.Install, $installBackup)
        $oldMoved = $true
        Invoke-TestHook $TestHooks "AfterBackupRename"
        [System.IO.Directory]::Move($staging, $paths.Install)
        $newActivated = $true
        Invoke-TestHook $TestHooks "AfterActivation"
        if (-not (Test-ManifestEntriesEqual $sourceManifest (Get-TreeManifest $paths.Install "UPDATE_POSTCHECK_FAILED"))) { Throw-MaintenanceError "UPDATE_POSTCHECK_FAILED" }
        if ((Get-FileSha256 (Join-Path $paths.Install "OrchestratoRRR.exe")) -ne $sourceHash -or (Get-FileSha256 (Join-Path $paths.Install $script:SchemaRelativePath.Replace("/", "\"))) -ne $schemaHash) { Throw-MaintenanceError "UPDATE_POSTCHECK_FAILED" }
        Assert-ShortcutState $paths
        $backup = Read-BackupManifest $backupPath $backupHash
        Assert-ProductMatchesBackup $paths $backup
        Remove-OwnedTree $installBackup $paths.InstallParent $backupName
        return [pscustomobject]@{ status = "success"; true_backup_rollback = $false; installed_file_count = $sourceManifest.Count; source_exe_sha256 = $sourceHash }
    }
    catch {
        $originalError = $_.Exception.Message
        if ($oldMoved) {
            try {
                if ($newActivated -and [System.IO.Directory]::Exists($paths.Install)) { [System.IO.Directory]::Move($paths.Install, $failed) }
                Invoke-TestHook $TestHooks "BeforeRollbackRestore"
                if (-not [System.IO.Directory]::Exists($installBackup) -or [System.IO.Directory]::Exists($paths.Install)) { Throw-MaintenanceError "UPDATE_ROLLBACK_FAILED" }
                [System.IO.Directory]::Move($installBackup, $paths.Install)
                if ((Get-FileSha256 (Join-Path $paths.Install "OrchestratoRRR.exe")) -ne $currentHash -or -not (Test-ManifestEntriesEqual $currentManifest (Get-TreeManifest $paths.Install "UPDATE_ROLLBACK_FAILED"))) { Throw-MaintenanceError "UPDATE_ROLLBACK_FAILED" }
                Assert-ShortcutState $paths
                Assert-ProductMatchesBackup $paths $backup
                if ([System.IO.Directory]::Exists($failed)) { Remove-OwnedTree $failed $paths.InstallParent $failedName }
                if ([System.IO.Directory]::Exists($staging)) { Remove-OwnedTree $staging $paths.InstallParent $stagingName }
            }
            catch { Throw-MaintenanceError "UPDATE_ROLLBACK_FAILED" }
        }
        elseif ([System.IO.Directory]::Exists($staging)) {
            Remove-OwnedTree $staging $paths.InstallParent $stagingName
        }
        Throw-MaintenanceError $originalError
    }
}

function Invoke-OrchestratoRRRInstallUpdate {
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
    return Invoke-OrchestratoRRRInstallUpdateCore @PSBoundParameters
}

Export-ModuleMember -Function Invoke-OrchestratoRRRProductDataBackup, Invoke-OrchestratoRRRInstallUpdate
