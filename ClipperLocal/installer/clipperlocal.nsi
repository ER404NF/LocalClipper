; ClipperLocal-Setup.exe : one installer for Windows. Built by installer/build_installer.sh (makensis).
; Installs for the current user (no admin), sets up Python with uv, then installer\steps.py downloads
; ffmpeg, adb, Git, Ollama and the AI models. Running it again repairs/updates and resumes downloads.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !define VERSION "0.4.0"
!endif
!ifndef STAGE
  !define STAGE "stage"
!endif

Name "ClipperLocal"
OutFile "ClipperLocal-Setup.exe"
InstallDir "$LOCALAPPDATA\ClipperLocal"
InstallDirRegKey HKCU "Software\ClipperLocal" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show
SetCompressor /SOLID lzma
BrandingText "ClipperLocal ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "ClipperLocal"
VIAddVersionKey "FileDescription" "ClipperLocal installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "ClipperLocal"

!define MUI_ICON "${STAGE}\installer\icon.ico"
!define MUI_UNICON "${STAGE}\installer\icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Install ClipperLocal"
!define MUI_WELCOMEPAGE_TEXT "This sets up everything ClipperLocal needs: Python, video tools, phone tools, Git, the Ollama AI engine and the AI models.$\r$\n$\r$\nThe AI models are big (about 25 GB), so the first install can take 30-90 minutes depending on the internet. Keep the PC plugged in and this window open.$\r$\n$\r$\nIf anything stops, just run this installer again: it continues where it stopped."
!define MUI_FINISHPAGE_RUN "$INSTDIR\ClipperLocal.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open ClipperLocal now"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.md"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Show the guide"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

; Run one command, show its output live, offer Retry on failure.
Function AskRetry
  ; in: step title on the stack. out: "retry" or "cancel"
  Exch $1
  MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$1 did not finish (code $0).$\r$\n$\r$\nThe details are in the list above and in $INSTDIR\data\install.log.$\r$\n$\r$\nRetry? Downloads continue where they stopped." IDRETRY again
  StrCpy $1 "cancel"
  Goto done
  again:
  StrCpy $1 "retry"
  done:
  Exch $1
FunctionEnd

!macro Step TITLE CMD
  DetailPrint ""
  DetailPrint "===== ${TITLE} ====="
  ${Do}
    nsExec::ExecToLog '${CMD}'
    Pop $0
    ${If} $0 == "0"
      ${Break}
    ${EndIf}
    Push "${TITLE}"
    Call AskRetry
    Pop $1
    ${If} $1 == "cancel"
      DetailPrint "Stopped at: ${TITLE}. Run the installer again any time to continue."
      Abort "Stopped at: ${TITLE}. Run the installer again to continue."
    ${EndIf}
  ${Loop}
!macroend

!macro SetEnv NAME VALUE
  System::Call 'Kernel32::SetEnvironmentVariable(t "${NAME}", t "${VALUE}") i'
!macroend

Function StopRunningApp
  ; ask a running engine to stop (so its files aren't locked), then close the app window
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/shutdown -TimeoutSec 3 | Out-Null } catch {}"'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM ClipperLocal.exe'
  Pop $0
  Sleep 1500
FunctionEnd

Section "ClipperLocal" SecMain
  SetDetailsPrint both
  Call StopRunningApp

  DetailPrint "Copying ClipperLocal files"
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "${STAGE}\*.*"
  CreateDirectory "$INSTDIR\data"
  CreateDirectory "$INSTDIR\assets"

  WriteRegStr HKCU "Software\ClipperLocal" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall ClipperLocal.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocal" "DisplayName" "ClipperLocal"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocal" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocal" "DisplayIcon" "$INSTDIR\ClipperLocal.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocal" "UninstallString" '"$INSTDIR\Uninstall ClipperLocal.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocal" "NoModify" 1

  CreateShortcut "$DESKTOP\ClipperLocal.lnk" "$INSTDIR\ClipperLocal.exe" "" "$INSTDIR\ClipperLocal.exe"
  CreateDirectory "$SMPROGRAMS\ClipperLocal"
  CreateShortcut "$SMPROGRAMS\ClipperLocal\ClipperLocal.lnk" "$INSTDIR\ClipperLocal.exe"
  CreateShortcut "$SMPROGRAMS\ClipperLocal\Repair or update ClipperLocal.lnk" "$EXEPATH"
  CreateShortcut "$SMPROGRAMS\ClipperLocal\Uninstall ClipperLocal.lnk" "$INSTDIR\Uninstall ClipperLocal.exe"

  ; Python, managed by uv inside the app folder (never the Microsoft Store one)
  !insertmacro SetEnv "UV_PYTHON_INSTALL_DIR" "$INSTDIR\tools\python"
  !insertmacro SetEnv "UV_PYTHON_PREFERENCE" "only-managed"
  !insertmacro SetEnv "UV_NO_PROGRESS" "1"
  !insertmacro SetEnv "UV_LINK_MODE" "copy"
  !insertmacro SetEnv "PYTHONUTF8" "1"
  !insertmacro SetEnv "PYTHONUNBUFFERED" "1"

  !insertmacro Step "Python (1/4)" '"$INSTDIR\tools\uv.exe" python install 3.12'
  !insertmacro Step "Python environment (2/4)" '"$INSTDIR\tools\uv.exe" venv "$INSTDIR\.venv" --python 3.12 --allow-existing'
  !insertmacro Step "Python packages (3/4, a few minutes)" '"$INSTDIR\tools\uv.exe" pip install --python "$INSTDIR\.venv\Scripts\python.exe" -r "$INSTDIR\requirements.txt"'

  ; One admin prompt for the firewall rule (phone share) and Tailscale (Italy box). Saying No is fine.
  DetailPrint ""
  DetailPrint "===== Firewall + Tailscale (Windows asks for permission) ====="
  ExecShellWait "runas" "$INSTDIR\.venv\Scripts\python.exe" '"$INSTDIR\installer\steps.py" admin' SW_HIDE

  !insertmacro Step "Tools and AI models (4/4, the long part)" '"$INSTDIR\.venv\Scripts\python.exe" "$INSTDIR\installer\steps.py"'

  DetailPrint ""
  DetailPrint "ClipperLocal is installed. Open it from the Desktop icon."
SectionEnd

Section "Uninstall"
  nsExec::ExecToLog 'powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/shutdown -TimeoutSec 3 | Out-Null } catch {}"'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM ClipperLocal.exe'
  Pop $0
  Sleep 1500
  Delete "$DESKTOP\ClipperLocal.lnk"
  RMDir /r "$SMPROGRAMS\ClipperLocal"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\desktop"
  RMDir /r "$INSTDIR\installer"
  RMDir /r "$INSTDIR\italy-box"
  RMDir /r "$INSTDIR\.venv"
  RMDir /r "$INSTDIR\tools"
  RMDir /r "$INSTDIR\.git"
  Delete "$INSTDIR\ClipperLocal.exe"
  Delete "$INSTDIR\WebView2Loader.dll"
  Delete "$INSTDIR\*.md"
  Delete "$INSTDIR\*.txt"
  Delete "$INSTDIR\config.example.yaml"
  Delete "$INSTDIR\.gitignore"
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete your clips, account logins, settings and the team's brain?$\r$\n$\r$\n(No keeps them, so a reinstall picks up where you left off.)" IDNO keep
    RMDir /r "$INSTDIR\data"
    RMDir /r "$INSTDIR\assets"
    RMDir /r "$INSTDIR\brain"
    Delete "$INSTDIR\config.yaml"
  keep:
  Delete "$INSTDIR\Uninstall ClipperLocal.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipperLocal"
  DeleteRegKey HKCU "Software\ClipperLocal"
SectionEnd
