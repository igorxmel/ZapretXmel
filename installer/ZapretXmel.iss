; Установщик ZapretXmel — Inno Setup 6.
;
; Собирается из `tools/build_release.py`, который передаёт сюда версию и пути:
;   ISCC /DAppVersion=0.4.0 /DFileVersion=0.4.0.0 /DSourceDir=... /DOutputDir=... /DRoot=...
;
; Ставит сборку папкой (PyInstaller --onedir): она запускается вдвое быстрее
; однофайловой — ей не нужно при каждом запуске распаковывать полсотни мегабайт
; во временную папку под проверкой антивируса.
;
; Программа обновляет себя через этот же установщик: скачивает новый, запускает
; его в тихом режиме и закрывается. Поэтому установщик ждёт её выхода, а не
; спрашивает, и сам запускает новую версию, если его попросили (/LAUNCH=1).

#ifndef AppVersion
  #error Версию передаёт tools/build_release.py: /DAppVersion=...
#endif

#define AppName "ZapretXmel"
#define AppExe "ZapretXmel.exe"
; Тот же мьютекс, что занимает запущенная программа (app/core/singleton.py).
#define AppMutex "Local\ZapretXmel.SingleInstance"

[Setup]
; Идентификатор менять нельзя: по нему новая версия находит старую и ставится
; поверх, а не рядом.
AppId={{C36BF218-56AE-471C-BE5A-FBCAF3AB3348}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=igorxmel
AppPublisherURL=https://github.com/igorxmel/ZapretXmel
AppSupportURL=https://github.com/igorxmel/ZapretXmel/issues
AppUpdatesURL=https://github.com/igorxmel/ZapretXmel/releases
VersionInfoVersion={#FileVersion}
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
; Программа без прав администратора не работает: служба, драйвер WinDivert.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=ZapretXmel-Windows-Setup
SetupIconFile={#Root}\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Закрытие программы установщик не берёт на себя: она закрывается сама и
; гасит прокси и обход, а снятая насильно оставила бы их сиротами.
CloseApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"

[InstallDelete]
; Библиотеки прошлой версии убираем целиком: иначе от неё оставались бы
; файлы, которых в новой уже нет, и Python мог бы подхватить старые модули.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Обновление из самой программы: она закрылась и просит запустить новую версию
; с теми же флагами — остаться в трее, поднять обход и прокси.
Filename: "{app}\{#AppExe}"; Parameters: "{param:LAUNCHARGS|}"; Flags: nowait; Check: RelaunchAfterUpdate
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Первым делом — то, что программа принесла в систему сама: служба zapret,
; драйвер, автозапуск, прокси, ядро и настройки. Установщик о них не знает, а
; служба без этого продолжала бы работать с удалёнными файлами.
Filename: "{app}\{#AppExe}"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "ZapretXmelCleanup"

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
function AppRunning(): Boolean;
begin
  Result := CheckForMutexes('{#AppMutex}');
end;

{ Ждёт, пока программа закроется. True — закрылась. }
function WaitForExit(Seconds: Integer): Boolean;
var
  Tick: Integer;
begin
  Tick := 0;
  while AppRunning() and (Tick < Seconds * 2) do
  begin
    Sleep(500);
    Tick := Tick + 1;
  end;
  Result := not AppRunning();
end;

{ Тихий режим — это обновление из самой программы: она уже закрывается, ждём.
  Обычная установка — человек запустил установщик сам: просим закрыть. }
function ProgramClosed(): Boolean;
begin
  if WizardSilent() then
  begin
    Result := WaitForExit(60);
    Exit;
  end;

  Result := True;
  while AppRunning() do
    if MsgBox('ZapretXmel сейчас запущен. Закройте его — в том числе из значка в трее — ' +
              'и нажмите «Повтор».', mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

function InitializeSetup(): Boolean;
begin
  Result := ProgramClosed();
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  while AppRunning() do
    if MsgBox('ZapretXmel сейчас запущен. Закройте его — в том числе из значка в трее — ' +
              'и нажмите «Повтор».', mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

function RelaunchAfterUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:LAUNCH|0}') = '1');
end;
