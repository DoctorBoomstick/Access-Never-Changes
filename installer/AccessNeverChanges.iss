; Access Never Changes -- the player's installer.
;
; Built by .github/workflows/release.yml after installer/freeze.py has made
; dist\AccessNeverChanges\. To build by hand on a machine with Inno Setup 6:
;
;     python installer\freeze.py
;     iscc /DAppVersion=1.0.0 installer\AccessNeverChanges.iss
;
; Inno Setup because its wizard is made of standard Windows controls, which
; NVDA and JAWS read without help.
;
; What it does:
;   1. asks where Fallout 2 is, suggesting a copy it found, and refuses a copy
;      without sfall and the Restoration Project, saying where to get them;
;   2. puts the mod in <Fallout 2>\Access Never Changes\ -- the game folder is
;      writable by whoever plays, since the game saves there, so the settings
;      and the language files can be edited without admin;
;   3. runs "AccessNeverChanges.exe install" to copy the scripts into the game
;      and set the handful of ddraw.ini / fallout2.cfg settings, backing each
;      file up first (install.py);
;   4. uninstalling runs "AccessNeverChanges.exe uninstall", which takes the
;      scripts out and puts those settings back.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Access Never Changes"
#define ExeName "AccessNeverChanges.exe"
#define Frozen "..\dist\AccessNeverChanges"

[Setup]
AppId={{12EC8840-0BC3-4C37-B68A-C8607E3EE4C1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Access Never Changes
AppSupportURL=https://github.com/DoctorBoomstick/Access-Never-Changes
; Replaced by the game folder the player picks; see NextButtonClick.
DefaultDirName={autopf}\{#AppName}
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=AccessNeverChanges-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#ExeName}

[Tasks]
Name: "desktopicon"; Description: "Put a ""Fallout 2 Access"" shortcut on the desktop"

[Dirs]
; Editable by the player without admin, wherever the game is.
Name: "{app}"; Permissions: users-modify
Name: "{app}\lang"; Permissions: users-modify

[Files]
Source: "{#Frozen}\*"; DestDir: "{app}"; Excludes: "access.ini"; Flags: ignoreversion recursesubdirs createallsubdirs
; The player's settings survive an upgrade.
Source: "{#Frozen}\access.ini"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\Fallout 2 Access"; Filename: "{app}\{#ExeName}"; Parameters: "--launch"; WorkingDir: "{app}"; Comment: "Start Fallout 2 with the screen reader mod"
Name: "{group}\Access Never Changes, mod only"; Filename: "{app}\{#ExeName}"; WorkingDir: "{app}"; Comment: "Start the mod for a game you start yourself"
Name: "{group}\Access Never Changes manual"; Filename: "{app}\manual.html"
Name: "{group}\Access Never Changes settings"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\access.ini"""
Name: "{group}\Access Never Changes folder"; Filename: "{app}"
Name: "{group}\Uninstall Access Never Changes"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Fallout 2 Access"; Filename: "{app}\{#ExeName}"; Parameters: "--launch"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; As the player, not as the admin the installer runs as: an elevated mod would
; start an elevated game.
Filename: "{app}\{#ExeName}"; Parameters: "--launch"; Description: "Start Fallout 2 with the mod now"; Flags: postinstall nowait skipifsilent unchecked runasoriginaluser

[UninstallRun]
Filename: "{app}\{#ExeName}"; Parameters: "uninstall ""{app}\.."""; Flags: runhidden waituntilterminated; RunOnceId: "RestoreGame"

[UninstallDelete]
Type: files; Name: "{app}\*.log"

[Code]
var
  GamePage: TInputDirWizardPage;

function IsGame(Dir: String): Boolean;
begin
  Result := (Dir <> '') and FileExists(AddBackslash(Dir) + 'fallout2.exe')
    and FileExists(AddBackslash(Dir) + 'master.dat');
end;

function HasSfall(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'ddraw.dll');
end;

function HasRPU(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'mods\rpu.dat');
end;

function SteamGame(): String;
var
  Steam: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM32, 'SOFTWARE\Valve\Steam', 'InstallPath', Steam) or
     RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamPath', Steam) then
  begin
    StringChangeEx(Steam, '/', '\', True);
    Result := AddBackslash(Steam) + 'steamapps\common\Fallout 2';
  end;
end;

function GogGame(): String;
var
  Path: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM32, 'SOFTWARE\GOG.com\Games\1440151285', 'path', Path) then
    Result := Path;
end;

{ The copy to suggest. One with the Restoration Project on it wins over one
  without: a machine with a plain copy beside a modded one should never be
  steered to the plain one. }
function FindGame(): String;
var
  Candidates: array of String;
  I: Integer;
begin
  SetArrayLength(Candidates, 6);
  Candidates[0] := SteamGame();
  Candidates[1] := GogGame();
  Candidates[2] := ExpandConstant('{commonpf32}\Steam\steamapps\common\Fallout 2');
  Candidates[3] := 'C:\GOG Games\Fallout 2';
  Candidates[4] := ExpandConstant('{commonpf32}\GOG Galaxy\Games\Fallout 2');
  Candidates[5] := ExpandConstant('{commonpf32}\Black Isle\Fallout2');
  Result := '';
  for I := 0 to GetArrayLength(Candidates) - 1 do
    if IsGame(Candidates[I]) and HasRPU(Candidates[I]) then
    begin
      Result := Candidates[I];
      Exit;
    end;
  for I := 0 to GetArrayLength(Candidates) - 1 do
    if IsGame(Candidates[I]) then
    begin
      Result := Candidates[I];
      Exit;
    end;
end;

function GameDir(Param: String): String;
begin
  Result := RemoveBackslashUnlessRoot(Trim(GamePage.Values[0]));
end;

procedure InitializeWizard;
var
  Previous: String;
begin
  GamePage := CreateInputDirPage(wpLicense,
    'Where is Fallout 2?',
    'The mod goes into the game''s own folder.',
    'Choose the folder that has fallout2.exe in it. If you have more than one ' +
    'copy, choose the one with the Restoration Project installed.',
    False, '');
  GamePage.Add('Fallout 2 folder:');
  Previous := GetPreviousData('GameDir', '');
  if IsGame(Previous) then
    GamePage.Values[0] := Previous
  else
    GamePage.Values[0] := FindGame();
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'GameDir', GameDir(''));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: String;
begin
  Result := True;
  if CurPageID <> GamePage.ID then
    Exit;
  Dir := GameDir('');
  if not IsGame(Dir) then
  begin
    MsgBox('There is no Fallout 2 in that folder. Choose the folder that has ' +
      'fallout2.exe and master.dat in it.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if (not HasSfall(Dir)) or (not HasRPU(Dir)) then
  begin
    MsgBox('This copy of Fallout 2 does not have the Restoration Project on it, ' +
      'and the mod needs it: it brings sfall, which the mod''s in-game half ' +
      'runs on.' + #13#10#13#10 +
      'Install the Restoration Project into this folder first. Its releases ' +
      'are at github.com/BGforgeNet/Fallout2_Restoration_Project. Then run ' +
      'this installer again.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  WizardForm.DirEdit.Text := AddBackslash(Dir) + '{#AppName}';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;
  if (not Exec(ExpandConstant('{app}\{#ExeName}'), 'install "' + GameDir('') + '"',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code)) or (Code <> 0) then
  begin
    if SuppressibleMsgBox('The mod is installed, but Fallout 2 needs attention ' +
        'before it will work. install.log in the mod''s folder says what.' + #13#10#13#10 +
        'Open it now?', mbConfirmation, MB_YESNO, IDNO) = IDYES then
      ShellExec('', ExpandConstant('{sys}\notepad.exe'),
        '"' + ExpandConstant('{app}\install.log') + '"', '', SW_SHOW, ewNoWait, Code);
  end;
end;
