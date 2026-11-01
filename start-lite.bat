@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%CD%\python\python.exe"
if not exist "%PY%" set "PY=D:\Apps Game\MaaYuan-win-x86_64-v2.1.1-beta.6\python\python.exe"

if not exist "%PY%" (
  echo [ERROR] Python runtime not found.
  echo Put the embedded runtime in .\python\ or update start-lite.bat.
  pause
  exit /b 1
)

if not exist "%CD%\build\generated\interface.json" (
  "%PY%" lite\apply_scope.py
)

"%PY%" app.py
if errorlevel 1 pause
