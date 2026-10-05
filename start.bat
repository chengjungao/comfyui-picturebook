@echo off
rem  Start the picture book studio (Windows).
rem  Keep this file ASCII-only and CRLF: cmd.exe parses batch files
rem  with the OEM codepage, so any non-ASCII text here turns into garbage.
chcp 65001 >nul 2>nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

set PYEXE=
call :TRY python
if not "%PYEXE%"=="" goto RUN
call :TRY py
if not "%PYEXE%"=="" goto RUN
goto NOPY

:RUN
%PYEXE% app.py %*
if errorlevel 1 pause
exit /b 0

:TRY
%1 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set PYEXE=%1
exit /b 0

:NOPY
echo.
echo   [X] Python 3.8 or newer was not found.
echo.
echo       Install it first:  https://www.python.org/downloads/
echo       During setup, tick "Add Python to PATH".
echo.
pause
exit /b 1
