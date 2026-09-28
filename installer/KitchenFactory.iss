#define MyAppName "Kitchen Factory"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Anton George Stoffberg"
#define MyAppExeName "KitchenFactory.exe"

[Setup]
AppId={{7C3FA9F9-8B35-4A9D-9E6E-1F7B8C4B1B01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Kitchen Factory
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=KitchenFactorySetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\KitchenFactory.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Kitchen Factory"; Flags: nowait postinstall skipifsilent
