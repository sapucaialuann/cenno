; =============================================================================
;  Cenno - Windows installer (Inno Setup 6)
; =============================================================================
;  Build it with:      build_win.bat
;  (build_win.bat compiles the exe first, then runs ISCC on this script and
;   passes /DAppVersion=<version from the VERSION file>.)
;
;  By hand:            ISCC.exe /DAppVersion=0.2.0 installer\cenno.iss
;
;  What the user gets:
;    - a normal Windows installer (progress bar, folder picker, finish page)
;    - Cenno in the Start Menu, and a shortcut on the Desktop
;    - an entry in Settings > Apps > Installed apps, so it can be uninstalled
;    - the cenno:// URL handler registered, so "cenno://on" works right away
; =============================================================================

; The version is not written here on purpose: the VERSION file in the
; repository root is the only place it lives. build_win.bat reads it and
; passes it in. Compiling this file by hand means passing the version too:
;     ISCC.exe /DAppVersion=0.2.0 installer\cenno.iss
; (in the Inno Setup IDE: Parameters > "Parameters" > /DAppVersion=0.2.0)
#ifndef AppVersion
  #error AppVersion is not defined. Build with build_win.bat, or pass /DAppVersion=<version>.
#endif

#define AppName    "Cenno"
#define AppExe     "Cenno.exe"
#define AppShort   "Cenno"
#define Publisher  "Luann Sapucaia"
#define AppURL     "https://cennoapp.com"

[Setup]
; A stable AppId so that a new version replaces the old one instead of
; installing side by side.
AppId={{8F3C1B92-6D47-4E58-9A2C-71D5E0B34C6A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

VersionInfoVersion={#AppVersion}
VersionInfoCompany={#Publisher}
VersionInfoDescription={#AppName} - hand gesture control for Windows
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCopyright=Copyright (c) 2026 {#Publisher}

; Install per user by default (no UAC prompt: the everyday user just clicks
; Next). The "install for all users" button on the ready page offers the
; machine-wide install under Program Files instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

OutputDir=..\dist
OutputBaseFilename={#AppShort}-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; Cenno runs from the system tray: close it before uninstalling.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; The Start Menu shortcut is always created; the Desktop one is a choice, on by
; default because that is where people look for an app they just installed.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; The whole PyInstaller folder: Cenno.exe plus the DLLs and data next to it.
Source: "..\dist\Cenno\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "Control your computer with hand gestures"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; The cenno:// handler (cenno://on, cenno://off, cenno://toggle). The "URL
; Protocol" value is what makes Windows treat the scheme as a link handler.
; HKCU, so it needs no admin rights and it belongs to the user who installed.
Root: HKCU; Subkey: "Software\Classes\cenno"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\cenno"; ValueType: string; ValueName: "DefaultIcon"; ValueData: "{app}\{#AppExe},0"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\cenno\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{sys}\explorer.exe"; Parameters: "ms-settings:privacy-webcam"; Description: "Open the Windows camera privacy settings"; Flags: runhidden postinstall skipifsilent unchecked

[UninstallRun]
; Cenno lives in the tray: close it, or the files stay locked.
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "StopCenno"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
