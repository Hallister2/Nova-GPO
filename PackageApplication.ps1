param(
    [string]$Version,
    [switch]$SkipInstaller,
    [switch]$NoClean,
    [switch]$Sign,
    [switch]$NoSign,
    [string]$CertificateThumbprint,
    [string]$CertificateSubject,
    [string]$CertificatePath,
    [string]$CertificatePassword,
    [string]$TimestampUrl = "http://time.certum.pl",
    [ValidateSet("Authenticode", "RFC3161")]
    [string]$TimestampMode = "Authenticode",
    [string]$SignToolPath,
    [switch]$SkipSignatureVerify
)

# Smart-card signing is automatic when the known Certum cert is detected.
# Use -NoSign to suppress signing, or pass an explicit certificate selector to override auto-detection.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$AppInitPath = Join-Path $ProjectRoot "app\__init__.py"
$IssPath = Join-Path $ProjectRoot "NovaGPO.iss"
$SpecPath = Join-Path $ProjectRoot "Nova GPO.spec"
$DistPath = Join-Path $ProjectRoot "dist"
$ExePath = Join-Path $DistPath "Nova GPO.exe"
$InstallerPath = Join-Path $DistPath "installer"
$DefaultCodeSigningThumbprints = @(
    "624774EDC0B147597C887FB7A3431F3B68CA4EE3"
)
$SigningPlan = [PSCustomObject]@{
    Enabled = $false
    Type = "None"
    Value = $null
    Password = $null
    Reason = "Not resolved"
}
$ResolvedSignToolPath = $null

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

function Find-SignTool {
    if ($SignToolPath) {
        if (-not (Test-Path $SignToolPath)) {
            throw "The specified SignTool path was not found: $SignToolPath"
        }
        return $SignToolPath
    }

    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "${env:ProgramFiles}\Windows Kits\10\bin"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $candidates = @()
    foreach ($root in $roots) {
        $candidates += Get-ChildItem -Path $root -Filter "signtool.exe" -Recurse -ErrorAction SilentlyContinue
    }

    if ($candidates.Count -gt 0) {
        $x64 = $candidates | Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } | Sort-Object FullName -Descending | Select-Object -First 1
        if ($x64) {
            return $x64.FullName
        }

        return ($candidates | Sort-Object FullName -Descending | Select-Object -First 1).FullName
    }

    return $null
}

function Test-SignedFile {
    param([string]$Path)

    if ($SkipSignatureVerify) {
        return
    }

    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne "Valid") {
        throw "Signature verification failed for '$Path': $($signature.Status) $($signature.StatusMessage)"
    }
}

function Get-CodeSigningCertificates {
    try {
        $now = Get-Date
        return @(Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction Stop | Where-Object { $_.HasPrivateKey -and $_.NotAfter -gt $now })
    }
    catch {
        return @()
    }
}

function Resolve-CodeSigningPlan {
    if ($NoSign) {
        return [PSCustomObject]@{
            Enabled = $false
            Type = "None"
            Value = $null
            Password = $null
            Reason = "Disabled with -NoSign."
        }
    }

    $resolvedThumbprint = $CertificateThumbprint
    if (-not $resolvedThumbprint -and $env:NOVA_GPO_CERT_THUMBPRINT) {
        $resolvedThumbprint = $env:NOVA_GPO_CERT_THUMBPRINT
    }

    $resolvedSubject = $CertificateSubject
    if (-not $resolvedSubject -and $env:NOVA_GPO_CERT_SUBJECT) {
        $resolvedSubject = $env:NOVA_GPO_CERT_SUBJECT
    }

    $resolvedCertificatePath = $CertificatePath
    if (-not $resolvedCertificatePath -and $env:NOVA_GPO_CERT_PATH) {
        $resolvedCertificatePath = $env:NOVA_GPO_CERT_PATH
    }

    $resolvedPassword = $CertificatePassword
    if (-not $resolvedPassword -and $env:NOVA_GPO_CERT_PASSWORD) {
        $resolvedPassword = $env:NOVA_GPO_CERT_PASSWORD
    }

    if ($resolvedCertificatePath) {
        if (-not (Test-Path $resolvedCertificatePath)) {
            throw "Certificate file was not found: $resolvedCertificatePath"
        }

        return [PSCustomObject]@{
            Enabled = $true
            Type = "Pfx"
            Value = $resolvedCertificatePath
            Password = $resolvedPassword
            Reason = "Using explicit certificate file."
        }
    }

    $certificates = Get-CodeSigningCertificates

    if ($resolvedThumbprint) {
        $normalizedThumbprint = $resolvedThumbprint -replace "\s", ""
        $certificate = $certificates | Where-Object { $_.Thumbprint -eq $normalizedThumbprint } | Select-Object -First 1
        if ($certificate) {
            return [PSCustomObject]@{
                Enabled = $true
                Type = "Thumbprint"
                Value = $normalizedThumbprint
                Password = $null
                Reason = "Using explicit certificate thumbprint."
            }
        }

        if ($Sign) {
            throw "Code signing was requested, but certificate thumbprint '$normalizedThumbprint' was not found in Cert:\CurrentUser\My."
        }
    }

    if ($resolvedSubject) {
        $certificate = $certificates | Where-Object { $_.Subject -like "*$resolvedSubject*" } | Sort-Object NotAfter -Descending | Select-Object -First 1
        if ($certificate) {
            return [PSCustomObject]@{
                Enabled = $true
                Type = "Subject"
                Value = $resolvedSubject
                Password = $null
                Reason = "Using explicit certificate subject."
            }
        }

        if ($Sign) {
            throw "Code signing was requested, but no code-signing certificate matched subject '$resolvedSubject' in Cert:\CurrentUser\My."
        }
    }

    foreach ($thumbprint in $DefaultCodeSigningThumbprints) {
        $normalizedThumbprint = $thumbprint -replace "\s", ""
        $certificate = $certificates | Where-Object { $_.Thumbprint -eq $normalizedThumbprint } | Select-Object -First 1
        if ($certificate) {
            return [PSCustomObject]@{
                Enabled = $true
                Type = "Thumbprint"
                Value = $normalizedThumbprint
                Password = $null
                Reason = "Auto-detected known Certum code-signing certificate."
            }
        }
    }

    if ($Sign) {
        return [PSCustomObject]@{
            Enabled = $true
            Type = "Auto"
            Value = $null
            Password = $null
            Reason = "Explicit -Sign requested; signtool will auto-select a certificate."
        }
    }

    return [PSCustomObject]@{
        Enabled = $false
        Type = "None"
        Value = $null
        Password = $null
        Reason = "No known code-signing certificate detected."
    }
}

function Invoke-CodeSigning {
    param([string]$Path)

    if (-not $SigningPlan.Enabled) {
        return
    }

    if (-not (Test-Path $Path)) {
        throw "Cannot sign '$Path' because it was not found."
    }

    $tool = $script:ResolvedSignToolPath
    if (-not $tool) {
        $tool = Find-SignTool
    }
    if (-not $tool) {
        throw "signtool.exe was not found. Install the Windows SDK, add signtool.exe to PATH, or pass -SignToolPath."
    }

    $signArgs = @("sign", "/v", "/fd", "SHA256")
    if ($TimestampUrl) {
        if ($TimestampMode -eq "RFC3161") {
            $signArgs += @("/tr", $TimestampUrl, "/td", "SHA256")
        }
        else {
            $signArgs += @("/t", $TimestampUrl)
        }
    }
    else {
        Write-Warning "Signing without a timestamp. The signature may not remain valid after the certificate expires."
    }

    if ($SigningPlan.Type -eq "Pfx") {
        $signArgs += @("/f", $SigningPlan.Value)
        if ($SigningPlan.Password) {
            $signArgs += @("/p", $SigningPlan.Password)
        }
    }
    elseif ($SigningPlan.Type -eq "Thumbprint") {
        $signArgs += @("/sha1", $SigningPlan.Value)
    }
    elseif ($SigningPlan.Type -eq "Subject") {
        $signArgs += @("/n", $SigningPlan.Value)
    }
    else {
        $signArgs += "/a"
    }

    $signArgs += $Path

    Write-Host "Signing $(Split-Path -Path $Path -Leaf)"
    & $tool @signArgs
    if ($LASTEXITCODE -ne 0) {
        throw "signtool.exe failed while signing '$Path'."
    }

    Test-SignedFile -Path $Path
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

$SigningPlan = Resolve-CodeSigningPlan
$ExplicitSigningRequested = $Sign -or $CertificateThumbprint -or $CertificateSubject -or $CertificatePath -or $env:NOVA_GPO_CERT_THUMBPRINT -or $env:NOVA_GPO_CERT_SUBJECT -or $env:NOVA_GPO_CERT_PATH
if ($SigningPlan.Enabled) {
    $script:ResolvedSignToolPath = Find-SignTool
    if (-not $script:ResolvedSignToolPath) {
        if ($ExplicitSigningRequested) {
            throw "Code signing is enabled, but signtool.exe was not found. Install the Windows SDK Signing Tools feature or pass -SignToolPath."
        }

        $SigningPlan.Enabled = $false
        $SigningPlan.Reason = "Auto-detected signing certificate, but signtool.exe was not found."
    }

    if ($SigningPlan.Enabled) {
        Write-Host "Code signing enabled: $($SigningPlan.Reason)"
        Write-Host "SignTool: $script:ResolvedSignToolPath"
    }
    else {
        Write-Host "Code signing skipped: $($SigningPlan.Reason)"
    }
}
else {
    Write-Host "Code signing skipped: $($SigningPlan.Reason)"
}

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

Invoke-CodeSigning -Path $ExePath

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

    Invoke-CodeSigning -Path $ExpectedInstaller

    Write-Host "Generating installer SHA-256 checksum"
    $ChecksumPath = New-Sha256File -Path $ExpectedInstaller
}

Write-Host ""
Write-Host "Package complete"
Write-Host "EXE: $ExePath"
if ($SigningPlan.Enabled) {
    Write-Host "Signing: enabled"
}
else {
    Write-Host "Signing: skipped"
}
if (-not $SkipInstaller) {
    Write-Host "Installer: $(Join-Path $InstallerPath "NovaGPOSetup_$AppVersion.exe")"
    Write-Host "Checksum: $ChecksumPath"
    Write-Host ""
    Write-Host "Upload both the installer and checksum file to the GitHub release."
}
