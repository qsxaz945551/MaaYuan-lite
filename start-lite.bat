@echo off
cd /d "%~dp0"

rem 唯一入口：WPF 客户端（它自己拉起 Python 服务并显示窗口）
if /i "%~1"=="--legacy" (
  echo [ERROR] --legacy 已退役：浏览器控制台在 0.3.0 移除，请直接双击本文件。
  pause
  exit /b 1
)

set "EXE=%CD%\desktop\MaaYuanLite.Desktop\bin\Release\net10.0-windows\MaaYuanLite.Desktop.exe"
if not exist "%EXE%" set "EXE=%CD%\desktop\MaaYuanLite.Desktop\bin\Debug\net10.0-windows\MaaYuanLite.Desktop.exe"
if not exist "%EXE%" (
  echo [ERROR] 未找到 WPF 产物，请先编译：
  echo         dotnet build desktop\MaaYuanLite.Desktop
  pause
  exit /b 1
)

start "" "%EXE%"
