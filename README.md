# ai-desktop-robot

AI 桌宠机器人：ESP32-S3 通过 Wi-Fi 连接云端 AI，逐步实现表情、运动、语音和视觉。

## 项目管理入口

- [协作规则](AGENTS.md)：工作流程、硬件约束、当前串口接口与 Git 同步规则。
- [当前进度与交接](docs/progress.md)：里程碑、验证证据、未决问题和下一步。
- [实验 005：SG90 单舵机控制](docs/experiments/005-servo.md)：GPIO4、50Hz PWM、限位、渐进运动，以及 2026-11-07 已通过的实物验收记录与复验步骤。
- [实验 004：OLED 桌宠表情引擎](docs/experiments/004-oled-eyes.md)：十种表情、眨眼、动画状态机和验收步骤。
- [实验 003：I²C 扫描与 OLED 首次显示](docs/experiments/003-i2c-scan.md)：I²C 扫描与双驱动测试图、验证状态及边界。
- [实验 002：串口命令控制 RGB](docs/experiments/002-serial-led.md)：已验收的 RGB 命令基线、串口测试及 VS Code 操作步骤。
- [实验 001：RGB 自动循环](docs/experiments/001-rgb-led.md)：已归档的首次实验，记录保持不变。

## 当前功能：OLED 表情、SG90 舵机、串口控制 RGB、I²C 扫描与 OLED 测试

Ubuntu + VS Code / PlatformIO + Arduino；ESP32-S3、16 MB Flash、8 MB PSRAM、GPIO48 均已验证。默认环境 `rgb_gpio48`。

程序上电熄灯，并在 SH1106 128×64 OLED 上显示两只机器人眼睛。通过 UART0 / 115200 发送 `eyes normal`、`eyes happy`、`eyes angry`、`eyes sad`、`eyes embarrassed`、`eyes sympathy`、`eyes comfort`、`eyes melancholy`、`eyes left`、`eyes right` 可切换持续表情；`eyes blink` 触发一次眨眼后恢复原表情，`eyes status` 查询表情、动画阶段和计数。眼睛使用 `millis()` 非阻塞动画，约 3–5 秒自动眨眼一次，闭眼约 200ms，串口命令始终可用。`eyes dump` 输出 64×32 ASCII 帧缓冲，供无屏幕时做软件调试。

SG90 通过 GPIO4 以 50Hz PWM 控制。命令 `servo center` 回 90°，`servo 60`–`servo 120` 渐进到指定角度，`servo status` 查询状态/角度/脉宽，`servo stop` 停止调度并关闭脉冲。上电不输出脉冲，首次显式命令才使能；软件限位 60–120°，脉宽 600–2400µs，运动速度 60°/s。舵机必须使用外部 5V 并与 ESP32 共地，不能把外部 5V 接到 3V3 或 GPIO；首次测试不装摇臂。

原有串口命令保留：`red`、`green`、`blue`、`off`、`status`、`help`、`i2cscan`、`oled_sh1106`、`oled_ssd1306`、`oled_status`。颜色持续保持，不自动切换；输入长度有上限，异常行不会执行。`i2cscan` 使用 GPIO8/9、100kHz 扫描 0x08–0x77；OLED 测试图与眼睛画面可互相切换，`oled_status` 显示当前驱动和画面类型。SH1106 已获用户实物显示确认，SSD1306 测试图由用户反馈异常，因此眼睛固定使用 SH1106；控制器型号仍未鉴定。实验 004 的十种表情与眨眼已于 2026-11-07 获用户实物验收，最新实测状态见实验 004。

在 VS Code 运行 **PlatformIO: Serial Monitor**，点击监视器终端后直接输入命令并按 Enter。已启用本地回显与回车发送，Ctrl-C 退出。表情逐项验收步骤见实验 004。

在项目根目录使用 `.venv/bin/pio run` 构建、`.venv/bin/pio run -t upload` 烧录、`.venv/bin/pio device monitor` 打开监视器。关闭监视器并保持舵机外部 5V 断开后，可运行 `.venv/bin/python scripts/test_serial_servo.py` 重复实机检查；脚本会复位板卡、回归旧命令、检查十种表情、眨眼与舵机逻辑，以舵机输出关闭、RGB 熄灯、SH1106 眼睛画面结束。`scripts/test_serial_eyes.py` 仅对应实验 004 固件，保留为历史记录。

代码分为 `src/main.cpp`（串口、RGB、I²C、屏幕与舵机命令）、`src/eyes_state.*`（纯时间状态机）、`src/eyes_render.*`（表情绘图）、`src/eyes_engine.*`（动画调度与增量刷新）、`src/servo_controller.*`（PWM、限位与渐进运动），配置在 `platformio.ini`。`diagnostics` 不驱动 LED；`rgb_gpio38` 仅保留作其他板卡版本的备选。当前由 USB 供电；用户报告 OLED VCC/GND/SDA/SCL 分别接 3V3/GND/GPIO8/GPIO9，SG90 信号 GPIO4、红/棕线接外部 5V 正/负极并与 ESP32 共地；2026-11-07 实物运动、停止/恢复与 OLED 并行运行已获用户确认，实际角度与电流未测量；完整厂家与 PCB 版本仍未确认。
