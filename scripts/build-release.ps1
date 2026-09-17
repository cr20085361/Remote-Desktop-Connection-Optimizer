$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Version = (Get-Content -Path (Join-Path $Root "VERSION") -Raw).Trim()
if (-not $Version) { throw "VERSION file is empty" }

Write-Host "Building $Version"

python -m pip install -q -r (Join-Path $Root "requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$Dist = Join-Path $Root "dist"
$InstallerDir = Join-Path $Dist "installer"
New-Item -ItemType Directory -Force -Path $Dist, $InstallerDir | Out-Null

python -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\rdp_optimizer.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Iss = Join-Path $Root "packaging\rdp_optimizer.iss"
$Utf8Bom = New-Object System.Text.UTF8Encoding $true
$IssText = [System.IO.File]::ReadAllText($Iss)
if (-not $IssText.StartsWith([char]0xFEFF)) {
    [System.IO.File]::WriteAllText($Iss, $IssText, $Utf8Bom)
}

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 7\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$Setup = Join-Path $InstallerDir "RdpOptimizer-Setup-$Version.exe"
if ($Iscc) {
    & $Iscc "/DMyAppVersion=$Version" $Iss
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
} else {
    Write-Warning "Inno Setup 6 not found. Portable folder is dist\RdpOptimizer. Install Inno Setup to build RdpOptimizer-Setup-$Version.exe"
}

python (Join-Path $Root "scripts\write_latest_json.py") --version $Version --setup $Setup --out (Join-Path $Dist "latest.json")
if ($LASTEXITCODE -ne 0) { throw "latest.json failed" }

Write-Host "Done. Portable: dist\RdpOptimizer"
if (Test-Path $Setup) { Write-Host "Installer: $Setup" }
Write-Host "Manifest: dist\latest.json"
