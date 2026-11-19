; ItalyBox-Setup.exe : turns the old laptop in Turin into the Italy box. Built by installer/build_installer.sh.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!ifndef STAGE
  !define STAGE "."
!endif

Name "ClipperLocal Italy box"
OutFile "ItalyBox-Setup.exe"
RequestExecutionLevel admin
ShowInstDetails show
SetCompressor /SOLID lzma
BrandingText "ClipperLocal Italy box"
InstallDir "$PROGRAMFILES64\ClipperLocal Italy box"

!define MUI_ICON "${STAGE}\icon.ico"
!define MUI_UNICON "${STAGE}\icon.ico"
!define MUI_WELCOMEPAGE_TITLE "Set up the Italy box"
!define MUI_WELCOMEPAGE_TEXT "This laptop will relay ClipperLocal's traffic so the accounts are always used from Italy.$\r$\n$\r$\nIt installs Tailscale (a private network between your own devices, nothing is opened to the internet), a tiny proxy that only your devices can use, and keeps the laptop awake when plugged in.$\r$\n$\r$\nA browser opens once so you can log in to Tailscale with your account."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Italy box"
  SetOutPath "$INSTDIR"
  File "${STAGE}\italybox-proxy.exe"
  File "${STAGE}\setup-italy-box.ps1"
  File "${STAGE}\README.md"
  WriteUninstaller "$INSTDIR\Remove Italy box.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocalItalyBox" "DisplayName" "ClipperLocal Italy box"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocalItalyBox" "UninstallString" '"$INSTDIR\Remove Italy box.exe"'
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup-italy-box.ps1" -Here "$INSTDIR"'
  Pop $0
  ${If} $0 != "0"
    MessageBox MB_ICONEXCLAMATION "Setup stopped (see the messages above). Run ItalyBox-Setup.exe again to continue."
    Abort
  ${EndIf}
  ClearErrors
  FileOpen $1 "$COMMONPROGRAMDATA\ClipperLocal Italy box\address.txt" r
  ${IfNot} ${Errors}
    FileRead $1 $2
    FileClose $1
    MessageBox MB_ICONINFORMATION "Done! Paste this address in ClipperLocal (Settings, Italy box proxy):$\r$\n$\r$\n$2$\r$\n$\r$\nThen in the Tailscale admin page allow this laptop as an exit node."
  ${EndIf}
SectionEnd

Section "Uninstall"
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\setup-italy-box.ps1" -Remove'
  Pop $0
  Delete "$INSTDIR\*.*"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocalItalyBox"
SectionEnd
