# ai-desktop-robot

AI 桌宠机器人：ESP32-S3 通过 Wi-Fi 连接云端 AI，逐步实现表情、运动、语音和视觉。

## 实验 001：板载 RGB LED

开发环境：Ubuntu + VS Code / PlatformIO + Arduino。

已实测 ESP32-S3、16 MB Flash、8 MB PSRAM；GPIO48 红绿蓝循环已构建、烧录并由用户确认。默认环境为 `rgb_gpio48`；`diagnostics` 用于硬件信息，`rgb_gpio38` 仅保留作其他板卡版本备选。完整 PCB 型号/版本仍未确认，详见[实验记录](docs/experiments/001-rgb-led.md)。

安装开发工具后，使用 `.venv/bin/pio run` 构建、`.venv/bin/pio run -t upload` 烧录、`.venv/bin/pio device monitor` 查看日志。VS Code 的默认构建任务会同时检查三个环境。

代码在 `src/main.cpp`，完整配置在 `platformio.ini`；当前仅使用 USB 供电，不接外部模块。
