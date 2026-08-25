; =============================================================================
;  turborec.nsi — Turbo Recorder Windows installer (NSIS 3.x)
;
;  Build with:  makensis /DVERSION=3.7.0 packaging/turborec.nsi
;
;  What gets installed:
;    * turborec.py            - the cross-platform Python CLI + GUI engine
;    * ffmpeg.exe/ffprobe.exe - Windows static FFmpeg build (pinned 8.1.2),
;                               placed on PATH only for the launched app
;    * README.md, LICENSE, CHANGELOG.md, docs/ (TUTORIAL, RELEASE_NOTES,
;      README.pt-BR)
;    * turborec.ico           - application icon
;    * turborec.cmd           - console launcher (CLI)
;    * turborec-gui.cmd       - GUI launcher (pythonw, no console window)
;
;  Requires Python 3.8+ (with Tk) on the target machine; the installer
;  checks for it and warns without aborting, mirroring the .deb/.rpm
;  dependency policy (python3-tkinter is a runtime dependency there too).
; =============================================================================

!include "MUI2.nsh"
!include "LogicLib.nsh"

; ---- version (overridable: /DVERSION=x.y.z) ---------------------------------
!ifndef VERSION
  !define VERSION "3.7.0"
!endif

; ---- metadata ----------------------------------------------------------------
Name "Turbo Recorder ${VERSION}"
OutFile "..\dist\Turbo_Recorder-${VERSION}-windows-x64-setup.exe"
Unicode True
RequestExecutionLevel admin

InstallDir "$PROGRAMFILES64\Turbo Recorder"
InstallDirRegKey HKLM "Software\Turbo Recorder" "InstallDir"

; ---- MUI pages ---------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "turborec.ico"
!define MUI_UNICON "turborec.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---- installer sections ------------------------------------------------------
Section "Install" SecMain
  SetOutPath "$INSTDIR"

  ; Engine and bundled binaries.
  File "..\turborec.py"
  File "..\build\win-bundle\ffmpeg.exe"
  File "..\build\win-bundle\ffprobe.exe"
  File "turborec.ico"

  ; Launchers.
  File "turborec.cmd"
  File "turborec-gui.cmd"

  ; Documentation.
  File "..\README.md"
  File "..\LICENSE"
  File "..\CHANGELOG.md"
  File "..\docs\TUTORIAL.md"
  File "..\docs\RELEASE_NOTES.md"
  File "..\docs\README.pt-BR.md"

  ; Warn (but do not abort) if no usable Python 3.8+ is found.
  Call DetectPython

  ; Start-menu entries (GUI + CLI).
  CreateDirectory "$SMPROGRAMS\Turbo Recorder"
  CreateShortcut "$SMPROGRAMS\Turbo Recorder\Turbo Recorder.lnk" \
    "$INSTDIR\turborec-gui.cmd" "" "$INSTDIR\turborec.ico"
  CreateShortcut "$SMPROGRAMS\Turbo Recorder\Turbo Recorder (CLI).lnk" \
    "$INSTDIR\turborec.cmd" "" "$INSTDIR\turborec.ico"
  CreateShortcut "$SMPROGRAMS\Turbo Recorder\Uninstall Turbo Recorder.lnk" \
    "$INSTDIR\Uninstall.exe"

  ; Desktop shortcut.
  CreateShortcut "$DESKTOP\Turbo Recorder.lnk" \
    "$INSTDIR\turborec-gui.cmd" "" "$INSTDIR\turborec.ico"

  ; Uninstaller + Add/Remove Programs entry.
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "DisplayName" "Turbo Recorder ${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "DisplayIcon" "$INSTDIR\turborec.ico"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "Publisher" "Cristian Cezar Moises"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder" \
    "NoRepair" 1
  WriteRegStr HKLM "Software\Turbo Recorder" "InstallDir" "$INSTDIR"
SectionEnd

; ---- uninstaller --------------------------------------------------------------
Section "Uninstall"
  Delete "$DESKTOP\Turbo Recorder.lnk"
  RMDir /r "$SMPROGRAMS\Turbo Recorder"

  Delete "$INSTDIR\turborec.py"
  Delete "$INSTDIR\ffmpeg.exe"
  Delete "$INSTDIR\ffprobe.exe"
  Delete "$INSTDIR\turborec.ico"
  Delete "$INSTDIR\turborec.cmd"
  Delete "$INSTDIR\turborec-gui.cmd"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\CHANGELOG.md"
  Delete "$INSTDIR\TUTORIAL.md"
  Delete "$INSTDIR\RELEASE_NOTES.md"
  Delete "$INSTDIR\README.pt-BR.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder"
  DeleteRegKey HKLM "Software\Turbo Recorder"
SectionEnd

; ---- Python detection (warning only) -----------------------------------------
Function DetectPython
  ; Look for the py launcher and the classic python.exe registry entries.
  ClearErrors
  ReadRegStr $0 HKLM "SOFTWARE\Python\PythonCore" ""
  ${If} ${Errors}
    ClearErrors
    ReadRegStr $0 HKCU "SOFTWARE\Python\PythonCore" ""
  ${EndIf}
  ${If} ${Errors}
    ; Fall back to PATH lookup.
    nsExec::ExecToStack '"py" -3 -c "import sys"'
    Pop $1  ; return code
    ${If} $1 != 0
      MessageBox MB_ICONINFORMATION|MB_OK \
        "Python 3.8 or newer (with Tk) was not detected on this system.$\n$\n\
         Turbo Recorder is a Python application; install Python from$\n\
         https://www.python.org/downloads/ (check 'Install launcher for all$\n\
         users' and 'Add python.exe to PATH') and re-run this installer, or$\n\
         run 'turborec' with any existing Python 3.8+ on PATH.$\n$\n\
         The files are installed and you can proceed either way."
    ${EndIf}
  ${EndIf}
FunctionEnd
