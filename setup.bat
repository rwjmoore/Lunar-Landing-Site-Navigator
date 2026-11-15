@echo off
rem ===========================================================================
rem  setup.bat - one-time installation of the Lunar Landing Site Navigator
rem
rem  1. Backend: Python virtual environment + pinned dependencies
rem  2. Data:    downloads NASA terrain (~1 GB, checksum-verified) and builds
rem              the terrain grids the API reads
rem  3. Frontend: Node.js + pnpm + pinned packages (src\frontend\install.ps1)
rem  4. Frontend config: src\frontend\.env.local pointing at the local API
rem
rem  Safe to re-run: finished steps are skipped or are quick no-ops.
rem  Requires Python 3.12+ on PATH and internet access. Windows only.
rem ===========================================================================
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%src\backend"
set "FRONTEND=%ROOT%src\frontend"
set "VENV_PY=%BACKEND%\.venv\Scripts\python.exe"

echo.
echo === [1/4] Backend: Python environment and dependencies ===
where python >nul 2>nul || (echo Python was not found on PATH. Install Python 3.12+ from python.org and re-run. & goto :fail)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" || (echo Python 3.12 or newer is required. & goto :fail)
if not exist "%VENV_PY%" (
    echo Creating virtual environment in src\backend\.venv ...
    python -m venv "%BACKEND%\.venv" || goto :fail
)
"%VENV_PY%" -m pip install --quiet --upgrade pip || goto :fail
"%VENV_PY%" -m pip install --quiet -r "%BACKEND%\requirements.lock" || goto :fail
pushd "%BACKEND%"
"%VENV_PY%" -m pip install --quiet -e . --no-deps
set "ERR=%ERRORLEVEL%"
popd
if not "%ERR%"=="0" goto :fail

echo.
echo === [2/4] Data: download NASA terrain (about 1 GB the first time) and build grids ===
pushd "%BACKEND%"
"%VENV_PY%" -m pipeline.fetch_data || (popd & goto :fail)
"%VENV_PY%" -W ignore -m pipeline.build_terrain || (popd & goto :fail)
popd

echo.
echo === [3/4] Frontend: Node.js, pnpm and packages ===
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%FRONTEND%\install.ps1" || goto :fail

echo.
echo === [4/4] Frontend configuration ===
if exist "%FRONTEND%\.env.local" (
    echo src\frontend\.env.local already exists; leaving it unchanged.
) else (
    > "%FRONTEND%\.env.local" echo VITE_API_BASE_URL=http://127.0.0.1:8000
    echo Created src\frontend\.env.local pointing the frontend at http://127.0.0.1:8000
)

echo.
echo Setup complete. Run start.bat to launch the app.
endlocal
exit /b 0

:fail
echo.
echo Setup stopped because a step failed. Fix the message above and run setup.bat again.
endlocal
exit /b 1
