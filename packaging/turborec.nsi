; =============================================================================
;  turborec.nsi — Turbo Recorder Windows installer (NSIS 3.x)
;
;  Build with:  makensis /DVERSION=x.y.z /DPYTHON_INSTALLER=..\build\python-... \
;                   packaging/turborec.nsi
;
;  What gets installed:
;    * turborec.py            - the cross-platform Python CLI + GUI engine
;    * ffmpeg.exe/ffprobe.exe - Windows static FFmpeg build (pinned 8.1.2),
;                               placed on PATH only for the launched app
;    * python-3.12.10-amd64.exe - pinned Python 3.12 installer; run silently
;                               during install UNLESS a Python 3.8+ (with Tk)
;                               is already present, so the app is fully
;                               self-contained (no prerequisites on the host)
;    * README.md, LICENSE, CHANGELOG.md, docs/ (TUTORIAL, README.pt-BR)
;    * turborec.ico           - application icon
;    * turborec.cmd           - console launcher (CLI)
;    * turborec-gui.cmd       - GUI launcher (pythonw, no console window)
;
;  The bundled Python is installed per-user (InstallAllUsers=0, with Tk and
;  the py launcher, PATH prepended) and is NEVER removed by the uninstaller —
;  it may be shared with other applications.
; =============================================================================

!include "MUI2.nsh"
!include "LogicLib.nsh"

; ---- version (overridable: /DVERSION=x.y.z) ---------------------------------
!ifndef VERSION
  !define VERSION "3.10.0"
!endif

; ---- bundled Python installer (overridable: /DPYTHON_INSTALLER=path) --------
!ifndef PYTHON_INSTALLER
  !define PYTHON_INSTALLER "..\build\python-3.12.10-amd64.exe"
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
  File "${PYTHON_INSTALLER}"
  File "turborec.ico"

  ; Launchers.
  File "turborec.cmd"
  File "turborec-gui.cmd"

  ; Documentation.
  File "..\README.md"
  File "..\LICENSE"
  File "..\CHANGELOG.md"
  File "..\docs\TUTORIAL.md"
  File "..\docs\README.pt-BR.md"

  ; Ensure a usable Python 3.8+ (with Tk): install the bundled Python 3.12
  ; silently when none is found.
  Call EnsurePython

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
  ; Remove the bundled Python installer we shipped, but NEVER uninstall the
  ; installed Python itself (it may be shared with other applications).
  Delete "$INSTDIR\python-3.12.10-amd64.exe"
  Delete "$INSTDIR\turborec.ico"
  Delete "$INSTDIR\turborec.cmd"
  Delete "$INSTDIR\turborec-gui.cmd"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\CHANGELOG.md"
  Delete "$INSTDIR\TUTORIAL.md"
  Delete "$INSTDIR\README.pt-BR.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Turbo Recorder"
  DeleteRegKey HKLM "Software\Turbo Recorder"
SectionEnd

; ---- ensure a usable Python (3.8+, with Tk) -----------------------------------
; Exit code 0 from `py -3` means a compatible Python with Tk already exists
; (python.org installs and the Microsoft Store build both register with the py
; launcher). Otherwise run the bundled Python 3.12 installer silently per-user
; (with Tk, pip, the py launcher, and PATH prepended), then re-check. Warn —
; without aborting — only if Python is still unusable afterwards.
Function EnsurePython
  nsExec::ExecToStack '"py" -3 -c "import tkinter,sys;sys.exit(0 if sys.version_info>=(3,8) else 1)"'
  Pop $0  ; exit code: 0 = usable Python already present
  ${If} $0 == 0
    Goto PythonReady
  ${EndIf}

  ClearErrors
  ExecWait '"$INSTDIR\python-3.12.10-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_tcltk=1 Include_pip=1 Include_launcher=1 Include_test=0 Include_doc=0 Shortcuts=0' $1

  nsExec::ExecToStack '"py" -3 -c "import tkinter,sys;sys.exit(0 if sys.version_info>=(3,8) else 1)"'
  Pop $0
  ${If} $0 == 0
    Goto PythonReady
  ${EndIf}

  MessageBox MB_ICONINFORMATION|MB_OK \
    "Python 3.8 or newer (with Tk) could not be detected after installing the$\n$\n\
     bundled Python 3.12. Turbo Recorder is a Python application; open a new$\n$\n\
     terminal and run 'py -3 turborec.py' from the install folder, or install$\n$\n\
     Python from https://www.python.org/downloads/ (check 'Add python.exe to$\n$\n\
     PATH') and re-run this installer.$\n$\n\
     The files are installed and you can proceed either way."

PythonReady:
FunctionEnd
