# ai-desktop-robot

AI 桌宠机器人：ESP32-S3 通过 Wi-Fi 连接云端 AI，逐步实现表情、运动、语音和视觉。

## 项目管理入口

- [协作规则](AGENTS.md)：工作流程、硬件约束、当前串口接口与 Git 同步规则。
- [当前进度与交接](docs/progress.md)：里程碑、验证证据、未决问题和下一步。
- [实验 002：串口命令控制 RGB](docs/experiments/002-serial-led.md)：当前程序、协议、串口测试及 VS Code 操作步骤。
- [实验 001：RGB 自动循环](docs/experiments/001-rgb-led.md)：已归档的首次实验，记录保持不变。

## 当前功能：串口命令控制 RGB

Ubuntu + VS Code / PlatformIO + Arduino；ESP32-S3、16 MB Flash、8 MB PSRAM、GPIO48 均已验证。默认环境 `rgb_gpio48`。

程序上电熄灯，在 UART0 / 115200 接收 `red`、`green`、`blue`、`off`、`status`、`help`，以回车结束。颜色持续保持，不自动切换；输入长度有上限，异常行不会执行。实验 002 已完成构建、烧录、38 项串口检查及用户灯光验收。

在 VS Code 运行 **PlatformIO: Serial Monitor**，点击监视器终端后直接输入命令并按 Enter。已启用本地回显与回车发送，Ctrl-C 退出。完整验收步骤见实验 002。

在项目根目录使用 `.venv/bin/pio run` 构建、`.venv/bin/pio run -t upload` 烧录、`.venv/bin/pio device monitor` 打开监视器。关闭监视器后，可运行 `.venv/bin/python scripts/test_serial_led.py` 重复实机检查；脚本会复位板卡、切换颜色并以熄灯结束。

代码在 `src/main.cpp`，配置在 `platformio.ini`。`diagnostics` 不驱动 LED；`rgb_gpio38` 仅保留作其他板卡版本的备选。当前沿用仅 USB 接线；完整厂家与 PCB 版本仍未确认。
