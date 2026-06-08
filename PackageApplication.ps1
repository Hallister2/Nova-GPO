param(
    [string]$Version,
    [switch]$SkipInstaller,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$AppInitPath = Join-Path $ProjectRoot "app\__init__.py"
$IssPath = Join-Path $ProjectRoot "NovaGPO.iss"
$SpecPath = Join-Path $ProjectRoot "Nova GPO.spec"
$DistPath = Join-Path $ProjectRoot "dist"
$ExePath = Join-Path $DistPath "Nova GPO.exe"
$InstallerPath = Join-Path $DistPath "installer"

function Get-AppVersion {
    $match = Select-String -Path $AppInitPath -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $match) {
        throw "Could not find __version__ in app\__init__.py."
    }
    return $match.Matches[0].Groups[1].Value
}

function Set-AppVersion {
    param([string]$NewVersion)

    if (-not ($NewVersion -match '^\d+(\.\d+){1,3}$')) {
        throw "Version '$NewVersion' is not a supported version string. Use values like 0.2, 1.0.0, or 1.0.0.1."
    }

    $content = Get-Content -Path $AppInitPath -Raw
    $content = $content -replace '__version__\s*=\s*"[^"]+"', "__version__ = `"$NewVersion`""
    Set-Content -Path $AppInitPath -Value $content -Encoding UTF8
}

function Sync-InnoVersion {
    param([string]$AppVersion)

    $issContent = Get-Content -Path $IssPath -Raw
    $issContent = $issContent -replace '#define MyAppVersion ".+?"', "#define MyAppVersion `"$AppVersion`""
    Set-Content -Path $IssPath -Value $issContent -Encoding UTF8
}

function Find-InnoCompiler {
    $commands = @("iscc.exe", "iscc")
    foreach ($command in $commands) {
        $candidate = Get-Command $command -ErrorAction SilentlyContinue
        if ($candidate) {
            return $candidate.Source
        }
    }

    $defaultPath = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $defaultPath) {
        return $defaultPath
    }

    return $null
}

function New-Sha256File {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Cannot create checksum because '$Path' was not found."
    }

    $hash = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $fileName = Split-Path -Path $Path -Leaf
    $checksumPath = "$Path.sha256"
    "$hash  $fileName" | Set-Content -Path $checksumPath -Encoding ascii
    return $checksumPath
}

if ($Version) {
    Write-Host "Updating app version to $Version"
    Set-AppVersion -NewVersion $Version
}

$AppVersion = Get-AppVersion
Write-Host "Nova GPO version: $AppVersion"

Write-Host "Syncing NovaGPO.iss version metadata"
Sync-InnoVersion -AppVersion $AppVersion

if (-not $NoClean) {
    Write-Host "Cleaning build output"
    Remove-Item -Recurse -Force -LiteralPath ".\build", ".\dist", ".\installer" -ErrorAction SilentlyContinue
}

Write-Host "Building one-file executable with PyInstaller"
if (Test-Path $SpecPath) {
    python -m PyInstaller $SpecPath --clean --noconfirm
}
else {
    python -m PyInstaller --noconsole --onefile --icon ".\assets\Nova GPO - Icon.ico" --name "Nova GPO" --paths "." --collect-submodules app main.py --clean --noconfirm
}

if (-not (Test-Path $ExePath)) {
    throw "PyInstaller finished, but '$ExePath' was not created."
}

New-Item -ItemType Directory -Path $InstallerPath -Force | Out-Null

if ($SkipInstaller) {
    Write-Host "Skipping Inno Setup installer build."
}
else {
    $InnoCompiler = Find-InnoCompiler
    if (-not $InnoCompiler) {
        throw "Inno Setup compiler was not found. Install Inno Setup 6 or rerun with -SkipInstaller."
    }

    Write-Host "Building installer with Inno Setup"
    & $InnoCompiler $IssPath

    $ExpectedInstaller = Join-Path $InstallerPath "NovaGPOSetup_$AppVersion.exe"
    if (-not (Test-Path $ExpectedInstaller)) {
        throw "Inno Setup finished, but '$ExpectedInstaller' was not created."
    }

    Write-Host "Generating installer SHA-256 checksum"
    $ChecksumPath = New-Sha256File -Path $ExpectedInstaller
}

Write-Host ""
Write-Host "Package complete"
Write-Host "EXE: $ExePath"
if (-not $SkipInstaller) {
    Write-Host "Installer: $(Join-Path $InstallerPath "NovaGPOSetup_$AppVersion.exe")"
    Write-Host "Checksum: $ChecksumPath"
    Write-Host ""
    Write-Host "Upload both the installer and checksum file to the GitHub release."
}
