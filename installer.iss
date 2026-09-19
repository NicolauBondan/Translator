; Instalador do Manhua Translator — compile com Inno Setup 6.3 ou superior (https://jrsoftware.org/isinfo.php)
;   ISCC.exe /DAppVersion=1.0.0 installer.iss
; Antes é preciso gerar a pasta dist\ManhuaTranslator com o PyInstaller.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Manhua Translator"
#define AppExe  "ManhuaTranslator.exe"

[Setup]
AppId={{B7C1F3A2-5D0E-4C8B-9E2A-3F6A1D8C4E77}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Manhua Translator
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=ManhuaTranslator-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; instala só para o usuário atual (sem pedir administrador), mas deixa escolher "para todos"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\ManhuaTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; remove configurações, log e chave de API salvos pelo app
Type: filesandordirs; Name: "{localappdata}\ManhuaTranslator"
