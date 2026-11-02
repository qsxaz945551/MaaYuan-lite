@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 运行时必须自带，不再回退到原版安装目录
set "PY=%CD%\runtime_env\python\python.exe"
if not exist "%PY%" (
  echo [ERROR] 运行时缺失：%PY%
  echo 请重新解压完整包，或运行 devtools\setup_runtime.py 准备运行时。
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
