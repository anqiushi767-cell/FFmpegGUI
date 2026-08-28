; FFmpeg 转码器 安装脚本（Inno Setup 6）
; 编译：ISCC.exe installer.iss

#define AppName "FFmpeg 转码器"
#define AppVersion "1.0.0"
#define AppExeName "ffmpegGUI.exe"

[Setup]
AppId={{B7F3E1A0-9C4D-4E2A-8F6B-3D5C7A9E1F02}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=勇者同行A
DefaultDirName={autopf}\FFmpegGUI
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputBaseFilename=FFmpegGUI-Setup-{#AppVersion}-Windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
CloseApplications=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\ffmpegGUI.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[CustomMessages]
LaunchProgram=运行 {#AppName}
