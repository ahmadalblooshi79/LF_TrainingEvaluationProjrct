; Inno Setup — بناء مُثبّت Windows لسيرفر نظام التحليل الذكي
; يتطلب Inno Setup 6: https://jrsoftware.org/isinfo.php
; التشغيل: installer\build_setup.bat

#define MyAppName "نظام التحليل الذكي — السيرفر"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "LF Training Evaluation"
#define MyAppExeName "START_SERVER.bat"

[Setup]
AppId={{A7F3C2E1-9B4D-4A8E-B1C0-5D6E7F8A9B0C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\LF_TrainingEvaluation
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=LF_TrainingEvaluation_Server_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات:"
Name: "firewall"; Description: "فتح المنفذ 8005 في جدار الحماية"; GroupDescription: "الشبكة:"; Flags: checked

[Files]
; يُنشأ مجلد التوزيع أولاً عبر create_distribution.ps1
Source: "..\dist\LF_TrainingEvaluation_Server\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\تشغيل السيرفر"; Filename: "{app}\installer\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\تثبيت المتطلبات"; Filename: "{app}\installer\INSTALL_SERVER.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\installer\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\install_server.ps1"" -SkipFirewall"; StatusMsg: "جاري تثبيت Python والمتطلبات..."; Flags: waituntilterminated
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""LF Training Evaluation Server (TCP 8005)"" dir=in action=allow protocol=TCP localport=8005"; StatusMsg: "فتح المنفذ 8005..."; Flags: runhidden; Tasks: firewall
Filename: "{app}\installer\{#MyAppExeName}"; Description: "تشغيل السيرفر الآن"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"

[Code]
function InitializeSetup(): Boolean;
begin
  if not DirExists(ExpandConstant('{src}\..\dist\LF_TrainingEvaluation_Server')) then
  begin
    MsgBox('مجلد التوزيع غير موجود.' + #13#10 +
      'شغّل أولاً: installer\create_distribution.ps1 ثم أعد البناء.',
      mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;
