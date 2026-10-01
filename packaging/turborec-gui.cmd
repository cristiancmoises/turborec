@echo off
rem ===========================================================================
rem  turborec-gui.cmd - Turbo Recorder GUI launcher (no console window)
rem
rem  Same PATH setup as turborec.cmd but runs under pythonw so no console
rem  window stays open while the Tk GUI is running.
rem ===========================================================================
setlocal
set "TURBOREC_DIR=%~dp0"
set "PATH=%TURBOREC_DIR%;%PATH%"

where pyw >nul 2>nul
if %errorlevel% equ 0 goto run_pyw
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" goto run_bundled_pythonw

start "" pythonw -I "%TURBOREC_DIR%turborec.py"
exit /b %errorlevel%

:run_pyw
start "" pyw -3 -I "%TURBOREC_DIR%turborec.py"
exit /b %errorlevel%

:run_bundled_pythonw
start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" -I "%TURBOREC_DIR%turborec.py"
exit /b %errorlevel%
