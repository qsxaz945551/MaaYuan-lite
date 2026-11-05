# 给 DeepSeek 的交接指令

> 复制下方分隔线之间的整段文字，作为一条消息发给 DeepSeek（或任何其他接手本项目的 AI）。
> 由 WorkBuddy 于 2026-11-05 排查后生成；项目路径 `C:\Users\S\WorkBuddy\2026-10-30-19-09-34\MaaYuan-Lite`。
> 项目内规则文件：`AGENTS.md`（`.gitignore` 已忽略，本地生效）。

---

以下是 MaaYuan-Lite 项目已完成的一轮环境排查。**请把这些结论作为既定事实接受，不要重复排查、不要推翻，并据此调整你后续的工作方式。**

【一、背景】
项目使用桌面上的雷电 14 模拟器跑如鸢自动化。之前有 AI 声称「SC.exe 无法正常使用，会导致模拟器开启后一段时间闪退」，并怀疑机器上存在双版本雷电引擎。用户要求核实并给出解决办法。排查已在 Windows 11 本机完成。

【二、排查过程（已执行，勿重复）】
1. 全盘/项目目录检索 `SC.exe`：雷电14 目录、引擎目录、项目源码均无此文件，也无 `sc.exe` 调用。全机唯一的 `sc.exe` 是 `C:\WINDOWS\System32\sc.exe`。
2. 校验该系统文件：102400 字节、微软数字签名 Valid（CN=Microsoft Windows）、版本 10.0.26100.9949、Users 有读/执行权限、无 IFEO 劫持、无 DisallowRun 策略、SysWOW64 副本存在 → 文件完好。
3. 尝试执行 `sc.exe query` 被拒，报错来自 WorkBuddy「程序黑名单 / 系统级工具」，属 AI 沙箱策略，非系统故障。
4. 解析桌面快捷方式：`dnplayer.exe` → `D:\Apps Game\LDPlayer14\dnplayer.exe`；检查引擎目录、驱动服务、事件日志、VBox.log、绿化脚本。
5. 三次启动对照实验 + 每 10 秒采样进程与 VBox.log；同时核查 Windows 应用/系统事件日志与项目进程状态。

【三、结果与证据】
1. `sc.exe` 是完好的系统工具，只是一次性命令行程序，不常驻、不加载驱动、不参与雷电引擎，与模拟器闪退没有因果关系。
2. 不存在双版本引擎。`C:\Program Files\ldplayer9box` 是雷电14 绿化版自己的 VirtualBox 内核：`!)绿化处理.bat` 第 36–45 行写明"安装模拟器内核 VirtualBox"并调用 `dnrepairer.exe`；VBox.log 第 12 行 `Executable: C:\Program Files\ldplayer9box\Ld9BoxHeadless.exe`、第 27 行 `SUP: Loaded Ld9VMMR0.r0`；实测启动后 Ld9BoxHeadless / Ld9BoxSVC / VBoxNetDHCP / VBoxNetNAT 全部从该目录运行，Ld9BoxSup.sys 是系统唯一 VBox 类驱动且 Running/Auto。删除它 = 雷电14 无法启动。用户已确认此线索排除。
3. 所谓「闪退」是**有序关机、不是崩溃**：VBox.log 只有 `Console::powerDown(): A request to power off the VM has been issued` → DESTROYING → TERMINATED → `VBoxHeadless: exiting`，无 Guru Meditation / Assert / 驱动错误；近 7 天应用日志无 dnplayer 崩溃记录。
4. 根因：AI 工具命令结束时，沙箱回收其派生的进程树并触发 VM powerDown。对照数据：命令内等待 63 秒 → VM 活 66 秒；命令立即返回 → VM 活 3.7 秒；用户手动启动 → 活 41 分 40 秒。存活时长完全由启动命令何时结束决定。复现时无任何 MaaYuan / YunX / python 进程，已排除项目结束动作；`lite/runtime-config.json` 的 `startup_action` / `shutdown_action` 均为 `none`，配置正确。
5. 这是**两个互相独立的安全策略**：① 系统级工具/程序黑名单禁用 sc；② 沙箱回收进程树。启用前者只能解决 sc.exe，解决不了模拟器被关。

【四、解决方法】
1. 不要用 `sc.exe`。查内核驱动用 `Get-CimInstance Win32_SystemDriver -Filter "Name='Ld9BoxSup'" | Select Name,State,StartMode,PathName`（注意 `Get-Service` / `Win32_Service` 查不到内核驱动）；或直接读 `Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Ld9BoxSup'`。普通服务用 `Get-Service`，停用/启动用 `Stop-Service` / `Start-Service` / `Set-Service`。这些命令已实测可用，无需改任何安全设置。
2. 不要在 AI 会话里启动或重启模拟器（含 `dnplayer.exe`、`ldconsole launch/quit`、`Start-Process`、devtools 里的 `smoke_emulator_restart.py` / `inject_fault.py`）。请用户手动双击桌面「dnplayer.exe - 快捷方式」，你只运行 `& "D:\Apps Game\LDPlayer14\adb.exe" devices` 检测 `emulator-5554 device`；未就绪就提示用户手动启动。项目已有 `check-adb.bat` 和 adb 探测链，直接沿用。
3. 若确实必须让 sc.exe 可执行：由用户在「左下角头像 → 设置 → 安全中心 → 命令安全 / 系统级工具」启用或移除黑名单项。这会一次性放开 WSL/wmic/sc/reg/schtasks 一整类工具，用完关回，且对下一条消息才生效。
4. 项目本身的桌面程序（MaaYuan-Lite / YunX-Desktop）不经过 WorkBuddy 沙箱，自己用 subprocess 启动模拟器不受影响，**无需改代码**；上述限制只针对 AI 会话内通过工具发起的调用。

【五、请你遵守】
- 不要调用、修复、替换或绕过 `sc.exe`；不要把它被拦当成故障。
- 不要由工具启动/重启模拟器，不要尝试 WMI/CIM 创建进程、后台作业等变体来规避进程回收。
- 不要删除 `C:\Program Files\ldplayer9box`，不要修改 `shutdown_action` / `startup_action` 来"修闪退"。
- 遇到 adb 未就绪，只提示用户手动启动模拟器，不要自行 launch、不要重复上述排查。
- 详细规则见项目 `AGENTS.md`；环境前提见 `LITE.md` 第 93–105 行。

【六、如果你要验证】
只做只读检查即可：`Get-CimInstance Win32_SystemDriver -Filter "Name='Ld9BoxSup'"`、`& "D:\Apps Game\LDPlayer14\adb.exe" devices`、查看 `D:\Apps Game\LDPlayer14\vms\leidian0\Logs\VBox.log` 尾部。不要为了验证而启动模拟器。

---
