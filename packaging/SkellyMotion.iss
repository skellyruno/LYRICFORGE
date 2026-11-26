; Single-file Windows installer for the previously verified PyInstaller onedir runtime.
; Compiler: Inno Setup 6. The application and models keep separate lifecycles.
[Setup]
AppId={{E0A0BC56-A87F-4C67-82FA-1713D23D3C95}
AppName=SkellyMotion
AppVersion=0.9.0
AppPublisher=Skell Audio
DefaultDirName={localappdata}\Programs\SkellyMotion
DefaultGroupName=SkellyMotion
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\static\skull.ico
UninstallDisplayIcon={app}\SkellyMotion.exe
OutputDir=..\dist\installer
OutputBaseFilename=SkellyMotion-Setup
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no

[Files]
Source: "..\dist\SkellyMotion\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{autoprograms}\SkellyMotion"; Filename: "{app}\SkellyMotion.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\SkellyMotion"; Filename: "{app}\SkellyMotion.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\SkellyMotion.exe"; Description: "Launch SkellyMotion"; Flags: nowait postinstall skipifsilent

; Intentionally no [UninstallDelete] or [InstallDelete]: projects, caches and
; recorded media live outside {app} and are not touched by setup/uninstall.
