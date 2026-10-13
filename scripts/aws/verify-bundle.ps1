param([string]$BundleRoot = '.')
# 配布物の自己整合性を検査する。出所の確認には別経路のZIP hashが必要。
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-SafeFile([string]$RelativePath) {
    # Windows/WSLで同じ範囲を検証し、junctionやsymlinkによる範囲外参照を拒否する。
    if ([string]::IsNullOrEmpty($RelativePath) -or $RelativePath -match '[\\:\x00-\x1f|]' -or $RelativePath.StartsWith('/')) {
        throw "Unsafe path: $RelativePath"
    }
    $Current = $script:Root
    foreach ($Part in $RelativePath.Split('/')) {
        if ($Part -eq '' -or $Part -eq '.' -or $Part -eq '..') { throw "Unsafe path: $RelativePath" }
        $Current = Join-Path $Current $Part
        $Item = Get-Item -LiteralPath $Current -Force
        if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Linked path: $RelativePath" }
    }
    $Item = Get-Item -LiteralPath $Current -Force
    if ($Item.PSIsContainer) { throw "Not a regular file: $RelativePath" }
    return $Item
}

function Read-HashList([string]$Name, [bool]$IsManifest) {
    $List = Get-SafeFile $Name
    $Seen = @{}
    $Records = @()
    foreach ($Line in [IO.File]::ReadAllLines($List.FullName, [Text.Encoding]::UTF8)) {
        if ($Line -notmatch '^([0-9a-f]{64})  (.+)$') { throw "Invalid checksum line: $Name" }
        $Hash = $Matches[1]
        $Path = $Matches[2]
        if ($Seen.ContainsKey($Path)) { throw "Duplicate path: $Path" }
        $Seen[$Path] = $true
        if ($IsManifest) {
            if ($Path -ne 'manifest.json' -and $Path -ne 'checksums.sha256') { throw "Unexpected manifest path: $Path" }
        } elseif ($Path -eq 'manifest.json' -or $Path -eq 'manifest.sha256' -or $Path -eq 'checksums.sha256') {
            throw "Unexpected payload path: $Path"
        }
        $File = Get-SafeFile $Path
        if ((Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Hash) {
            throw "Checksum mismatch: $Path"
        }
        $Records += $Path
    }
    if ($Records.Count -eq 0) { throw "Empty checksum list: $Name" }
    if ($IsManifest -and ($Records.Count -ne 2 -or -not $Seen.ContainsKey('manifest.json') -or -not $Seen.ContainsKey('checksums.sha256'))) {
        throw 'Manifest checksum list must contain exactly two files.'
    }
    return $Records
}

try {
    $RootItem = Get-Item -LiteralPath $BundleRoot -Force
    if (-not $RootItem.PSIsContainer -or ($RootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'BundleRoot must be an ordinary directory.'
    }
    $script:Root = $RootItem.FullName
    $null = Read-HashList 'manifest.sha256' $true
    $PayloadPaths = @(Read-HashList 'checksums.sha256' $false)
    $ManifestFile = Get-SafeFile 'manifest.json'
    $Manifest = [IO.File]::ReadAllText($ManifestFile.FullName, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if (($Manifest.schemaVersion -isnot [int] -and $Manifest.schemaVersion -isnot [long]) -or $Manifest.schemaVersion -ne 1) { throw 'Unsupported manifest schema.' }
    $Seen = @{}
    foreach ($Entry in $Manifest.files) {
        if ($Entry.path -isnot [string]) { throw 'Manifest path must be a string.' }
        $Path = $Entry.path
        if ($Seen.ContainsKey($Path)) { throw "Duplicate manifest path: $Path" }
        $Seen[$Path] = $true
        if ($Path -ne 'checksums.sha256' -and $PayloadPaths -cnotcontains $Path) { throw "Unexpected manifest file: $Path" }
        $File = Get-SafeFile $Path
        if (($Entry.size -isnot [int] -and $Entry.size -isnot [long]) -or $Entry.size -lt 0 -or $File.Length -ne $Entry.size) { throw "Size mismatch: $Path" }
        if ($Entry.sha256 -isnot [string] -or [string]$Entry.sha256 -cnotmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne [string]$Entry.sha256) {
            throw "Manifest checksum mismatch: $Path"
        }
    }
    if ($Seen.Count -ne $PayloadPaths.Count + 1 -or -not $Seen.ContainsKey('checksums.sha256')) { throw 'Incomplete manifest file list.' }
    # 展開直後のキットでは一覧外ファイルも拒否する。
    foreach ($Item in Get-ChildItem -LiteralPath $script:Root -Recurse -Force) {
        if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Linked item: $($Item.FullName)" }
        if ($Item.PSIsContainer) { continue }
        $Relative = $Item.FullName.Substring($script:Root.TrimEnd([char[]]'\/').Length + 1).Replace('\', '/')
        if ($Relative -ne 'manifest.json' -and $Relative -ne 'manifest.sha256' -and -not $Seen.ContainsKey($Relative)) {
            throw "Unlisted file: $Relative"
        }
    }
    Write-Output '整合性を確認しました。出所は信頼できる別経路のZIP SHA-256と照合してください。'
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
