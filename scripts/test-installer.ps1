param([Parameter(Mandatory = $true)][string]$Version)
# Installer smoke test (no admin, no UAC, does not touch the real install):
#  1. compile a throwaway per-user variant of the installer (different AppId, PrivilegesRequired=lowest)
#  2. plant an "old install" containing stale files that an earlier build shipped
#  3. install over it silently and assert the stale files are gone
#  4. launch the installed app and assert its window opens (no "Unhandled exception" dialog)
#  5. uninstall the throwaway copy again
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 7\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup not found" }

$Work = Join-Path $Root "dist\installer-test"
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force -Path (Join-Path $Work "out") | Out-Null

$Packaging = Join-Path $Root "packaging"
$Variant = Join-Path $Packaging "_test_installer.iss"
$text = [System.IO.File]::ReadAllText((Join-Path $Packaging "rdp_optimizer.iss"))
$text = $text -replace 'PrivilegesRequired=admin', 'PrivilegesRequired=lowest'
$text = $text -replace 'AppId=\{\{[0-9A-Fa-f-]+\}', 'AppId={{B1B1B1B1-0000-4000-8000-00000000AA55}'
$text = $text -replace 'OutputDir=.*', ("OutputDir=" + (Join-Path $Work "out"))
$text = $text -replace 'OutputBaseFilename=.*', 'OutputBaseFilename=test-setup'
[System.IO.File]::WriteAllText($Variant, $text, (New-Object System.Text.UTF8Encoding $true))
try {
    & $Iscc "/DMyAppVersion=$Version" /Q $Variant | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "test installer compile failed" }
} finally {
    Remove-Item $Variant -ErrorAction SilentlyContinue
}

$Target = Join-Path $Work "app"
New-Item -ItemType Directory -Force -Path (Join-Path $Target "_internal\scipy") | Out-Null
Set-Content (Join-Path $Target "_internal\icuuc.dll") "stale file from an older build"
Set-Content (Join-Path $Target "_internal\scipy\stale.txt") "stale file from an older build"

$setup = Start-Process -FilePath (Join-Path $Work "out\test-setup.exe") -PassThru -Wait -ArgumentList `
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$Target`""
if ($setup.ExitCode -ne 0) { throw "test install failed, exit code $($setup.ExitCode)" }

try {
    foreach ($stale in @("_internal\icuuc.dll", "_internal\scipy")) {
        if (Test-Path (Join-Path $Target $stale)) { throw "stale file survived the upgrade: $stale" }
    }
    $Exe = Join-Path $Target "RdpOptimizer.exe"
    if (-not (Test-Path $Exe)) { throw "installed exe missing" }

    $env:__COMPAT_LAYER = "RunAsInvoker"
    $app = Start-Process -FilePath $Exe -PassThru
    $title = ""
    for ($i = 0; $i -lt 40 -and -not ($title -like "*$Version*"); $i++) {
        Start-Sleep -Milliseconds 750
        $live = Get-Process -Id $app.Id -ErrorAction SilentlyContinue
        if (-not $live) { throw "installed app exited right after start" }
        $title = $live.MainWindowTitle
        if ($title -like "*Unhandled*") { throw "installed app shows an unhandled-exception dialog: $title" }
    }
    if (-not ($title -like "*$Version*")) { throw "installed app window did not appear (title: '$title')" }
    Write-Host "Installer test OK: stale files removed, app window '$title' opened"
} finally {
    $env:__COMPAT_LAYER = $null
    Get-Process RdpOptimizer -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "$Target*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
    $un = Get-ChildItem $Target -Filter "unins*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($un) { Start-Process -FilePath $un.FullName -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait }
}
