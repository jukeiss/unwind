; Inno Setup script: builds Unwind-Setup-x64.exe from the PyInstaller output in dist\Unwind.
; Installs per user (no admin prompt). Built by .github/workflows/release.yml.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7B4C4C1E-5E1D-4A57-9C3B-0D5A5E1B9A21}
AppName=Unwind
AppVersion={#AppVersion}
AppPublisher=jukeiss
AppPublisherURL=https://github.com/jukeiss/unwind
DefaultDirName={localappdata}\Programs\Unwind
DefaultGroupName=Unwind
PrivilegesRequired=lowest
OutputDir=..\..\out
OutputBaseFilename=Unwind-Setup-x64
SetupIconFile=..\..\build\icon.ico
UninstallDisplayIcon={app}\Unwind.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\Unwind\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Unwind"; Filename: "{app}\Unwind.exe"
Name: "{group}\Uninstall Unwind"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Unwind"; Filename: "{app}\Unwind.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Unwind.exe"; Description: "Start Unwind now"; Flags: nowait postinstall skipifsilent
