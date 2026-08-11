@echo off
set "ENGINEERING_PYTHON="
set "ENGINEERING_PY_ARGS="
for %%I in (py.exe py.cmd py.bat) do if not "%%~$PATH:I"=="" (
  set "ENGINEERING_PYTHON=%%~$PATH:I"
  set "ENGINEERING_PY_ARGS=-3"
  goto run_engineering
)
for %%I in (python.exe python.cmd python.bat) do if not "%%~$PATH:I"=="" (
  set "ENGINEERING_PYTHON=%%~$PATH:I"
  goto run_engineering
)
>&2 echo ERROR: Engineering requires py -3 or python on PATH.
exit /b 9009

:run_engineering
"%ENGINEERING_PYTHON%" %ENGINEERING_PY_ARGS% "%~dp0engineering.py" %*
exit /b %errorlevel%
