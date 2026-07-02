; Inno Setup — مُثبّت سطح المكتب (حزمة PyInstaller — بدون Python)
; يتطلب Inno Setup 6: https://jrsoftware.org/isinfo.php
; التشغيل: installer\build_desktop_setup.bat

#define MyAppName "نظام إدارة التمارين"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "LF Training Evaluation"
#define MyAppExeName "LF_TrainingEvaluation_Server.exe"

[Setup]
AppId={{B8E4D1F2-3C5A-4E7B-9D0F-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\LF_TrainingEvaluation
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=LF_TrainingEvaluation_Desktop_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات:"; Flags: checked
Name: "firewall"; Description: "فتح المنفذ 8005 في جدار الحماية"; GroupDescription: "الشبكة:"; Flags: checked

[Files]
Source: "..\dist\LF_TrainingEvaluation_Server\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\تشغيل النظام"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""LF Training Evaluation Server (TCP 8005)"" dir=in action=allow protocol=TCP localport=8005"; StatusMsg: "فتح المنفذ 8005..."; Flags: runhidden; Tasks: firewall
Filename: "{app}\{#MyAppExeName}"; Description: "تشغيل النظام الآن"; Flags: postinstall nowait skipifsilent unchecked

[Code]
function InitializeSetup(): Boolean;
begin
  if not DirExists(ExpandConstant('{src}\..\dist\LF_TrainingEvaluation_Server')) then
  begin
    MsgBox('حزمة PyInstaller غير موجودة.' + #13#10 +
      'شغّل أولاً: installer\build_desktop_setup.bat',
      mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Exec('netsh', 'advfirewall firewall delete rule name="LF Training Evaluation Server (TCP 8005)"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
