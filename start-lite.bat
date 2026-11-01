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

rem 每次启动都重建 interface.json：上游资源更新后不会再用到旧的裁剪结果
"%PY%" lite\apply_scope.py
if errorlevel 1 (
  echo [ERROR] apply_scope failed. Check lite\runtime-config.json.
  pause
  exit /b 1
)

"%PY%" app.py
if errorlevel 1 pause
