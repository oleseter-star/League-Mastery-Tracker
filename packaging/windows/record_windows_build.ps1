<#
.SYNOPSIS
Builds LeagueMasteryTracker.exe with PyInstaller and records build evidence.

.DESCRIPTION
Runs one PyInstaller build from a clean Git working tree and writes the
evidence that docs/STEP10_WINDOWS_ACCEPTANCE_HANDOFF.md asks for:
Windows and Python versions, commit, spec, command, start and end time,
exit code, warning count, executable path and size, SHA-256, version
metadata, and the PE subsystem that decides whether a console window opens.

The application icon is not verified here; confirm it in File Explorer.

Run from the repository root with the project virtual environment active:

    powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\record_windows_build.ps1

Evidence is written below build\windows-build-evidence\, which Git ignores.
The script exits with a nonzero status when the build or any check fails.
#>
[CmdletBinding()]
param(
    [ValidateSet("LeagueMasteryTracker-onefile.spec", "LeagueMasteryTracker.spec")]
    [string] $Spec = "LeagueMasteryTracker-onefile.spec",

    [string] $Python = "python",

    [switch] $RemovePriorOutput,

    [switch] $AllowDirtyTree
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $RepositoryRoot

function Invoke-Captured {
    param(
        [string] $FilePath,
        [string[]] $Arguments,
        [string] $StandardOutputPath,
        [string] $StandardErrorPath
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $StandardOutputPath `
        -RedirectStandardError $StandardErrorPath
    return $process.ExitCode
}

function Get-CommandOutput {
    param(
        [string] $FilePath,
        [string[]] $Arguments
    )

    $output = & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
    return ($output -join "`n").Trim()
}

function Get-PortableExecutableInfo {
    param([string] $Path)

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $header = New-Object byte[] 4096
        $read = $stream.Read($header, 0, $header.Length)
    }
    finally {
        $stream.Dispose()
    }

    if ($read -lt 64 -or $header[0] -ne 0x4D -or $header[1] -ne 0x5A) {
        throw "Not a PE executable: $Path"
    }
    $peOffset = [System.BitConverter]::ToInt32($header, 0x3C)
    if ($peOffset -lt 0 -or ($peOffset + 24 + 70) -gt $read) {
        throw "PE header is outside the inspected range: $Path"
    }
    if ($header[$peOffset] -ne 0x50 -or $header[$peOffset + 1] -ne 0x45 -or
        $header[$peOffset + 2] -ne 0 -or $header[$peOffset + 3] -ne 0) {
        throw "Missing PE signature: $Path"
    }

    $machine = [System.BitConverter]::ToUInt16($header, $peOffset + 4)
    $optionalHeader = $peOffset + 24
    $subsystem = [System.BitConverter]::ToUInt16($header, $optionalHeader + 68)

    $machineName = switch ($machine) {
        0x8664 { "x64" }
        0x014C { "x86" }
        0xAA64 { "ARM64" }
        default { "0x{0:X4}" -f $machine }
    }
    $subsystemName = switch ($subsystem) {
        2 { "Windows GUI (no console window)" }
        3 { "Windows console" }
        default { "Other ($subsystem)" }
    }

    return [pscustomobject]@{
        Machine       = $machineName
        Subsystem     = $subsystem
        SubsystemName = $subsystemName
    }
}

$failures = New-Object System.Collections.Generic.List[string]

# Source gate: a clean tree ties the executable to exactly one commit.
$commit = Get-CommandOutput "git" @("rev-parse", "HEAD")
$treeStatus = Get-CommandOutput "git" @("status", "--porcelain", "--untracked-files=all")
if ($treeStatus) {
    if ($AllowDirtyTree) {
        Write-Warning "Working tree is not clean; evidence will record it."
    }
    else {
        throw "Working tree is not clean. Commit or remove these changes first:`n$treeStatus"
    }
}

$metadataJson = Get-CommandOutput $Python @(
    "-B",
    "-c",
    "import dataclasses, json; from pyinstaller_build_metadata import load_application_build_metadata as load; print(json.dumps(dataclasses.asdict(load())))"
)
$metadata = $metadataJson | ConvertFrom-Json

$executableRelativePath = "dist\$($metadata.windows_executable_name)"
$executablePath = Join-Path $RepositoryRoot $executableRelativePath

if (Test-Path -LiteralPath $executablePath) {
    if (-not $RemovePriorOutput) {
        throw "Prior build output exists at $executableRelativePath. Record or move it, or rerun with -RemovePriorOutput."
    }
    $priorHash = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash
    Write-Host "Removing prior $executableRelativePath (SHA-256 $priorHash)."
    Remove-Item -LiteralPath $executablePath
}

$pythonVersion = Get-CommandOutput $Python @("-c", "import sys; print(sys.version.split()[0])")
$pythonArchitecture = Get-CommandOutput $Python @("-c", "import platform; print(platform.architecture()[0])")
$pyInstallerVersion = Get-CommandOutput $Python @("-m", "PyInstaller", "--version")

$windowsVersion = [System.Environment]::OSVersion.VersionString
if ($env:OS -eq "Windows_NT") {
    $operatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
    $windowsVersion = "$($operatingSystem.Caption) $($operatingSystem.Version) build $($operatingSystem.BuildNumber)"
}

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$evidenceDirectory = Join-Path $RepositoryRoot "build\windows-build-evidence\$stamp"
New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
$standardOutputLog = Join-Path $evidenceDirectory "pyinstaller-stdout.log"
$standardErrorLog = Join-Path $evidenceDirectory "pyinstaller-stderr.log"

$buildArguments = @("-m", "PyInstaller", "--clean", "--noconfirm", $Spec)
$command = "$Python $($buildArguments -join ' ')"

Write-Host "Building $Spec at commit $commit ..."
$startTime = (Get-Date).ToUniversalTime()
$exitCode = Invoke-Captured `
    -FilePath $Python `
    -Arguments $buildArguments `
    -StandardOutputPath $standardOutputLog `
    -StandardErrorPath $standardErrorLog
$endTime = (Get-Date).ToUniversalTime()

$buildLog = @(Get-Content -LiteralPath $standardOutputLog) + @(Get-Content -LiteralPath $standardErrorLog)
$warningLines = @($buildLog | Where-Object { $_ -match "\bWARNING:" })

if ($exitCode -ne 0) {
    $failures.Add("PyInstaller exited with code $exitCode; see $standardErrorLog")
}

$executableSize = $null
$sha256 = $null
$versionMetadata = $null
$portableExecutable = $null

if (Test-Path -LiteralPath $executablePath) {
    $executableItem = Get-Item -LiteralPath $executablePath
    $executableSize = $executableItem.Length
    $sha256 = (Get-FileHash -LiteralPath $executablePath -Algorithm SHA256).Hash
    $portableExecutable = Get-PortableExecutableInfo -Path $executablePath

    if ($portableExecutable.Subsystem -ne 2) {
        $failures.Add("Executable subsystem is $($portableExecutable.SubsystemName); a console-free build requires Windows GUI.")
    }
    if ($portableExecutable.Machine -ne "x64") {
        $failures.Add("Executable machine is $($portableExecutable.Machine); expected x64.")
    }

    $versionInfo = $executableItem.VersionInfo
    $versionMetadata = [ordered]@{
        ProductName      = $versionInfo.ProductName
        ProductVersion   = $versionInfo.ProductVersion
        FileDescription  = $versionInfo.FileDescription
        FileVersion      = $versionInfo.FileVersion
        InternalName     = $versionInfo.InternalName
        OriginalFilename = $versionInfo.OriginalFilename
    }
    $expectedVersionMetadata = [ordered]@{
        ProductName      = $metadata.product_name
        ProductVersion   = $metadata.product_version
        FileDescription  = $metadata.file_description
        FileVersion      = $metadata.file_version
        InternalName     = $metadata.internal_name
        OriginalFilename = $metadata.original_filename
    }
    if ($env:OS -eq "Windows_NT") {
        foreach ($field in $expectedVersionMetadata.Keys) {
            if ($versionMetadata[$field] -ne $expectedVersionMetadata[$field]) {
                $failures.Add("Version metadata $field is '$($versionMetadata[$field])'; expected '$($expectedVersionMetadata[$field])'.")
            }
        }
    }
}
else {
    $failures.Add("Expected executable is missing: $executableRelativePath")
}

$machine = $null
$subsystem = $null
if ($portableExecutable) {
    $machine = $portableExecutable.Machine
    $subsystem = $portableExecutable.SubsystemName
}

$evidence = [ordered]@{
    windows_version        = $windowsVersion
    python_version         = "$pythonVersion ($pythonArchitecture)"
    pyinstaller_version    = $pyInstallerVersion
    commit                 = $commit
    working_tree_clean     = -not [bool] $treeStatus
    spec                   = $Spec
    command                = $command
    start_time_utc         = $startTime.ToString("o")
    end_time_utc           = $endTime.ToString("o")
    duration_seconds       = [math]::Round(($endTime - $startTime).TotalSeconds, 1)
    exit_code              = $exitCode
    warning_count          = $warningLines.Count
    executable_path        = $executableRelativePath
    executable_size_bytes  = $executableSize
    sha256                 = $sha256
    version_metadata       = $versionMetadata
    machine                = $machine
    subsystem              = $subsystem
    icon_result            = "Not checked by this script; confirm in File Explorer."
    failures               = @($failures)
}

$evidencePath = Join-Path $evidenceDirectory "evidence.json"
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $evidencePath -Encoding UTF8

$warningPath = Join-Path $evidenceDirectory "pyinstaller-warnings.txt"
Set-Content -LiteralPath $warningPath -Value $warningLines -Encoding UTF8

$versionSummary = "n/a"
if ($versionMetadata) {
    $versionSummary = "$($versionMetadata.ProductName) $($versionMetadata.ProductVersion) / file $($versionMetadata.FileVersion)"
}
$row = "| {0} | {1} | {2} | {3} | ``{4}`` | {5} to {6} | {7} | {8} | {9} | {10} | {11} | {12} | (check in Explorer) | {13} |" -f `
    $windowsVersion,
    $evidence.python_version,
    $commit.Substring(0, 12),
    $Spec,
    $command,
    $startTime.ToString("u"),
    $endTime.ToString("u"),
    $exitCode,
    $warningLines.Count,
    $executableRelativePath,
    $executableSize,
    $sha256,
    $versionSummary,
    $evidence.subsystem
$rowPath = Join-Path $evidenceDirectory "evidence-row.md"
Set-Content -LiteralPath $rowPath -Value $row -Encoding UTF8

Write-Host ""
Write-Host "Evidence directory: $evidenceDirectory"
Write-Host "Build evidence row for the handoff table:"
Write-Host $row

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Build checks failed:"
    foreach ($failure in $failures) {
        Write-Host " - $failure"
    }
    exit 1
}

Write-Host ""
Write-Host "Build checks passed. Confirm the icon in File Explorer before recording the row."
exit 0
