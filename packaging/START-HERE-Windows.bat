@echo off
setlocal EnableExtensions
title Horus Beta Installer

pushd "%~dp0"
if errorlevel 1 (
  echo.
  echo   ERROR: could not enter "%~dp0"
  echo.
  pause
  exit /b 1
)

set "HORUS_SCRIPT=%~dp0installer\horus_install.py"
if not exist "%HORUS_SCRIPT%" (
  echo.
  echo   ERROR: installer\horus_install.py is missing.
  echo.
  echo   This usually means the ZIP was only partly extracted, or this file
  echo   was copied out of it on its own.
  echo.
  echo   Extract the whole Horus-Beta ZIP to a folder, open that folder,
  echo   and double-click START-HERE-Windows.bat from inside it.
  echo.
  popd
  pause
  exit /b 17
)

set "HORUS_PY="
call :try_python py -3
if not defined HORUS_PY call :try_python python
if not defined HORUS_PY call :try_python python3
if not defined HORUS_PY goto :no_python

echo.
echo   Using %HORUS_PY%
echo.

%HORUS_PY% "%HORUS_SCRIPT%" %*
set "HORUS_RC=%ERRORLEVEL%"

echo.
if not "%HORUS_RC%"=="0" (
  echo   The installer stopped with exit code %HORUS_RC%.
  echo   Details are in install-log.txt next to this file.
)
echo.
popd
pause
exit /b %HORUS_RC%

:try_python
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "HORUS_PY=%*"
exit /b 0

:no_python
echo.
echo   ===================================================================
echo    Python 3.11 or newer is required, and was not found.
echo   ===================================================================
echo.
echo   Horus itself runs in Docker - Python is only needed to run this
echo   installer.
echo.
echo   1. Download Python from:
echo.
echo          https://www.python.org/downloads/windows/
echo.
echo   2. Run the installer. On the FIRST screen, tick
echo.
echo          [x] Add python.exe to PATH
echo.
echo      (it is easy to miss, and nothing works without it)
echo.
echo   3. When it finishes, close this window and double-click
echo      START-HERE-Windows.bat again.
echo.
popd
pause
exit /b 10
