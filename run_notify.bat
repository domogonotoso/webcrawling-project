@echo off
setlocal
cd /d "%~dp0"
if defined JOB_TRACKER_PYTHON goto run
if defined CONDA_PREFIX (
    set "JOB_TRACKER_PYTHON=%CONDA_PREFIX%\python.exe"
) else if exist "%~dp0.runtime\python\python.exe" (
    set "JOB_TRACKER_PYTHON=%~dp0.runtime\python\python.exe"
) else (
    set "JOB_TRACKER_PYTHON=python"
)
:run
"%JOB_TRACKER_PYTHON%" "%~dp0notify.py" %*
exit /b %errorlevel%
