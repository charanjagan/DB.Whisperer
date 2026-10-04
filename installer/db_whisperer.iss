; Inno Setup script for DB.Whisperer.
;
;   "C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\db_whisperer.iss
;
; Wraps the PyInstaller onedir output (dist\DB.Whisperer\) into a single
; setup.exe. Build that first -- `pyinstaller db_whisperer.spec --noconfirm` --
; or this will not compile: the #error below fires rather than letting a build
; silently produce an installer with no application in it.
;
; Two things worth knowing before editing this file:
;
; 1. The payload is ~4.6GB, of which 4.4GB is one GGUF model file. That file is
;    already compressed (Q4_K_M quantised weights), so LZMA gains almost
;    nothing on it while costing a very long compile. See SolidCompression /
;    the model's `nocompression` flag below.
;
; 2. DiskSpanning has to be ON, and that is not a preference. Inno refuses to
;    build a single Setup.exe past ~4.2GB ("as this approaches the maximum
;    supported by Windows"), and this payload is ~4.6GB. Compression does not
;    get under the limit either: the model is already-quantised weights, so
;    LZMA2 recovers a couple of percent at best on the bulk of it.
;
;    So the output is Setup.exe plus one or more .bin slices. All of them must
;    travel together in the same folder -- Setup.exe alone will not install.
;    Zip the lot for distribution.
;
;    The alternative, if a literal single-file download is ever required, is to
;    stop bundling the model and fetch it on first run. That trades away the
;    thing this app is built around: it works offline, out of the box, with no
;    download step and no account.

#define AppName "DB.Whisperer"
; Keep in step with nl2sql.__version__ (nl2sql/__init__.py).
#define AppVersion "1.0.0"
#define AppPublisher "Charan Jagan"
#define AppURL "https://github.com/charanjagan/DB.Whisperer"
#define AppExeName "DB.Whisperer.exe"

; Relative to this .iss file, which lives in installer\ .
#define DistDir "..\dist\DB.Whisperer"

#if !FileExists(AddBackslash(SourcePath) + DistDir + "\" + AppExeName)
  #error PyInstaller output not found. Run: pyinstaller db_whisperer.spec --noconfirm
#endif

[Setup]
AppId={{8F3A5C21-6D4E-4B7A-9E15-2C8D4F1A7B93}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; The user can still pick a different location; this just means the wizard
; does not open on the "where do you want it" page with nothing else to say.
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
InfoBeforeFile=BEFORE_INSTALL.txt
InfoAfterFile=AFTER_INSTALL.txt
OutputDir=..\dist
OutputBaseFilename=DB.Whisperer-{#AppVersion}-setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern

; Installing into Program Files needs elevation; asking for it up front beats
; failing at the first file write. A user who picks a different directory still
; gets an elevated install, which is harmless.
PrivilegesRequired=admin

; The app is 64-bit (PyInstaller built it against 64-bit Python), so the
; installer must not land it in the 32-bit Program Files.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; LZMA2 at normal rather than max: the 4.4GB model is already-quantised weights
; and compresses by single-digit percent no matter how hard the compressor
; tries, so `max` buys a slightly smaller file for a much longer compile.
Compression=lzma2
SolidCompression=no

; See the header note: not optional at this payload size. `max` keeps the
; slice count as low as the format allows (~2.1GB each), so this produces
; Setup.exe plus two .bin files rather than a scattering of small ones.
DiskSpanning=yes
DiskSliceSize=max

; Rough sizes so the wizard's "space required" and Add/Remove Programs entry
; are honest. Inno computes the first itself, but stating it avoids a surprise
; on a machine that is tight on disk.
DirExistsWarning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The GGUF model, flagged nocompression: it is quantised weights, so the
; compressor spends a long time to achieve almost nothing. Listed before the
; wildcard below and excluded from it, so it is not swept up twice.
Source: "{#DistDir}\models\*.gguf"; DestDir: "{app}\models"; Flags: ignoreversion nocompression

; Everything else: the exe, the Python runtime, Qt, llama.cpp's DLLs, and the
; app icon under assets\ . recursesubdirs is what carries the nested package
; folders (PySide6\, matplotlib\, numpy\, ...) that PyInstaller produced.
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "models\*.gguf"; Flags: ignoreversion recursesubdirs createallsubdirs

; Kept beside the app so a user who clicked past the wizard pages can still
; find the prerequisites in writing.
Source: "AFTER_INSTALL.txt"; DestDir: "{app}"; DestName: "README.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{#AppName} Readme"; Filename: "{app}\README.txt"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\README.txt"; Description: "View setup notes (ODBC driver prerequisite)"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete] for the app's settings folder, deliberately.
;
; The app writes %APPDATA%\DB.Whisperer\config.json at runtime, and the obvious
; thing -- Type: filesandordirs; Name: "{userappdata}\{#AppName}" -- is wrong
; here. This installer runs elevated (PrivilegesRequired=admin), so
; {userappdata} resolves to the *administrator's* profile, which is usually not
; the account that ran the app. It would miss the real file and, on a shared
; machine, delete a different user's settings. Inno warns about exactly this.
;
; Leaving it costs a few hundred bytes of JSON holding a server name, a
; database name, and a dialect preference -- no credentials, by design (see
; AppConfig.to_dict) -- and means a reinstall comes back to the same server.

[Code]
// Checked before anything is written. Not a hard block: the ODBC driver can be
// installed after the fact and the app still installs correctly without it --
// it just cannot connect to a database. So this warns and lets the user
// proceed, rather than refusing to install over a prerequisite they may well
// be planning to add next.
function IsODBCDriverInstalled(): Boolean;
begin
  Result :=
    RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server') or
    RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
  begin
    if not IsODBCDriverInstalled() then
    begin
      if MsgBox(
           'The SQL Server ODBC driver was not found on this machine.' + #13#10 + #13#10 +
           'DB.Whisperer will install and start without it, but it cannot connect to a ' +
           'database until "ODBC Driver 17 for SQL Server" or "ODBC Driver 18 for SQL ' +
           'Server" is installed. The download link is in the readme, which is also ' +
           'shown at the end of setup.' + #13#10 + #13#10 +
           'Continue with the installation?',
           mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;
