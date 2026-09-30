$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Version = (Get-Content -Path (Join-Path $Root "VERSION") -Raw).Trim()
if (-not $Version) { throw "VERSION file is empty" }

Write-Host "Building $Version"

# Build in a clean virtualenv with a sanitized PATH.
# PyInstaller collects DLLs from PATH and packages from global site-packages. A foreign icuuc.dll
# (e.g. from poppler) shadows the Windows one and breaks the frozen app with
# "DLL load failed while importing QtCore"; it also drags in scipy and other unrelated packages.
$Venv = Join-Path $Root ".venv-build"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& $VenvPy -m pip install -q --upgrade pip
& $VenvPy -m pip install -q -r (Join-Path $Root "requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$Dist = Join-Path $Root "dist"
$InstallerDir = Join-Path $Dist "installer"
New-Item -ItemType Directory -Force -Path $Dist, $InstallerDir | Out-Null

$OldPath = $env:PATH
$env:PATH = "$(Join-Path $Venv 'Scripts');$env:SystemRoot\System32;$env:SystemRoot"
try {
    & $VenvPy -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\rdp_optimizer.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally {
    $env:PATH = $OldPath
}

# Self-test the frozen app: it must really load Qt and all app modules, otherwise no installer is produced.
# RunAsInvoker avoids the UAC prompt from the requireAdministrator manifest; 90s limit so an
# unhandled-exception dialog cannot hang the build.
$Exe = Join-Path $Dist "RdpOptimizer\RdpOptimizer.exe"
$SelfOut = Join-Path $Dist "selftest.txt"
Remove-Item $SelfOut -ErrorAction SilentlyContinue
$env:__COMPAT_LAYER = "RunAsInvoker"
try {
    $proc = Start-Process -FilePath $Exe -ArgumentList "--selftest", "`"$SelfOut`"" -PassThru -WindowStyle Hidden
    if (-not $proc.WaitForExit(90000)) {
        $proc | Stop-Process -Force
        throw "Frozen self-test timed out (likely an unhandled-exception dialog)"
    }
} finally {
    Remove-Item Env:\__COMPAT_LAYER -ErrorAction SilentlyContinue
}
$SelfMsg = if (Test-Path $SelfOut) { (Get-Content $SelfOut -Raw).Trim() } else { "(no output, exit code $($proc.ExitCode))" }
if ($proc.ExitCode -ne 0 -or $SelfMsg -notlike "SELFTEST OK*") { throw "Frozen self-test failed: $SelfMsg" }
Write-Host $SelfMsg

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
