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
rem  Requires Python 3.12+ and internet access. Windows only.
rem
rem  Python selection: the newest stable Python 3.12+ found via the Python
rem  launcher (py -3), "python" or "python3" is used to create the virtual
rem  environment. Pre-releases (alpha/beta/rc) are skipped.
rem  "setup.bat --which-python" only reports which Python would be chosen.
rem ===========================================================================
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%src\backend"
set "FRONTEND=%ROOT%src\frontend"
set "VENV_PY=%BACKEND%\.venv\Scripts\python.exe"

if /i "%~1"=="--which-python" (
    call :find_python
    if defined PY (call echo Would use Python %%PY_VERSION%% at %%PY%%) else (echo No stable Python 3.12 or newer found via py, python or python3.)
    endlocal
    exit /b 0
)

echo.
echo === [1/4] Backend: Python environment and dependencies ===
if exist "%VENV_PY%" (
    rem Reuse the existing environment if its Python still meets the minimum.
    "%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" || (
        echo The existing environment in src\backend\.venv uses Python older than 3.12.
        echo Delete the src\backend\.venv folder and run setup.bat again.
        goto :fail
    )
    echo Reusing existing virtual environment in src\backend\.venv
) else (
    call :find_python
    if not defined PY (
        echo No stable Python 3.12 or newer was found via py, python or python3.
        echo Install Python 3.12+ from https://www.python.org/downloads/ and re-run setup.bat.
        goto :fail
    )
    call echo Using Python %%PY_VERSION%% at %%PY%%
    echo Creating virtual environment in src\backend\.venv ...
    call "%%PY%%" -m venv "%BACKEND%\.venv" || goto :fail
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
"%VENV_PY%" -W ignore -m pipeline.build_elevation_tiles || (popd & goto :fail)
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

rem ---------------------------------------------------------------------------
rem  :find_python - sets PY (executable path) and PY_VERSION to the newest
rem  stable Python >= 3.12 among the candidates below; PY stays empty if none.
rem ---------------------------------------------------------------------------
:find_python
set "PY="
set "PY_VERSION="
set "BEST=0"
call :probe_python py -3
call :probe_python python
call :probe_python python3
exit /b 0

rem  :probe_python <command...> - asks one candidate for its version and path.
rem  It prints "<major*100+minor> <x.y.z> <path>" only if it is stable and >= 3.12.
:probe_python
for /f "usebackq tokens=1,2,*" %%A in (`%* -c "import sys; v = sys.version_info; ok = v >= (3, 12) and v.releaselevel == 'final'; ok and print('{0} {1}.{2}.{3} {4}'.format(v.major * 100 + v.minor, v.major, v.minor, v.micro, sys.executable))" 2^>nul`) do call :consider_python %%A %%B "%%C"
exit /b 0

:consider_python
if %~1 GTR %BEST% (
    set "BEST=%~1"
    set "PY_VERSION=%~2"
    set "PY=%~3"
)
exit /b 0
