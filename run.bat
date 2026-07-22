@echo off
rem ===========================================================================
rem  TIA Web Practice - one launcher for every way to start the app (Windows).
rem
rem  Double-click this file for a menu, or from a terminal:
rem      run.bat offline              open the app, no server, no Python
rem      run.bat online  [httpPort]   PLC runtime + web server (default 8000)
rem      run.bat modbus  [mbPort] [httpPort]   ...also Modbus TCP (default 5020)
rem
rem  Anything more exotic (--dir, --mock, custom combinations) is still just
rem  plc_server.py - see "run.bat --help".
rem ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "MODE=%~1"

rem internal re-entry: wait for the server to bind, then open the browser
if /I "%MODE%"=="_browser" goto :browser

if /I "%MODE%"=="/?"     goto :usage
if /I "%MODE%"=="-h"     goto :usage
if /I "%MODE%"=="--help" goto :usage
if not defined MODE goto :menu
goto :dispatch

rem ---------------------------------------------------------------- menu ----
:menu
echo.
echo   TIA Web Practice
echo   ----------------
echo   [1]  Offline           Open the app only. No server, no Python.
echo                          Everything except the live Pi runtime works.
echo   [2]  Online runtime    PLC runtime + web server on http://localhost:8000
echo                          Use this for Monitor / Download / online mode.
echo   [3]  Online + Modbus   Same as [2], plus Modbus TCP on port 5020
echo                          (what the Automation Sim gateway connects to).
echo   [Q]  Quit
echo.
set "CHOICE="
set /p "CHOICE=Choose 1, 2, 3 or Q [1]: "
if not defined CHOICE set "CHOICE=1"
if "%CHOICE%"=="1"    set "MODE=offline"
if "%CHOICE%"=="2"    set "MODE=online"
if "%CHOICE%"=="3"    set "MODE=modbus"
if /I "%CHOICE%"=="Q" exit /b 0
if not defined MODE (
    echo   "%CHOICE%" is not one of the choices.
    goto :menu
)

rem ------------------------------------------------------------ dispatch ----
:dispatch
if /I "%MODE%"=="offline" goto :offline
if /I "%MODE%"=="online"  goto :online
if /I "%MODE%"=="modbus"  goto :modbus
echo Unknown mode "%MODE%".
echo.
goto :usage

rem ------------------------------------------------------------- offline ----
:offline
echo.
echo Opening index.html in your default browser...
echo (No server is started. Close the tab when you are done.)
start "" "%~dp0index.html"
exit /b 0

rem -------------------------------------------------------------- online ----
:online
set "HTTP_PORT=%~2"
if not defined HTTP_PORT set "HTTP_PORT=8000"
set "MB_ARGS="
goto :serve

rem -------------------------------------------------------------- modbus ----
:modbus
set "MB_PORT=%~2"
if not defined MB_PORT set "MB_PORT=5020"
set "HTTP_PORT=%~3"
if not defined HTTP_PORT set "HTTP_PORT=8000"
set "MB_ARGS=--modbus-port %MB_PORT%"
goto :serve

rem --------------------------------------------------------------- serve ----
:serve
call :findpython
if errorlevel 1 goto :nopython

echo.
echo Starting the PLC runtime...
echo   App:    http://localhost:%HTTP_PORT%
if defined MB_ARGS echo   Modbus: TCP port %MB_PORT%
echo   Press Ctrl+C in this window to stop it.
echo.

rem open the browser from a second window once the port is actually listening
start "" /min cmd /c ""%~f0" _browser %HTTP_PORT%"

%PY_CMD% plc_server.py --port %HTTP_PORT% %MB_ARGS%
set "RC=%ERRORLEVEL%"

rem Ctrl+C is a normal way to stop the server, not a failure. plc_server.py
rem catches KeyboardInterrupt and exits 0, but if it is killed harder Windows
rem reports STATUS_CONTROL_C_EXIT (0xC000013A) as either sign.
if not "%RC%"=="0" if not "%RC%"=="-1073741510" if not "%RC%"=="3221225786" (
    echo.
    echo The runtime stopped with an error ^(exit code %RC%^).
    echo If it mentioned "address already in use", something else has port
    echo %HTTP_PORT% - start it on another one, e.g.:   run.bat online 8001
    echo.
    pause
)
exit /b %RC%

rem ------------------------------------------------------------- browser ----
:browser
rem %2 = port. ping is the portable sleep; timeout.exe misbehaves without a console.
ping -n 3 127.0.0.1 >nul 2>&1
start "" "http://localhost:%~2/"
exit /b 0

rem ---------------------------------------------------------- find python ----
:findpython
rem Prefer the "py" launcher: on Windows a bare "python" is often the Microsoft
rem Store alias, which opens the Store instead of running anything.
set "PY_CMD="
py -3 -c "import sys" >nul 2>&1 && set "PY_CMD=py -3"
if defined PY_CMD exit /b 0
python -c "import sys" >nul 2>&1 && set "PY_CMD=python"
if defined PY_CMD exit /b 0
python3 -c "import sys" >nul 2>&1 && set "PY_CMD=python3"
if defined PY_CMD exit /b 0
exit /b 1

:nopython
echo.
echo Could not find Python ^(tried "py -3", "python", "python3"^).
echo.
echo Install it from https://www.python.org/downloads/ and tick
echo   [x] Add python.exe to PATH
echo during setup, then run this file again.
echo.
echo You do NOT need Python for offline use - choose [1], or run:
echo   run.bat offline
echo.
pause
exit /b 1

rem --------------------------------------------------------------- usage ----
:usage
echo.
echo   run.bat                        show the menu
echo   run.bat offline                open index.html, no server, no Python
echo   run.bat online  [httpPort]     PLC runtime + web server  (default 8000)
echo   run.bat modbus  [mbPort] [httpPort]
echo                                  ...and Modbus TCP        (default 5020)
echo.
echo   Everything else is plain plc_server.py, e.g.:
echo       py -3 plc_server.py --mock --dir C:\some\folder
echo.
exit /b 0
