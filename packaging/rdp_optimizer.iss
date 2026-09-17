; 远程桌面连接优化器 — Inno Setup
#ifndef MyAppVersion
#define MyAppVersion "1.5.0"
#endif
#define MyAppName "远程桌面连接优化器"
#define MyAppExeName "RdpOptimizer.exe"

[Setup]
AppId={{A8F3C2E1-9D47-4B6A-8E21-1C9F0D4B7A55}
AppName={#MyAppName} {#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=cr20085361
AppPublisherURL=https://github.com/cr20085361/Remote-Desktop-Connection-Optimizer
AppSupportURL=https://github.com/cr20085361/Remote-Desktop-Connection-Optimizer/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=RdpOptimizer-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName} {#MyAppVersion}
VersionInfoProductVersion={#MyAppVersion}
SetupLogging=no
WizardStyle=modern
UsePreviousAppDir=yes

[InstallDelete]
Type: files; Name: "{autodesktop}\远程桌面连接优化器 *.lnk"
Type: files; Name: "{group}\远程桌面连接优化器 *.lnk"

[Files]
Source: "..\dist\RdpOptimizer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#MyAppName} {#MyAppVersion}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} {#MyAppVersion}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName} {#MyAppVersion}"; Flags: nowait postinstall skipifsilent
