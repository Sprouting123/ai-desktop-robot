# 项目进度与交接

最后更新：2026-11-07（Asia/Shanghai）

## 当前状态

- **实验 001 已验收：** GPIO48 板载 RGB LED 红 → 绿 → 蓝循环，每色约 1 秒；构建、烧录校验、串口和用户实物观察均有记录。
- **管理机制已建立：** 规则、进度和交接入口已提交为 `93c9ce6`；继续随项目状态维护。
- **实验 002 已验收：** 六个串口命令已实现、构建与烧录通过、38 项实机串口检查通过；用户在 VS Code Monitor 中确认红绿蓝保持且 off 熄灯。实验 002 验收时设备启动为 off，不再自动循环。
- **实验 003 第一阶段：已验收（I²C 通信）。** 三环境构建、GPIO48 烧录及写入校验通过，52 项实机串口检查通过；连续两次只发现 0x3C，设备数 1、错误数 0。实验 003 阶段设备运行该版本；当前设备运行实验 006。OLED 型号未确认；第一阶段历史记录保留，第二阶段状态见下一条。见[实验 003](experiments/003-i2c-scan.md)。
- **实验 003 第二阶段：已验收（SH1106 首次显示）。** U8g2 2.36.17 已加入；默认 SH1106，支持串口切换 SSD1306。最终三环境构建和 GPIO48 烧录校验通过，65 项实机串口检查全部通过；用户已确认 SH1106 画面完整、没有问题；SSD1306 对比画面由用户反馈异常，显示未通过；保留 SH1106 为默认方案。
- **实验 004 已验收：** 十种持续表情、一次性眨眼、状态查询与 ASCII 帧缓冲调试已实现；默认开机进入 normal 眼睛画面。三环境构建通过，GPIO48 烧录及区域 hash 校验通过；`scripts/test_serial_eyes.py` 的 244 项串口/软件检查全部通过，十种表情帧缓冲哈希互不相同，自动眨眼在命令服务期间正常发生，内部堆与最大区域传输时间稳定。用户于 2026-11-07 按实验 004 第 9 节逐项观察，确认十种表情、手动/自动眨眼与显示均正常，见[实验 004](experiments/004-oled-eyes.md)。
- **实验 005 已验收：** SG90 单舵机控制已实现：GPIO4、50Hz LEDC、14 位分辨率、软件限位 60–120°、默认输出关闭、非阻塞渐进运动和 `servo stop` 放松策略。三环境构建、GPIO48 烧录校验和 `scripts/test_serial_servo.py` 的 348 项串口/软件检查通过，2 分钟连续运行无失败、无复位、堆稳定。2026-11-07 用户上电完成第 8 节观察，反馈 `servo center`/`75`/`105`/`120`/`60`、运动中 `servo stop` 与恢复、OLED 并行运行全部正常，见[实验 005](experiments/005-servo.md)。
- **实验 006 第一阶段：已验收。** 两个独立 `servo::Controller` 实例：舵机 1 GPIO4/通道 0，舵机 2 GPIO5/通道 1，均 50Hz、14 位、60–120°。保留旧 `servo ...` 命令（仍指舵机 1），新增 `servo1 ...`、`servo2 ...`、`servo both center|stop`。三环境构建、GPIO48 烧录校验和 `scripts/test_serial_dual_servo.py` 的 557 项串口/软件检查通过，2 分钟连续运行无失败、堆稳定。2026-11-07 用户先后确认舵机 1、舵机 2 单独测试和双舵机同时运动正常；运动中 `servo both stop` 因动作过快未能人工复现，仅有软件证据；供电余量与电流未测量。
- **实验 006 第二阶段：已验收。** 新增 `motion neutral|wiggle|together|alternate|stop|status` 非阻塞动作序列和 `mood happy|sad|angry|normal|status|stop` 表情联动；动作参数 75–105°，mood 80–100°、85–95°、82–98°，全部在 60–120° 限位内。新脚本 `scripts/test_serial_motion.py` 的 893 项检查通过（含第一阶段的独立停止回归），2 分钟连续运行 `failures=0`、无复位、堆稳定；GPIO48 已烧录实验 006-2 固件。2026-11-07 用户在外部 5V 上电条件下逐项确认四个动作、运动中 `motion stop`、四个 mood 及 `mood stop` 均正常；验收以用户观察为依据，未做定量测量，见[实验 006](experiments/006-dual-servo.md)。
- **Git 同步：** 用户于 2026-11-07 确认实验 004 验收后授权提交与推送；实现与验收提交 [ba460c2](https://github.com/Sprouting123/ai-desktop-robot/commit/ba460c2b2763706f5aa557e41cc617b28469fd61) 已推送至 `origin/main`，远程分支 commit 与本地一致。实验 006 第一阶段的实现、测试脚本与文档提交 [4693430](https://github.com/Sprouting123/ai-desktop-robot/commit/469343005ba6b7cd3d704b25fd1d6d338ad52d4d) 已于 2026-11-07 推送并核对远程一致。实验 003 两阶段实现提交 [252d4b7](https://github.com/Sprouting123/ai-desktop-robot/commit/252d4b73d483bdb89321c18138efef540e6a40c8) 已推送并核对一致。此前实验 002 用户已授权提交与推送。实验 002 实现提交 [e702fc1](https://github.com/Sprouting123/ai-desktop-robot/commit/e702fc14f8708e335d48b849d8a28a41e2ebfc62) 已于 2026-11-07 推送到 `origin/main`，并通过远程查询核对一致。
- 项目固定路径：`/home/hy/ai-desktop-robot`。
- 仓库：[Sprouting123/ai-desktop-robot](https://github.com/Sprouting123/ai-desktop-robot)，开发分支 `main`。
- 工作规则：[AGENTS.md](../AGENTS.md)；当前实验：[006-dual-servo.md](experiments/006-dual-servo.md)；上一阶段：[005-servo.md](experiments/005-servo.md)；更早：[004-oled-eyes.md](experiments/004-oled-eyes.md)；I²C/显示基线：[003-i2c-scan.md](experiments/003-i2c-scan.md)；RGB 基线：[002-serial-led.md](experiments/002-serial-led.md)；已归档实验：[001-rgb-led.md](experiments/001-rgb-led.md)。

## 长期目标与协作方式

使用 ESP32-S3 经 Wi-Fi 连接云端 AI，逐步实现 OLED 表情、双舵机运动、语音交互和视觉感知，日常运行不依赖电脑或树莓派。

ChatGPT 负责技术指导、原理学习与验收；Codex / Work 负责代码和命令执行、调试、文档及获授权的 Git 操作；用户决定方向并提供必要的接线与实物观察。GitHub 保存工程和项目记录，Obsidian 可用于整理学习笔记；尚未建立自动同步到 Obsidian 的流程。

## 里程碑与证据

| 工作项 | 状态 | 已有结果与依据 |
| --- | --- | --- |
| 本地仓库与 GitHub | 已验收 | 原有 `7a17d0b` 初始化提交；首次实验与照片说明均已完成提交和远程核验，见变更记录 |
| VS Code / PlatformIO / Arduino 环境 | 已验收 | 本地工具安装完成；三个构建环境通过，见实验 001 |
| 实验 001：RGB LED | 已验收 | `6adb065`；GPIO48 烧录与校验通过，用户确认灯光，日志记录 3 个周期 |
| 开发板照片补充 | 已验收 | `53fdc11`；正反面可见标识已写入实验 001，第 2.1 节说明识别边界 |
| 长期管理文档 | 已验收 | `93c9ce6` 已建立规则、进度和 README 导航；本次随实验 002 补充当前接口与交接 |
| 实验 002：串口控制 RGB | 已验收 | 三环境构建、GPIO48 烧录与写入校验、38 项串口检查、Monitor 实测和用户灯光确认均通过，详见实验 002 |
| 实验 003：I²C 扫描 | 已验收 | 三环境构建、GPIO48 烧录与校验、52 项串口检查通过，两次扫描均为 0x3C；见实验 003 |
| OLED 显示阶段 | 已验收 | 最终构建、烧录及 65 项串口检查通过；SH1106 用户确认完整正常，SSD1306 用户反馈异常，不采用为默认方案 |
| 实验 004：OLED 表情引擎 | 已验收 | 三环境构建、GPIO48 烧录校验、244 项串口/软件检查通过；十种表情哈希不同、眨眼与自动眨眼、堆稳定；2026-11-07 用户实物确认十种表情、眨眼与显示均正常，见[实验 004](experiments/004-oled-eyes.md) |
| 实验 005：SG90 单舵机 | 已验收 | 三环境构建、GPIO48 烧录校验、348 项串口/软件检查通过；2 分钟连续运行无失败、堆稳定；2026-11-07 用户上电确认 60–120° 运动、停止/恢复与 OLED 并行正常，见[实验 005](experiments/005-servo.md) |
| 实验 006：双 SG90 舵机（第一阶段） | 已验收 | 三环境构建、GPIO48 烧录校验、557 项串口/软件检查通过；2 分钟连续运行无失败、堆稳定；两个 LEDC 通道独立初始化；2026-11-07 用户确认舵机 1、舵机 2 单独测试及双舵机同时运动正常；运动中 `servo both stop` 未实物复现，供电余量未测，见[实验 006](experiments/006-dual-servo.md) |
| 实验 006：动作序列与表情联动（第二阶段） | 已验收 | 三环境构建、GPIO48 烧录校验、893 项串口/软件检查及 2 分钟连续运行通过；2026-11-07 用户确认 `motion neutral/wiggle/together/alternate`、运动中 `motion stop`、`mood happy/sad/angry/normal` 和 `mood stop` 均正常；未做定量测量，见[实验 006](experiments/006-dual-servo.md) |

“已验收”仅用于已经有相应证据的工作。固件编译成功、日志正常、用户实物确认分别记录；未来未取得观察的硬件实验使用“待实物验收”。

## 已确认的硬件与配置

| 项目 | 当前基线 |
| --- | --- |
| 板卡外观 | 屏蔽罩 `S3-N16R8`、背面 `ESP32-S3`，双 USB-C：`COM` / `USB` |
| 芯片与内存 | ESP32-S3 revision v0.2；16 MB Flash、8 MB 物理 PSRAM，均已读取 |
| RGB | GPIO48；依据原板 MicroPython 脚本和 Arduino 实物验收 |
| PlatformIO 环境 | 默认 `rgb_gpio48`；实验 005 三个环境构建通过，仅 GPIO48 烧录及串口验证，见实验 005 |
| 内存配置 | QIO Flash、OPI PSRAM，`qio_opi`，`default_16MB.csv` |
| 开发依赖 | Core 6.2.0；Espressif32 6.12.0；Arduino 2.0.17；NeoPixel 1.15.5；第二阶段新增 U8g2 2.36.17，详见配置文件 |
| 烧录及串口 | COM 口 USB 串口桥、UART0、115200 baud，USB CDC on boot 关闭 |
| 设备标识 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00`；实验时为 `/dev/ttyACM1` |
| 摄像头 | 实验时 `/dev/ttyACM0` 对应 4K USB 摄像头，不能据编号把它用于烧录 |
| 最新已确认接线 | 用户报告：USB 供电；OLED VCC → 3V3、GND → GND、SDA → GPIO8、SCL → GPIO9；Wire 100kHz |
| SG90 舵机 1（用户报告） | 180° SG90；信号 → GPIO4；红线 → 外部 5V 正极；棕线 → 外部电源负极；ESP32 GND 共地；外部电源标称 5V 5A。2026-11-07 实物运动与停止/恢复经用户确认正常；未做电流或角度测量 |
| SG90 舵机 2（用户报告） | 暂定 180° SG90；信号 → GPIO5；与舵机 1 共用外部 5V 并共地。2026-11-07 用户确认单独测试与双舵机同时运动正常；实际角度、电流未测量 |

用户此前报告已备有 OLED、两个 SG90、INMP441、MAX98357A 与扬声器、5V 5A 电源及基础工具。OLED 已按用户报告接线，实验 003 已确认 0x3C 地址应答，SH1106 首次显示获用户确认，实际控制器型号仍待确认；第一只 SG90 接 GPIO4、第二只接 GPIO5，均由外部 5V 供电并与 ESP32 共地；实验 005 和实验 006 第一阶段的软件与 2026-11-07 实物验收均已通过；其余模块尚未在本工程逐项核验或完成接线实验；机器人摄像头尚未选型，不能与电脑的 USB 摄像头混为一谈。

## 实验 001 的验证摘要

- 三个环境最终构建均为 SUCCESS；GPIO48 最终固件 284656 字节，静态 RAM 使用 19108 字节。
- 写入过程各区域 hash 校验通过；程序输出 `[experiment 001] RGB LED / Arduino`。
- 运行读数：Flash 16777216、物理 PSRAM 8388608、PSRAM 堆 8386279 字节；堆容量与物理容量差异已正确处理。
- 日志捕获连续 9 次红绿蓝命令，首次间隔 1011 ms，后续 7 次均为 1000 ms。
- 用户确认每秒红绿蓝循环正常；确认发生在只修正容量提示之前，灯光代码未改变。
- 原板本来就有 MicroPython RGB 演示，因此上电变色并非新现象；新程序身份由 Arduino 标记、烧录校验及仓库代码证明。
- 原板两个脚本备份在 `work/preflash-micropython/`；构建、烧录及运行原始日志在 `work/`。它们保存在本机并被 Git 忽略；关键结论已进入实验文档。
- 实验 001 文档在实验 002 开发前后 hash 一致，未改动。原自动循环固件保留于 `6adb065` 历史中；当前主程序已更新为实验 002。

## 实验 002 的验证摘要

- 支持 `red`、`green`、`blue`、`off`、`status`、`help`，上电熄灯，无自动循环或 `delay()`。
- 固定 32 字符输入缓冲，CR/LF/CRLF 支持，空行忽略；过长、非法字符整行丢弃，下一行恢复。每轮读取上限 64 字节，避免无限等待输入。
- 三个环境构建成功，约 9.76 秒；GPIO48 烧录约 18.04 秒，各区域 hash 校验通过。固件镜像 285312 字节，静态 RAM 使用 19148 字节。
- 实机测试脚本 `scripts/test_serial_led.py` 的 38 项检查全通过，涵盖状态保持、换行、分片、长度边界、4096 字节级输入、非法字符和恢复。
- PlatformIO CLI Monitor 已实际验证本地回显、Enter 才发送、status/help/off 回复及 Ctrl-C 释放串口；VS Code 的命令名称已核对。
- 用户通过 VS Code Monitor 确认：红、绿、蓝各自保持，off 可熄灭；因此可记为已验收，而不只是日志通过。
- 原始测试资料在本机 `work/002-*.log` 及 `work/002-monitor-transcript.txt`，被 Git 忽略；实验文档保存关键结果，新增测试脚本用于复现。
- 用户已授权提交与推送；实现提交 [e702fc1](https://github.com/Sprouting123/ai-desktop-robot/commit/e702fc14f8708e335d48b849d8a28a41e2ebfc62) 已在 GitHub 上核验。

## 实验 003 第一阶段的验证摘要

- 新增 `i2cscan`；保留原六命令和输入保护，启动标记更新为实验 003。Wire 使用 GPIO8/9、100000Hz，扫描 0x08–0x77，单次事务超时 25ms。
- 三环境构建成功，约 6.04 秒；GPIO48 程序 300817 字节、静态 RAM 19484 字节。
- 目标串口身份及映射已核对；首次烧录因 ACL 缺失返回 Permission denied。用户恢复该设备的 hy 读写 ACL 后，烧录成功，约 18.95 秒，各区域 hash 校验通过。
- 52 项实机串口检查全部通过，覆盖原 38 项回归与 14 项新增检查。两次扫描均只发现 0x3C、errors=0；扫描前后 red 状态保持，最后 off 并关闭串口。屏幕显示未验证，不据地址判定控制器型号。
- 本机原始日志 `work/003-build.log`、`work/003-upload.log`（首次失败）、`work/003-upload-retry.log`、`work/003-serial-test.log` 被 Git 忽略，未归档入库。实验 001 / 002 文档未修改。

## 实验 003 第二阶段的验证摘要

- 上电默认 SH1106 128×64；`oled_sh1106` / `oled_ssd1306` 切换并重画；`oled_status` 查询，复位恢复 SH1106。保留原七命令及输入保护。
- 画面含三行指定文字、全屏边框、四种角落标记、底部驱动名；引脚、地址和频率均不改变。
- 初版在 U8g2 begin 阶段阻塞，原串口回归检测到；改为 Wire 统一管理引脚、U8g2 不重复设置 GPIO 后，最终构建和烧录通过。完整原因及结果见实验 003 第二阶段补充。
- 最终 65 项实机串口检查通过，含原 52 项与新增 13 项。两种驱动切换后绘图调用完成、0x3C 应答、实际 Wire 频率 100000Hz，RGB 状态保持。用户已确认 SH1106 画面完整、没有问题，SH1106 显示已验收；SSD1306 对比画面被用户选为“有错位、裁切或乱码”，具体症状未进一步区分，显示验收未通过。显示兼容性不等于控制器型号鉴定。
- 最终 GPIO48 程序 313541 字节、RAM 20924 字节，烧录约 22.47 秒、各区域 hash 通过。最终日志位于本机 `work/003-oled-fixed-*.log`，被 Git 忽略；初版故障和修正证据见实验 003。

## 实验 004 的验证摘要

- 代码拆分为 `eyes_state`（纯时间状态机）、`eyes_render`（纯绘图）、`eyes_engine`（按需重绘与增量传输）；`main.cpp` 保留原命令并新增眼睛命令。统一接口为 `eyesEngine.setExpression()`。
- 十种持续表情、`eyes blink`、`eyes status`、调试用 `eyes dump` 已实现；开机默认 SH1106 + normal 眼睛。原 RGB、I²C 扫描、OLED 双驱动测试图和输入保护保持不变。
- 动画参数：自动眨眼 normal 3–5 秒，悲伤 5–7 秒、安慰 4.5–6.5 秒、忧郁 6–8 秒、尴尬 3.6–5.6 秒；闭眼保持 200ms；开合 200ms（悲伤 320、安慰 360、忧郁 400）。每次 `update()` 最多发送一个 32 字节区域。
- 三环境构建成功，`rgb_gpio48` Flash 319773 字节、RAM 22084 字节；GPIO48 烧录约 21 秒，各区域 hash 校验通过。
- `scripts/test_serial_eyes.py` 的 244 项检查全部通过：原实验 002/003 回归、十种表情与间隔、ASCII 帧缓冲 32×64 网格、十种帧哈希互不相同、手动/自动眨眼、眨眼中切换表情的取消、30 次快速切换、堆稳定；最大区域传输 4436µs，10 秒内 blinks 由 5 增至 6。
- 3 分钟连续运行：15 次表情切换与周期性驱动切换均无失败，blinks 由 0 增至 27，内部堆 364984 字节保持不变，`min_heap` 359628–359732 字节，无复位。
- 实机原始日志位于 `work/004-build.log`、`work/004-upload.log`、`work/004-upload-final.log`、`work/004-serial-test.log`、`work/004-serial-test-final.log`、`work/004-preview.log`、`work/004-soak.log`，被 Git 忽略，未归档入库。
- 用户于 2026-11-07 按实验 004 第 9 节观察十种表情、手动/自动眨眼与驱动切换，确认均正常，未报告错位、裁切或明显闪烁；实验 004 记为已验收。

## 实验 005 的验证摘要

- 新增 `src/servo_controller.*`，参数集中在 `servo::Config`：GPIO4、LEDC 通道 0、50Hz、14 位、脉宽 600–2400µs、软件限位 60–120°、中位 90°、60°/s、20ms 步进。
- 开机只配置 LEDC 并写 0 占空比，`servo status` 为 `stopped`/`output=off`，不会自动扫动；首次 `servo center` 或角度命令才使能输出。
- `servo center`、`servo 60`–`servo 120`、`servo status`、`servo stop` 已实现；`servo stop` 取消调度并把占空比写 0，舵机放松。原 RGB、I²C、OLED 测试图、十种表情、眨眼和输入保护保持不变。
- 首版使用 16 位 LEDC，启动日志报 S3 最大 14 位、`SERVO_INIT ready=0`；改为 14 位后 `actual_hz=50`、`ready=1`。该问题在烧录后由启动日志发现，未发生舵机运动。
- 最终三环境构建成功；`rgb_gpio48`/`rgb_gpio38` Flash 327349 字节、RAM 22204 字节，`diagnostics` Flash 323981 字节、RAM 22148 字节。GPIO48 重新烧录约 21.4 秒，各区域 hash 校验通过。
- `scripts/test_serial_servo.py` 的 348 项检查全部通过：原实验 002/003/004 回归、舵机启动安全状态、解析与限位、60/75/90/105/120° 脉宽映射、渐进运动、运动中停止与恢复、快速目标切换、OLED 与舵机并行、堆稳定。最大 OLED 区域传输 4455µs，内部堆 364184 字节保持不变，`min_heap` 358532 字节，10 秒内 blinks 由 5 增至 6。
- 2 分钟连续运行：14 次舵机目标、16 次表情切换和周期性 `servo stop` + `servo center`，`failures=0`，blinks 由 0 增至 15，内部堆 364212 字节保持不变，`min_heap` 358852–358888 字节，无复位。
- 自动测试期间保持舵机外部 5V 断开，因此只验证固件、串口和 PWM 逻辑，没有观察到舵机实际运动；测试结束状态为舵机 `stopped`/`output=off`、RGB 熄灭、normal 眼睛。
- 2026-11-07 用户随后接通外部 5V 完成实物步骤：上电后舵机不自动运动；首次 `servo center` 因原位置接近 90° 无可见位移，`servo 105` 确认转动；后续 75/120/60、运动中 stop 与恢复、OLED 并行均反馈正常。
- 原始日志位于 `work/005-build*.log`、`work/005-upload*.log`、`work/005-serial-test.log`、`work/005-soak.log`，被 Git 忽略，未归档入库。
- 实物验收步骤见实验 005 第 8 节；2026-11-07 用户反馈全部步骤正常，实验 005 记为已验收。

## 实验 006 的验证摘要

- `servo::Controller` 复用为两个实例：舵机 1 GPIO4/通道 0，舵机 2 GPIO5/通道 1；参数由 `servo::makeConfig()` 统一生成，均 50Hz、14 位、600–2400µs、60–120°、中位 90°、60°/s、20ms 步进。
- ESP32-S3 的 LEDC 通道 0/1 共用定时器 0，两者配置相同，无频率冲突；通道、引脚、状态分别独立。
- 旧 `servo center`/`servo <角度>`/`servo status`/`servo stop` 保持实验 005 含义（舵机 1），回复文本不变；新增 `servo1 ...`、`servo2 ...`、`servo both center`、`servo both stop`。状态行增加 `channel=`。
- 上电 `SERVO1_INIT`、`SERVO2_INIT` 均 `ready=1`、`output=off`，不自动运动；两只初始均为 `stopped`、参考角度 90°。
- 最终三环境构建成功；`rgb_gpio48`/`rgb_gpio38` Flash 328265 字节、RAM 22252 字节，`diagnostics` Flash 324917 字节、RAM 22196 字节。GPIO48 烧录约 21.3 秒，各区域 hash 校验通过。
- `scripts/test_serial_dual_servo.py` 的 557 项检查全部通过：原实验 002/003/004 回归、双通道启动状态、旧命令兼容、双实例解析与限位、60/75/90/105/120° 脉宽映射、单只停止不影响另一只、`servo both stop/center`、同时运动、运动中停止与恢复、OLED 并行、堆稳定。最大 OLED 区域传输 4433µs，内部堆 364136 字节，`min_heap` 358484 字节。
- 2 分钟连续运行：14 次舵机目标、16 次表情切换和周期性 `servo both stop` + `servo both center`，`failures=0`，两只均观察到 60–120°，blinks 由 0 增至 13，内部堆 364164 字节保持不变，`min_heap` 358808–358836 字节，无复位。
- 自动测试期间外部 5V 断开，舵机 2 未接线，因此没有观察到任何舵机实际运动；设备结束状态为两只 `stopped`/`output=off`、RGB 熄灭、normal 眼睛。
- 原始日志位于 `work/006-build.log`、`work/006-upload.log`、`work/006-serial-test.log`、`work/006-soak.log`，被 Git 忽略，未归档入库。
- 第二阶段新增 `src/motion_engine.*`（动作序列状态机）和 `src/mood_controller.*`（表情与动作映射），`main.cpp` 增加 `motion`/`mood` 命令；`motion stop`、`servo both stop` 停止两只并清序列，新动作覆盖旧动作，手动 `servo` 只丢弃序列、仅改变被命令的通道，无自动恢复或重排队。
- 第二阶段参数：neutral 90/90×1；wiggle 75–105°×6 周期，每周期 4 步，停留 350ms，共 24 步（约 20 秒，便于人工中途停止）；together 和 alternate 75–105°×5 周期，每周期 2 步，停留 350/300ms；mood 参数为 happy 80–100° wiggle 16 步、sad 85–95° wiggle 12 步、angry 82–98° alternate 8 步、normal=neutral。
- 第二阶段最终三环境构建成功，`rgb_gpio48` Flash 331341 字节、RAM 22300 字节；GPIO48 烧录约 21.7 秒，`Hash of data verified`。启动标记为 `[experiment 006-2] OLED eyes + dual SG90 motion/mood / Arduino`，上电不自动动作。
- `scripts/test_serial_motion.py` 的 893 项检查全部通过（约 146 秒）：回归实验 002/003/004 与第一阶段命令，新增动作解析/限位/完成/切换/中途停止/手动接管、mood 映射与状态、`mood stop` 保留表情、`eyes` 只清 mood 不停止动作、动作中非法命令不取消序列、动作期间自动眨眼与 OLED 非阻塞、双路输出最终关闭。最大 OLED 区域传输 4431µs，内部堆 364088 字节、`min_heap` 358436 字节。
- 2 分钟连续运行（`work/006-2-soak.py`）：17 条动作/mood 命令、96 次状态采样，`failures=0`，blinks 由 0 增至 22，两只角度始终在 60–120°，`min_heap` 358764 字节，无复位或卡死。
- 测试发现并修正：手动接管最初会同时关闭另一只舵机，破坏第一阶段的独立停止行为；现改为只丢弃序列、不碰输出。测试正则分组错误也已修正，固件本身无对应问题。
- 第二阶段自动化测试期间外部 5V 始终保持断开，只验证固件、串口和 PWM 逻辑；随后用户按实验 006 第 7.4 节接通外部 5V，逐项确认四个动作、运动中 `motion stop`、四个 mood 和 `mood stop` 均正常，第二阶段记为已验收。验收依据为用户观察，动作方向、幅度、噪声和温度没有定量测量；运动中 `servo both stop` 的实物补测未执行，仍只有软件证据。

## 未决事项与已解决问题

| 事项 | 状态 / 影响 | 后续处理 |
| --- | --- | --- |
| 厂家、完整 PCB 版本及正式模组型号 | 未确认；不阻塞当前已验证的 RGB 配置 | 如后续提供商品资料或更清晰标识，再补充；不能把通用板定义当作实物鉴定 |
| 照片原图归档 | 正反面图片在会话中，识别信息已入库，原图文件未入库 | 原图可作为本地文件取得时，再存入合适的文档资源目录并更新引用；不假称已经保存图片 |
| 串口权限 | 已解除本次阻塞；用户恢复设备级 ACL 后烧录和测试成功 | 重插后若再次拒绝访问，再核对并恢复指定设备权限；见实验 003 |
| USB 数据线 | 前序已通过更换数据线解决 | 连接正常时不重新排查；再次不识别时结合新证据处理 |
| PSRAM 容量误报警 | 已修正，最终日志无该警告 | 后续区分物理容量与可用堆容量 |
| 系统 ROS Python 路径 | 项目 CLI 已可用；排除 `PYTHONPATH` 后依赖检查通过 | 遇到包冲突时按 AGENTS.md 的项目级方法处理 |
| 实验 002 验证 | 已验收；没有已知硬件阻塞 | 保留测试和用户观察结果，继续维护当前串口接口 |
| 实验 002 Git 同步 | 已完成 | 实现提交 [e702fc1](https://github.com/Sprouting123/ai-desktop-robot/commit/e702fc14f8708e335d48b849d8a28a41e2ebfc62) 已推送到 `origin/main` 并核对远程一致 |
| 实验 004 实物验收 | 已完成 | 2026-11-07 用户确认十种表情、眨眼与显示均正常；后续修改渲染或更换屏幕时需重新观察 |
| 实验 004 Git 同步 | 已完成 | 实现与验收提交 [ba460c2](https://github.com/Sprouting123/ai-desktop-robot/commit/ba460c2b2763706f5aa557e41cc617b28469fd61) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地一致 |
| 实验 005 实物验收 | 已完成 | 2026-11-07 用户上电确认 60–120° 运动、停止/恢复与 OLED 并行正常；实际角度与电流未测量 |
| 实验 005 Git 同步 | 已完成 | 实现与验收提交 [f33dd0e](https://github.com/Sprouting123/ai-desktop-robot/commit/f33dd0ef6494d93271a6fd85a918069d772c8a7c) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地一致 |
| 实验 006 第一阶段实物验收 | 已完成，含一项边界 | 2026-11-07 用户确认两只单独测试和双舵机同时运动正常；运动中 `servo both stop` 因动作过快无法人工输入，仅有软件检查证据。第二阶段的 `motion wiggle` 约 20 秒，可用于补做该观察 |
| 实验 006 双舵机供电 | 未测量 | 两只共用 5V 5A 电源；同时动作与堵转电流、电压跌落未测，异常发热立即断开外部 5V |
| 实验 006 第二阶段 | 已验收 | 2026-11-07 用户接通外部 5V，确认四个动作、运动中 `motion stop`、四个 mood 和 `mood stop` 均正常；软件侧另有 893 项串口/软件检查与 2 分钟连续运行证据；未做定量测量 |
| 实验 006 动作中 `servo both stop` | 软件已验证，实物未补测 | 第一阶段因动作过快未复现；第二阶段约 20 秒的 `motion wiggle` 可补测，但用户尚未执行；不影响 `motion stop` 已获实物确认 |
| 实验 006 Git 同步 | 已完成 | 用户授权后，实现、测试脚本与文档提交 [4693430](https://github.com/Sprouting123/ai-desktop-robot/commit/469343005ba6b7cd3d704b25fd1d6d338ad52d4d) 已推送至 `origin/main`；`git fetch` 后核对本地与远程 commit 一致 |

实验 003 已核对 USB 目标；测试完成后脚本关闭了串口，用户可打开 VS Code Monitor。后续烧录或自动测试前，应关闭用户的监视器。

## 下一步与后续候选

**当前下一步：确定实验 007 方向。** 实验 006 两阶段均已验收，动作序列与表情联动可用。候选方向：接入 Wi-Fi 与云端 AI 的最小对话链路、增加麦克风/扬声器、或先做机械结构与供电测量（双舵机同时动作的电流、电压跌落仍未测）。启动前需用户确定优先级、硬件型号与验收标准；可选的实物补测是在 `motion wiggle` 运行中输入 `servo both stop`，补齐第一阶段遗留边界。

下面只是长期目标的拆分候选，尚未排期或获得实施指令：

| 候选功能 | 启动前需明确的内容 |
| --- | --- |
| OLED 表情 | 实际屏幕型号、接口、供电和引脚；首个显示效果的验收标准 |
| 双舵机运动 | 舵机供电、信号引脚、机械约束和首个运动范围 |
| Wi-Fi 与云端 AI | 网络连接目标、服务选择、凭据保存方式和最小交互行为 |
| 麦克风与扬声器 | 模块型号、音频接线、采集/播放参数与独立验收方法 |
| 视觉感知 | 摄像头型号、接口及与现有资源的兼容性；当前未选型 |
| 整机集成 | 各模块分别通过实验后，再规划供电、调度与整机验收 |

实验 002 的既有用户灯光验收保留；当前扫描的 Monitor 操作和结果解读见实验 003。

## 变更记录

| 日期 | 变更 | 证据 |
| --- | --- | --- |
| 2026-11-06 | 建立并验收 RGB 实验，保存工程、配置和实验记录 | [6adb065](https://github.com/Sprouting123/ai-desktop-robot/commit/6adb06554445ba208b6ba03cf86b24f0bbf14730)；实验 001 使用该日作为用户会话日期 |
| 2026-11-07 | 补充正反面照片信息，保留厂家和 PCB 版本未确认的边界 | [53fdc11](https://github.com/Sprouting123/ai-desktop-robot/commit/53fdc11e0206b8fe68bdad27248fdc85bbedc90e) |
| 2026-11-07 | 建立长期管理规则、进度文档与导航，已同步 GitHub | [93c9ce6](https://github.com/Sprouting123/ai-desktop-robot/commit/93c9ce60dc769894af5be5633a9955d9b8d0b3d3) |
| 2026-11-07 | 实验 002 实现与验收：六命令、健壮输入处理、38 项实机检查、Monitor 与用户灯光确认；实验 001 记录保留 | [实验 002](experiments/002-serial-led.md)，实现提交 [e702fc1](https://github.com/Sprouting123/ai-desktop-robot/commit/e702fc14f8708e335d48b849d8a28a41e2ebfc62) 已获授权并推送 |
| 2026-11-07 | 实验 003 第一阶段通信验收：Wire 扫描、三环境构建、烧录校验、52 项实机检查，两次 0x3C 应答；权限阻塞已解除 | [实验 003](experiments/003-i2c-scan.md)；实现提交 [252d4b7](https://github.com/Sprouting123/ai-desktop-robot/commit/252d4b73d483bdb89321c18138efef540e6a40c8) 已推送并核验 |
| 2026-11-07 | 实验 003 第二阶段：增加 U8g2 双驱动串口切换和测试图；最终构建、烧录和 65 项串口检查通过，SH1106 用户实物确认通过，SSD1306 用户反馈异常，默认保留 SH1106 | [实验 003 第二阶段](experiments/003-i2c-scan.md)；实现提交 [252d4b7](https://github.com/Sprouting123/ai-desktop-robot/commit/252d4b73d483bdb89321c18138efef540e6a40c8) 已推送并核验 |
| 2026-11-07 | 实验 004：OLED 表情引擎 V1.0，十种表情、眨眼、状态查询、非阻塞状态机与增量刷新；三环境构建、烧录校验、244 项串口/软件检查通过，用户实物确认十种表情与眨眼均正常 | [实验 004](experiments/004-oled-eyes.md)；实现与验收提交 [ba460c2](https://github.com/Sprouting123/ai-desktop-robot/commit/ba460c2b2763706f5aa557e41cc617b28469fd61) 已推送并核对一致 |
| 2026-11-07 | 实验 005：SG90 单舵机控制，GPIO4、50Hz LEDC（S3 14 位）、60–120° 软件限位、非阻塞渐进运动与 `servo stop` 放松策略；三环境构建、烧录校验、348 项串口/软件检查及 2 分钟连续运行通过；用户上电确认 60–120° 运动、停止/恢复与 OLED 并行正常，记为已验收 | [实验 005](experiments/005-servo.md)；实现与验收提交 [f33dd0e](https://github.com/Sprouting123/ai-desktop-robot/commit/f33dd0ef6494d93271a6fd85a918069d772c8a7c) 已推送并核对一致 |
| 2026-11-07 | 实验 006 第一阶段：两个 `servo::Controller` 实例（GPIO4/通道 0、GPIO5/通道 1），保留旧 `servo` 命令并新增 `servo1`/`servo2`/`servo both`；三环境构建、烧录校验、557 项串口/软件检查及 2 分钟连续运行通过；用户确认两只单独测试和双舵机同时运动正常，运动中 `servo both stop` 未实物复现 | [实验 006](experiments/006-dual-servo.md)；实现与验收提交 [4693430](https://github.com/Sprouting123/ai-desktop-robot/commit/469343005ba6b7cd3d704b25fd1d6d338ad52d4d) 已推送并核对一致 |
| 2026-11-07 | 实验 006 第二阶段：`motion` 非阻塞动作序列与 `mood` 表情联动，含中途停止、切换、手动接管、非法命令保护；三环境构建、烧录校验、893 项串口/软件检查及 2 分钟连续运行通过；用户接通外部 5V 逐项确认动作、停止、mood 与 `mood stop` 正常，记为已验收 | [实验 006](experiments/006-dual-servo.md)；实现与验收提交在授权后推送，提交号由后续同步记录补充 |

## 维护方法

- 每次项目状态有变化，更新日期、当前状态、里程碑、未决事项和下一步；已解决问题保留简短结论，避免重复排查。
- 每次新实验都链接到其独立记录；日志、实测和用户反馈各自标明来源。
- 稳定的协作或硬件约束变化时同时更新根目录 `AGENTS.md`；临时过程细节留在实验记录。
- 在同一任务的 Git 提交中同步相关进度，提交前检查差异，push 前检查状态和远程变化，push 后核对远程提交。
- 文档中的同步描述不能代替 Git 验证。提交号引用既有提交；本次提交与远程一致性由实际 Git 命令核查，避免预写成功状态或循环引用自身提交号。
