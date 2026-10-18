@echo off
rem Explicit native Windows entry point. Never discover or invoke bash.exe/WSL.
setlocal DisableDelayedExpansion
if "%~1"=="" goto usage
if not "%~2"=="" goto usage
if defined LSF_IDE_PYTHON goto explicit
if exist "%~dp0..\.venv\Scripts\python.exe" goto venv
"%SystemRoot%\System32\where.exe" py.exe >nul 2>nul
if not errorlevel 1 goto py
"%SystemRoot%\System32\where.exe" python.exe >nul 2>nul
if not errorlevel 1 goto python
echo Python is missing. Prepare .venv or set LSF_IDE_PYTHON to python.exe. 1>&2
exit /b 127
:explicit
"%LSF_IDE_PYTHON%" "%~dp0intellij.py" run "%~1"
exit /b %errorlevel%
:venv
"%~dp0..\.venv\Scripts\python.exe" "%~dp0intellij.py" run "%~1"
exit /b %errorlevel%
:py
py.exe -3 "%~dp0intellij.py" run "%~1"
exit /b %errorlevel%
:python
python.exe "%~dp0intellij.py" run "%~1"
exit /b %errorlevel%
:usage
echo Usage: tools\intellij.cmd ^<task^> 1>&2
exit /b 2
