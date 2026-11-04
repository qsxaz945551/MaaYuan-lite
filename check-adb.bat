@echo off
chcp 936 >nul
cd /d "%~dp0"
set "ADB=D://Apps Game\LDPlayer14\adb.exe"

echo ==========================================
echo   MaaYuan Lite - ADB 连接检查
echo ==========================================
echo.
"%ADB%" devices
echo.
echo ------------------------------------------
echo 正常应该看到: emulator-5554    device
echo.
echo 如果列表是空的，请这样恢复：
echo   1. 在雷电窗口右上角点 三条横线 菜单
echo   2. 选 设置 - 其他设置
echo   3. 找到 ADB 调试，先关掉，等两秒，再打开
echo   4. 回到本窗口按任意键重新检查
echo ------------------------------------------
echo.
pause
echo.
echo === 重新检查 ===
"%ADB%" devices
echo.
pause
