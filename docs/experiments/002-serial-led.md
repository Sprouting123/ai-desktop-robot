# 实验 002：串口命令控制板载 RGB LED

- 日期：2026-11-07（Asia/Shanghai）。
- 状态：**已验收**。三个环境构建成功，GPIO48 烧录与写入校验成功，38 项实机串口检查通过；用户在 VS Code Monitor 中确认三种颜色保持且 `off` 熄灯。
- 当前程序：`src/main.cpp`；默认环境 `rgb_gpio48`；启动标记 `[experiment 002] Serial RGB LED / Arduino`。
- Git：实验实现、测试脚本与初始记录已提交为 [e702fc1](https://github.com/Sprouting123/ai-desktop-robot/commit/e702fc14f8708e335d48b849d8a28a41e2ebfc62)；用户于 2026-11-07 明确授权推送，已推送到 GitHub `origin/main` 并核对远程提交一致。
- 历史保留：实验 001 文档未修改；当时的自动循环程序可在提交 `6adb065` 的 `src/main.cpp` 中查看。当前主程序已进入实验 002。

## 1. 目标、接线与复用配置

接收电脑通过 UART0 发送的文本行，控制板载 RGB LED。上电或复位后熄灯；收到有效颜色命令后更新 LED 并回复；不再自动循环变色。

沿用实验 001 的仅 USB 接线，本次不增加外设，也未重新安装环境：

| 项目 | 配置 |
| --- | --- |
| 开发板 | ESP32-S3 / S3-N16R8 双 USB-C；完整厂家与 PCB 版本仍未确认 |
| RGB | GPIO48，单颗可寻址 LED，GRB / 800 kHz，亮度 24/255 |
| 内存 | 16 MB QIO Flash、8 MB OPI PSRAM，`qio_opi`，`default_16MB.csv` |
| 串口 | COM 口 USB 串口桥，UART0，115200 baud，`ARDUINO_USB_CDC_ON_BOOT=0` |
| 固定路径 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00`；本次仍映射至 `/dev/ttyACM1` |
| 设备访问 | 本次核对目标 VID:PID `1a86:55d3`、已有 ACL 读写权限及端口占用；没有访问摄像头串口，也没有要求重复授权 |
| 依赖 | Core 6.2.0；Espressif32 6.12.0；Arduino 2.0.17；NeoPixel 1.15.5，均沿用原版本 |
| 监视器新增设置 | `monitor_echo = yes`、`monitor_eol = LF`、`monitor_filters = time, send_on_enter`；DTR/RTS 仍为 0 |

## 2. 命令协议

命令不需要引号，一行一条。英文字母不区分大小写，首尾空格和 Tab 会被忽略。

| 命令 | 行为 | 回复格式 |
| --- | --- | --- |
| `red` | 设置红色并保持 | `OK state=red pin=48` |
| `green` | 设置绿色并保持 | `OK state=green pin=48` |
| `blue` | 设置蓝色并保持 | `OK state=blue pin=48` |
| `off` | 关闭 RGB 灯并保持 | `OK state=off pin=48` |
| `status` | 查询最后执行的颜色、GPIO、是否启用、亮度参数与启动后时间 | `STATUS state=... pin=48 enabled=1 brightness=24 uptime_ms=...` |
| `help` | 列出命令、长度上限和结束符 | `HELP red | green | blue | off | status | help; max_line=32; endings=LF/CR/CRLF` |

`status` 返回的是程序最后设置的状态，不是光传感器测量；它与实际观察一起用于验收。`status` 和 `help` 不改变颜色。这里的 `off` 控制标有 RGB 的彩灯，不控制板上的电源指示灯。

输入规则：

- 支持 LF、CR、CRLF。CRLF 只结束一次命令；空行或纯空格/Tab 行直接忽略，无回复。
- 未完成的一行只保留在缓冲区，不会提前执行；下一次 `loop()` 仍能继续工作。输入速度慢时也不等待固定超时。
- 最多缓存 32 个 ASCII 字符，包括首尾空白、不包括结束符。另预留一个字节存放字符串终止符；退格或 Delete 可删除尚未作废的缓冲字符。
- 第 33 个待缓存字符触发“过长”状态；整行剩余内容全部丢弃，到下一换行才回复一次 `ERR line_too_long; max=32; discarded`。有效命令前缀或后缀不会被误执行；下一行恢复正常。
- NUL、非 ASCII 字节和不支持的控制字符使整行作废，换行时回复 `ERR invalid_character; use ASCII commands; discarded`。中文命令不支持，使用英文输入法。
- 未知命令或多余参数（例如 `red blue`）回复 `ERR unknown_command; use help`，不改变状态。错误回复不回显任意输入内容。
- 一行一旦因过长或非法字符作废，退格不能撤销该错误；按回车结束这行后重新输入即可。

## 3. 程序原理

`setup()` 初始化串口、LED，先清空灯光，再输出程序身份、内存信息、初始 `off` 状态和帮助。没有等待监视器连接，也没有启动延时。

`loop()` 用 `Serial.available()` 判断已经到达的字节，再用 `Serial.read()` 逐字节交给行接收函数。每轮最多处理 64 个字节，之后返回；不使用 `readStringUntil()`、阻塞式等换行或 `delay()`。缓冲区是固定数组，不会随长输入无限增长。

接收函数维护缓冲长度、CRLF 状态及错误状态。遇到结束符后，执行函数去掉首尾空白、统一大小写并精确匹配六个命令。颜色命令调用 `setPixelColor()` 和 `show()` 后回复；没有收到新命令时保持原状态。

“非阻塞”指接收过程不等输入、不靠延时轮询。LED 发送和串口输出仍是短小的同步调用；本实验没有宣称在无限输入洪水下达到硬实时响应。后续多任务功能可继续利用每轮的读取上限。

## 4. 实际验证

### 构建与烧录

执行了三个环境的构建，全部 SUCCESS，合计约 9.76 秒；只向本块板烧录 `rgb_gpio48`，约 18.04 秒，各写入区域显示 `Hash of data verified`。

| 检查项 | 实际结果 |
| --- | --- |
| 三环境构建 | `diagnostics` / `rgb_gpio48` / `rgb_gpio38` 全部通过，无构建错误或警告 |
| GPIO48 静态 RAM 使用 | 19148 / 327680 字节 |
| GPIO48 程序使用 | 284945 / 6553600 字节 |
| 固件镜像文件 | 285312 字节 |
| 运行内存信息 | Flash 16777216、物理 PSRAM 8388608、PSRAM 堆 8386279 字节 |
| 程序初始状态 | 启动日志及 `status` 均为 `off` |
| GPIO38 / diagnostics 实物验证 | 本次未烧录；只验证可构建。diagnostics 不驱动 LED，颜色命令回复 `ERR led_disabled` |

最终固件 SHA-256：`946849245712872b47c7cf08b8d4cb382df268a40efff56e409352075ceedcee`。

### 实机串口回归测试

新增可重复执行的 [scripts/test_serial_led.py](../../scripts/test_serial_led.py)。脚本只接受已验证的 USB 串口桥身份，使用独占串口，复位板卡检查初始状态，退出时发送 `off` 并释放端口。它需要先关闭所有串口监视器；会实际切换 LED，但不自行判断可见颜色。

本次 **38 项检查全部通过**，覆盖：

| 范围 | 真实结果 |
| --- | --- |
| 启动身份、内存与初始熄灯状态 | 通过 |
| 六个命令及各状态查询 | 通过 |
| LF、CR、CRLF | 均接受；CRLF 只有一次响应 |
| 空行、纯空白、大小写、首尾空格/Tab | 正确处理，空行不改变状态 |
| 分片输入 `gr` 再 `een` + 换行 | 未结束时无响应；结束后执行 green |
| 未知命令及 `red blue` | 报错，原状态保持 |
| 32 字符边界 / 33 字符输入 | 前者通过，后者整行丢弃 |
| 4096 字节长前缀带有效命令后缀 | 整行丢弃一次；后续 status 正常、状态不变 |
| NUL、UTF-8 中文、终端转义序列 | 整行丢弃，无错误颜色切换 |
| Backspace / Delete | 能删除缓冲字符并执行修正后的命令 |
| 单次写入多条命令 | 按顺序执行 |
| 同次写入“过长行 + 合法行” | 报错后立即恢复到下一行 |
| 空闲保持 | 观察 3.2 秒无自动输出；随后 status 仍为 red |
| 测试收尾 | `off` 回复与 status 通过，端口释放 |

真实输出节选：

```text
OK state=red pin=48
STATUS state=red pin=48 enabled=1 brightness=24 uptime_ms=2583
ERR line_too_long; max=32; discarded
ERR invalid_character; use ASCII commands; discarded
OK state=off pin=48
PASS: 38 checks; physical LED colors still require user confirmation.
```

末行是自动测试完成时的边界声明；后续用户已完成下面的实物确认。

### Monitor 与实物验收

- 实际启动项目的 PlatformIO CLI Monitor，确认 115200、时间戳、本地回显和回车发送。输入 `red` 后仅本地显示文字；发送回车后收到 `OK state=red pin=48`。
- 同一 Monitor 中 `status`、`help`、`off` 均收到正确回复。使用 Ctrl-C 退出，并确认端口已释放。
- VS Code 扩展中的命令名称已通过已安装扩展核对：`PlatformIO: Serial Monitor`；它使用上述项目监视配置。
- 用户随后在 VS Code 中依次测试 red、green、blue、off，并确认：**“全部正确，颜色保持且 off 能熄灯”。** 至此才将本实验标记为已验收。

原始证据留在本机、被 Git 忽略：`work/002-build.log`、`work/002-upload.log`、`work/002-serial-test.log`、`work/002-monitor-transcript.txt`。最后一个文件保存回车发送测试的交互片段，不是完整启动日志。

## 5. 在 VS Code 中输入命令

1. 打开 `/home/hy/ai-desktop-robot`，选择 `rgb_gpio48` 环境。保持原来的 COM 口 USB 连接。
2. 按 **Ctrl+Shift+P**，输入并选择 **PlatformIO: Serial Monitor**。也可从 PlatformIO 的 Project Tasks → rgb_gpio48 → General → Monitor 打开。
3. 点击下方监视器终端，让键盘焦点进入终端。确认顶部速率为 **115200**；它不是普通 shell，不需要运行程序命令，也没有 Arduino IDE 那样独立的发送输入框。
4. 切换到英文输入法，输入 `help`，按 **Enter**；应看到 HELP 回复。输入字符会显示在本机，整行在回车时才发给板卡。输入回显本身不代表板卡已执行。
5. 输入 `red` + Enter，看 RGB 灯常亮红色；等待约 2 秒，应保持红色。随后分别输入 `green`、`blue`，每条都回车并观察。输入 `status` 查询最后状态，最后输入 `off` 熄灭 RGB 灯。
6. 输入 `purple` 应返回 `ERR unknown_command; use help`；再输入 `red` 应可正常执行。单独按 Enter 应没有错误回复。
7. 退出时按 **Ctrl+C** 释放串口，再烧录或运行回归测试。

打开监视器时驱动可能触发复位，RGB 会回到 `off`；看到启动信息后再输入命令。若没看到启动横幅，可发送 `help` 确认程序响应。若端口被占用，先退出另一个监视器；不要同时打开多个终端读写同一串口。

## 6. 重复实验与问题记录

在项目根目录可执行：

```bash
.venv/bin/pio run
.venv/bin/pio run -t upload
.venv/bin/pio device monitor
# 退出监视器后运行自动测试：
.venv/bin/python scripts/test_serial_led.py
```

本次没有遇到编译、烧录或串口协议测试失败。延续的注意事项：串口重插后 ACL 可能变化，只在实际拒绝访问时按实验 001 处理；ROS 的 Python 路径冲突可用 `env -u PYTHONPATH` 排除。

实验 001 文档的 Git blob hash 在开发前后均为 `1ef43b72653b2edba9fadc3dbd0b6a0c6d37867f`，确认未覆盖。当前主程序不再复现实验 001 的自动循环；需要查看旧实现时，查看历史提交，不应无提示覆盖当前工程。

## 7. 学习要点与参考

- 串口传来的是字节流，一次收到的字节不一定是一条完整命令；换行符在本实验中负责划分消息。
- 固定数组、长度检查和“整行作废”状态避免越界，也避免把长输入截断后误当成合法命令。
- `loop()` 可以不断查看已到达的数据；没有数据时立即返回，让后续显示、运动等任务有机会执行。
- 输入回显、板卡 ACK、status 状态和肉眼灯光是不同层次的证据；物理效果仍需实际观察。
- [PlatformIO Serial Monitor 与 send_on_enter / echo / EOL 官方说明](https://docs.platformio.org/en/latest/core/userguide/device/cmd_monitor.html)
- 项目实现：[src/main.cpp](../../src/main.cpp)、[platformio.ini](../../platformio.ini)；当前交接：[docs/progress.md](../progress.md)。
