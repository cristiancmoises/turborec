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

rem Isolated Python ignores ambient PYTHONPATH and the user site directory.
rem Keep execution outside IF blocks so the engine exit code is not pre-expanded.
where py >nul 2>nul
if %errorlevel% equ 0 goto run_py
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" goto run_bundled_python

python -I "%TURBOREC_DIR%turborec.py" %*
exit /b %errorlevel%

:run_py
py -3 -I "%TURBOREC_DIR%turborec.py" %*
exit /b %errorlevel%

:run_bundled_python
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -I "%TURBOREC_DIR%turborec.py" %*
exit /b %errorlevel%
