; Inno Setup script for ExamLoader for Exam.net. Run via: .\build.ps1 -Installer
; build.ps1 passes /DAppVersion=<examnet.__version__>; the app itself must already be built in dist\ExamLoader.
;
; Per-user install (no admin rights): installs to %LOCALAPPDATA%\Programs\ExamLoader for Exam.net.
; Uninstalling keeps the user's data in %LOCALAPPDATA%\ExamLoader (logs, browser profile with the Exam.net login).

#ifndef AppVersion
  #error AppVersion must be passed on the command line, e.g. /DAppVersion=1.0.0
#endif

#define AppName "ExamLoader for Exam.net"
#define AppExe "ExamLoader.exe"
#define AppUrl "https://github.com/MrHoran8120/ExamLoader-examdotnet"

[Setup]
; Never change AppId: it is how Windows recognises upgrades of the same app.
AppId={{19BC0B74-3A45-49EF-BC2D-6EA4A1B1D22A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=ExamLoader (independent; not affiliated with Exam.net)
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
SourceDir=..
OutputDir=dist
OutputBaseFilename=ExamLoader-examdotnet-setup-{#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\ExamLoader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; On upgrade, clear the previous build's bundled files so none are left over from an older version.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent
