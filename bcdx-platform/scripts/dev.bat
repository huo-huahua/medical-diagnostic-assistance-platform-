@echo off
REM ============================================================
REM  BC-Dx Platform - one-shot development launcher (Windows)
REM
REM  Opens the backend and frontend in separate windows.
REM  Probes for a Python interpreter that actually has the backend
REM  dependencies, because a bare `python` on PATH may resolve to an
REM  unrelated install (e.g. the WorkBuddy managed runtime) that
REM  lacks FastAPI. All messages are ASCII-only on purpose: cmd reads
REM  .bat files using the OEM code page, so non-ASCII text here can
REM  be garbled on non-UTF8 systems.
REM ============================================================
setlocal

set ROOT=%~dp0..
cd /d "%ROOT%"

if not exist "backend\app\main.py" (
  echo [X] Could not find backend\app\main.py under "%ROOT%"
  echo     Run this script from inside the bcdx-platform folder.
  pause
  exit /b 1
)

REM ---- 1. locate a usable Python -------------------------------------------
echo [1/3] Looking for a Python with the backend dependencies...

set "PY="
call :try_python "%BCDX_PYTHON%"
call :try_python "%USERPROFILE%\anaconda3\python.exe"
call :try_python "%USERPROFILE%\miniconda3\python.exe"
call :try_python "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :try_python "python3"
call :try_python "python"

if not defined PY (
  echo.
  echo [X] No Python interpreter with FastAPI + Uvicorn was found.
  echo     Install the backend deps first:
  echo.
  echo         cd backend
  echo         pip install -r requirements.txt
  echo.
  echo     Or point this script at an existing interpreter:
  echo.
  echo         set BCDX_PYTHON=C:\path\to\python.exe
  echo         scripts\dev.bat
  echo.
  pause
  exit /b 1
)

echo       using: %PY%

REM Put the chosen interpreter first on PATH so a bare `python` inside the
REM spawned windows resolves to the same one (avoids quoting headaches).
for %%D in ("%PY%") do set "PYDIR=%%~dpD"
set "PATH=%PYDIR%;%PATH%"

REM ---- 2. model registry ---------------------------------------------------
if not exist "ml\registry\registry.json" (
  echo       registry.json missing - training models now ^(~30s^)...
  pushd ml
  python pipelines\train.py
  popd
  if errorlevel 1 (
    echo [X] Training failed. Aborting.
    pause
    exit /b 1
  )
) else (
  echo       model registry found - skipping training
)

REM ---- 3. launch both services --------------------------------------------
echo [2/3] Starting backend on http://127.0.0.1:8000 ...
start "BC-Dx backend" cmd /k "cd /d "%ROOT%\backend" && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

echo [3/3] Starting frontend on http://127.0.0.1:5173 ...
start "BC-Dx frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev"

echo.
echo   ------------------------------------------------------------
echo    Frontend : http://127.0.0.1:5173      ^(open this one^)
echo    API docs : http://127.0.0.1:8000/docs
echo    Health   : http://127.0.0.1:8000/health
echo   ------------------------------------------------------------
echo.
echo   The backend needs ~20-30s on first start: it loads the ML models
echo   and builds the local embedding index. The login page works right
echo   away, but the Q&A page is only ready once the backend log shows
echo   "RAG index built".
echo.
echo   Two new windows were opened. Close them to stop the servers.
echo.
pause
exit /b 0

REM --------------------------------------------------------------------------
REM  Probe a candidate interpreter: it must import fastapi AND uvicorn.
REM --------------------------------------------------------------------------
:try_python
if defined PY exit /b 0
if "%~1"=="" exit /b 0
"%~1" -c "import fastapi, uvicorn" >nul 2>&1
if not errorlevel 1 set "PY=%~1"
exit /b 0
