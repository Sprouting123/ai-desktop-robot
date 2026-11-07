# ai-desktop-robot

AI 桌宠机器人：ESP32-S3 通过 Wi-Fi 连接云端 AI，逐步实现表情、运动、语音和视觉。

## 项目管理入口

- [协作规则](AGENTS.md)：工作流程、硬件约束、当前串口接口与 Git 同步规则。
- [当前进度与交接](docs/progress.md)：里程碑、验证证据、未决问题和下一步。
- [实验 003：I²C 扫描与 OLED 首次显示](docs/experiments/003-i2c-scan.md)：当前新增命令、接线、验证状态与扫描结果边界。
- [实验 002：串口命令控制 RGB](docs/experiments/002-serial-led.md)：已验收的 RGB 命令基线、串口测试及 VS Code 操作步骤。
- [实验 001：RGB 自动循环](docs/experiments/001-rgb-led.md)：已归档的首次实验，记录保持不变。

## 当前功能：串口控制 RGB、I²C 扫描与 OLED 测试

Ubuntu + VS Code / PlatformIO + Arduino；ESP32-S3、16 MB Flash、8 MB PSRAM、GPIO48 均已验证。默认环境 `rgb_gpio48`。

程序上电熄灯，在 UART0 / 115200 接收 `red`、`green`、`blue`、`off`、`status`、`help`，以回车结束。颜色持续保持，不自动切换；输入长度有上限，异常行不会执行。实验 002 已完成构建、烧录、38 项串口检查及用户灯光验收。新增 `i2cscan` 使用 GPIO8/9、100kHz 扫描 0x08–0x77，输出应答地址和设备/错误数量，不改变 RGB 状态；第二阶段使用 U8g2 显示文字、边框及四角标记，默认 SH1106 128×64。输入 `oled_ssd1306` 或 `oled_sh1106` 可切换驱动并重画，无需重复烧录；`oled_status` 查询，复位恢复 SH1106。SH1106 测试图已获用户完整正常的实物确认，SSD1306 对比画面由用户反馈异常，默认保留 SH1106；控制器型号仍未鉴定。最新烧录和实测状态见实验 003。

在 VS Code 运行 **PlatformIO: Serial Monitor**，点击监视器终端后直接输入命令并按 Enter。已启用本地回显与回车发送，Ctrl-C 退出。完整验收步骤见实验 002。

在项目根目录使用 `.venv/bin/pio run` 构建、`.venv/bin/pio run -t upload` 烧录、`.venv/bin/pio device monitor` 打开监视器。关闭监视器后，可运行 `.venv/bin/python scripts/test_serial_led.py` 重复实机检查；脚本会复位板卡、切换颜色和两种 OLED 驱动，以 RGB 熄灯、SH1106 测试图结束。

代码在 `src/main.cpp`，配置在 `platformio.ini`。`diagnostics` 不驱动 LED；`rgb_gpio38` 仅保留作其他板卡版本的备选。当前由 USB 供电，用户报告 OLED VCC/GND/SDA/SCL 分别接 3V3/GND/GPIO8/GPIO9；完整厂家与 PCB 版本仍未确认。
