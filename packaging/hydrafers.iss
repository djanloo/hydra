; Inno Setup script — wraps the PyInstaller onedir bundle into a Windows installer.
;
; Build first with packaging\build_windows.bat (produces dist\hydrafers\), then:
;     ISCC packaging\hydrafers.iss
; Output: dist\HydraFERS-Setup-<version>.exe

#define MyAppName "HydraFERS"
#define MyAppVersion "0.0.4"
#define MyAppPublisher "CAEN"
#define MyAppExeName "hydrafers.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=HydraFERS-Setup-{#MyAppVersion}
SetupIconFile=..\src\hydrafers\gui\imgs\hydrafers.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The entire PyInstaller onedir output (exe + _internal\).
Source: "..\dist\hydrafers\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
