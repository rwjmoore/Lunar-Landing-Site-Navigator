@echo off
rem ===========================================================================
rem  start.bat - launches the full Lunar Landing Site Navigator
rem
rem  Opens two windows:
rem    "LunarSight API"  backend  at http://127.0.0.1:8000  (FastAPI/uvicorn)
rem    "LunarSight Web"  frontend at http://localhost:5173   (Vite dev server)
rem  then waits until both answer and opens the app in your browser.
rem
rem  Stop the app by closing both windows (or Ctrl+C in each).
rem  Run setup.bat once before the first start.
rem  Optional argument:  start.bat nobrowser   (start without opening a browser)
rem ===========================================================================
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%src\backend"
set "FRONTEND=%ROOT%src\frontend"
set "VENV_PY=%BACKEND%\.venv\Scripts\python.exe"
set "API_URL=http://127.0.0.1:8000"
set "WEB_URL=http://localhost:5173"

rem --- Check that setup.bat has been run --------------------------------------
if not exist "%VENV_PY%" goto :needsetup
if not exist "%ROOT%data\artifacts\terrain\site04\heights.npy" goto :needsetup
if not exist "%FRONTEND%\node_modules\vite\bin\vite.js" goto :needsetup
set "NODE="
for /d %%D in ("%FRONTEND%\.frontend-tools\node-v*") do set "NODE=%%D\node.exe"
if not defined NODE goto :needsetup
if not exist "%NODE%" goto :needsetup

rem --- Refuse to start twice ----------------------------------------------------
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul && (echo Port 8000 is already in use. Is the API already running? Close it first. & exit /b 1)
netstat -ano | findstr /r /c:":5173 .*LISTENING" >nul && (echo Port 5173 is already in use. Is the web app already running? Close it first. & exit /b 1)

rem --- Start both servers in their own windows ----------------------------------
rem The API only accepts browser calls from the web app's address (CORS).
set "LLSN_CORS_ORIGINS=%WEB_URL%"
echo Starting the API (window "LunarSight API") ...
start "LunarSight API" /D "%BACKEND%" cmd /k ""%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
echo Starting the web app (window "LunarSight Web") ...
start "LunarSight Web" /D "%FRONTEND%" cmd /k ""%NODE%" node_modules\vite\bin\vite.js --port 5173 --strictPort"

rem --- Wait until both answer ----------------------------------------------------
echo Waiting for the API and web app to come up ...
powershell.exe -NoProfile -Command ^
  "$deadline = (Get-Date).AddSeconds(60);" ^
  "foreach ($url in '%API_URL%/health', '%WEB_URL%') {" ^
  "  while ($true) {" ^
  "    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url | Out-Null; Write-Host ('  ready: ' + $url); break }" ^
  "    catch { if ((Get-Date) -gt $deadline) { Write-Host ('  not responding: ' + $url); exit 1 }; Start-Sleep -Milliseconds 500 }" ^
  "  }" ^
  "}"
if errorlevel 1 (
    echo One of the servers did not start. Check the "LunarSight API" and "LunarSight Web" windows for errors.
    exit /b 1
)

echo.
echo LunarSight is running:
echo   Web app:  %WEB_URL%
echo   API:      %API_URL%   (interactive docs: %API_URL%/docs)
echo Close the two LunarSight windows to stop it.
if /i not "%~1"=="nobrowser" start "" "%WEB_URL%"
endlocal
exit /b 0

:needsetup
echo The app is not installed yet (or setup did not finish). Run setup.bat first.
endlocal
exit /b 1
