@echo off
rem ===========================================================================
rem  turborec.cmd - Turbo Recorder console launcher (CLI)
rem
rem  Prepends the install directory to PATH so the bundled ffmpeg.exe /
rem  ffprobe.exe are discovered by the engine, then runs turborec.py with
rem  the Python found on PATH (python >= 3.8 required).
rem ===========================================================================
setlocal
set "TURBOREC_DIR=%~dp0"
set "PATH=%TURBOREC_DIR%;%PATH%"

rem Prefer the py launcher, then plain python.
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%TURBOREC_DIR%turborec.py" %*
  exit /b %errorlevel%
)

python "%TURBOREC_DIR%turborec.py" %*
exit /b %errorlevel%
