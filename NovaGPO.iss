#define MyAppName "Nova GPO"
; Synced from app\__init__.py by PackageApplication.ps1.
#define MyAppVersion "0.9.4"
#define MyAppPublisher "Hallister Labs"
#define MyAppExeName "Nova GPO.exe"

[Setup]
AppId={{7E4A6E8D-6D1C-4E1D-8E9A-4E37C9C6A8B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://hallisterlabs.com
AppSupportURL=https://github.com/Hallister2/Nova-GPO
AppUpdatesURL=https://github.com/Hallister2/Nova-GPO
DefaultDirName={autopf}\Hallister Labs\Nova GPO
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
SetupLogging=yes
OutputDir=dist\installer
OutputBaseFilename=NovaGPOSetup_{#MyAppVersion}
SetupIconFile=assets\Nova GPO - Icon.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Dirs]
Name: "{commonappdata}\Hallister Labs\Nova GPO\Runtime"; Permissions: users-modify

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Description: "Launch {#MyAppName}"; Flags: shellexec nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\Hallister Labs\Nova GPO\Runtime"































