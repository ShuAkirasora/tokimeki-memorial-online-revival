@echo off
rem  Tokimeki Memorial ONLINE -- double-click this.
rem
rem  It does three things and none of them is its own: it asks Windows for the
rem  administrator rights the game already required, finds a Python to run
rem  play.py with, and keeps this window open afterwards so the report can be
rem  read. Everything that actually changes anything is in play.py, which runs
rem  the same way from a Command Prompt if you would rather see it coming.
setlocal
cd /d "%~dp0"

rem  Elevated already? "net session" is the cheapest question that needs to be.
rem  Asking before relaunching matters: without it an elevated window would
rem  relaunch itself forever.
net session >nul 2>&1
if not errorlevel 1 goto :elevated

echo Windows will ask for administrator rights. The game needs them -- without
echo them its updater refuses to start -- and so does the hosts file. This is
echo the only prompt; everything happens in the window that opens after it.
echo.
set "PASSED="
if not "%~1"=="" set "PASSED= -ArgumentList '%*'"
powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'%PASSED%"
if errorlevel 1 (
    echo.
    echo Those rights were refused, so nothing was done. You can still run
    echo    py play.py --dry-run
    echo from here to see what it would have changed.
    pause
)
exit /b

:elevated
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if defined PY goto :found

echo Python is not installed, or was installed without being added to PATH.
echo.
echo    https://www.python.org/downloads/
echo.
echo Tick "Add python.exe to PATH" on the first screen of the installer, then
echo double-click this again. Nothing else has to be installed.
pause
exit /b 1

:found
set "TMO_PLAY_WRAPPER=1"
%PY% "%~dp0play.py" %*
echo.
pause
