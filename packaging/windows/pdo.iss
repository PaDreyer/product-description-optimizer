#ifndef MyAppVersion
  #error MyAppVersion must be passed to ISCC
#endif

#define MyAppName "Product Description Optimizer"
#define MyAppExeName "PDO.exe"

[Setup]
AppId={{5A06BB72-7AB3-4A18-9120-8C63A837548E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=PDO contributors
DefaultDirName={localappdata}\Programs\PDO
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=PDO-Setup-{#MyAppVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\PDO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Product Description Optimizer"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Product Description Optimizer"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start Product Description Optimizer"; Flags: nowait postinstall skipifsilent
