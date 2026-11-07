# 实验 006：双 SG90 舵机协同控制

- 日期：2026-11-07（Asia/Shanghai）。
- 状态：**第一阶段、第二阶段均已验收（2026-11-07）。** 第一阶段由用户确认舵机 1、舵机 2 单独测试和双舵机同时运动正常；第二阶段已实现动作序列与表情联动，893 项串口/软件检查和 2 分钟连续运行通过，用户随后按第 7.4 节逐项确认 `motion`、中途停止和 `mood` 联动正常，见第 8 节。
- 基线：实验 005 的单舵机控制、实验 004 的十种 OLED 表情与眨眼均已验收，历史记录不修改。
- 目标：在保留全部旧命令的前提下，让两只 SG90 各自独立控制（第一阶段），再实现非阻塞的动作序列、中途取消、手动接管和表情联动（第二阶段），为后续 Wi-Fi / 云端 AI 调用预留统一入口。

## 1. 阶段划分与验收标准

### 1.1 第一阶段：双舵机独立控制（已验收）

软件验收：

- `diagnostics`、`rgb_gpio48`、`rgb_gpio38` 三个环境构建成功；GPIO48 固件烧录及区域 hash 校验成功。
- 两个 LEDC 通道分别初始化成功，上电都不输出脉冲。
- 旧命令 `servo center`、`servo <角度>`、`servo status`、`servo stop` 保持实验 005 的含义，仍指向舵机 1。
- 新增 `servo1 ...`、`servo2 ...` 分别独立控制两个通道；`servo both center`、`servo both stop` 同时作用于两只。
- 两只的角度、目标、运动状态和停止状态互不干扰；越界、非数字、负数和多余参数被拒绝且不改变状态。
- 运动按 20ms 步进渐进，OLED 眨眼和串口命令保持响应；自动化测试和连续运行无失败、无复位、堆稳定。

实物验收（已完成）：舵机 1、舵机 2 单独运动正常；双舵机同时运动和 `servo both center` 正常。运动中 `servo both stop` 因 60°/s 太快未能人工复现，仅有软件证据。

### 1.2 第二阶段：动作序列与表情联动（已验收）

软件验收：

- 新增 `motion neutral|wiggle|together|alternate|stop|status`，所有动作都有明确终点，不无限循环。
- 新增 `mood happy|sad|angry|normal|status|stop`，每种 mood 对应一个明确的表情和动作参数；`mood stop` 明确说明屏幕是否保留表情。
- 全部 `eyes` 命令保留；`eyes` 命令不会隐式启动或停止动作。
- 动作使用 `millis()` 非阻塞状态机，不用长 `delay()`；OLED 表情、自动眨眼和串口命令在动作期间保持响应。
- 中途 `motion stop` 立即停止；新动作覆盖旧动作；手动 `servo1`/`servo2`/`servo` 取消自动序列；`servo both stop` 停止全部并清除序列。
- 非法参数不改变任何现有动作或舵机状态；角度不绕过舵机层 60–120° 限位；取消后不自动恢复、不重新排队。
- 三个环境构建成功、烧录校验通过，自动化测试和短时连续运行无失败、无复位、堆稳定。

实物验收（已完成，2026-11-07，分步进行，见第 7.4 节）：

- `motion neutral`、`motion wiggle`、`motion together`、`motion alternate` 的动作方向和幅度符合设计。
- 长动作途中输入 `motion stop` 能立即停止，之后不复位、不续跑。
- `mood happy/sad/angry/normal` 的表情与动作同时出现；`mood stop` 后屏幕保留表情、舵机停止输出。
- 动作期间 OLED 仍能眨眼，串口仍能及时响应。

## 2. 硬件、接线与安全

| 信号 | 连接 |
| --- | --- |
| 舵机 1 信号 | GPIO4，LEDC 通道 0 |
| 舵机 2 信号 | GPIO5，LEDC 通道 1（用户报告已接线；2026-11-07 单独测试与双舵机运动已确认） |
| 两只舵机电源 | 共用外部 5V 标称电源，红线接正极、棕线接负极 |
| 共地 | ESP32 GND ↔ 外部电源负极 |
| ESP32 供电 | USB（COM 口） |
| OLED | ESP32 3V3、GPIO8/9、0x3C、100kHz |
| RGB | GPIO48 |

- GPIO5 在 ESP32-S3 上不是启动 strapping 引脚；Flash/PSRAM 使用模组内部 SPI 引脚，OLED 使用 GPIO8/9，RGB 使用 GPIO48，GPIO5 在软件和实物上均已验证可用。
- 两只舵机由同一 5V 电源供电；标称 5A 电源在空载时测得 5.49V，但双舵机同时启动、堵转时的电流余量尚未测量。
- 首次测试不安装摇臂、不带机械负载；开发、烧录和自动串口测试期间保持外部 5V 断开。
- 禁止把外部 5V 接到 ESP32 3V3 或任何 GPIO；发现堵转、异常发热、持续抖动或线缆松动时立即断开外部 5V。
- 关闭 PWM 只表示不再发送脉冲，不等于切断舵机电源，也不等于机械制动：舵机在 `stop` 后放松，外力仍可推动。
- 动作序列的软件限位为 60–120°，第二阶段实际动作参数限制在 75–105°（mood 为 80–100°、82–98°、85–95°），不接近限位边缘。

## 3. 设计与通道分配

### 3.1 两个独立舵机控制器

两个独立 `servo::Controller` 实例共用同一份参数结构，参数来自 `src/servo_controller.h`：

| 参数 | 舵机 1 | 舵机 2 |
| --- | --- | --- |
| 信号引脚 | GPIO4 | GPIO5 |
| LEDC 通道 | 0 | 1 |
| 刷新频率 | 50Hz | 50Hz |
| 分辨率 | 14 位 | 14 位 |
| 软件限位 | 60–120° | 60–120° |
| 中位 | 90° | 90° |
| 脉宽范围 | 600–2400µs | 600–2400µs |
| 运动速度 | 60°/s，20ms 步进 | 60°/s，20ms 步进 |

ESP32-S3 的 LEDC 通道 0 和 1 共用定时器 0（Arduino-ESP32 2.0.17 的 `ledcSetup` 映射为 `timer = (channel / 2) % 4`）。本次两个通道都配置为 50Hz、14 位，因此共用定时器不会产生频率冲突；将来若某只舵机需要不同频率，应改用通道 2/3 等独立定时器。

每个实例自己保存角度、目标、运动与输出状态；`loop()` 依次调用两个实例的 `update()`，每次最多各走一步，不等待、不阻塞。

### 3.2 `motion::Engine`：动作序列

`src/motion_engine.h/.cpp` 中的 `Engine` 只持有两个 `servo::Controller` 的引用，负责“下一步把目标设成多少”，不复制 PWM、限位或渐进逻辑。角度、重复次数和停留时间集中在 `Profile` 中，修改动作形状不需要改命令解析或状态机。

| 动作 | 每一步 | 每周期步数 | 默认参数 | 总步数 | 设计时长（约） |
| --- | --- | --- | --- | --- | --- |
| `neutral` | 两只回中位 | 1 | 90/90，1 周期，无停留 | 1 | 立即 |
| `wiggle` | 舵机 1 低→高，舵机 2 低→高（另一只保持 90°） | 4 | 75–105°，6 周期，停留 350ms | 24 | 20s |
| `together` | 两只同时低→高 | 2 | 75–105°，5 周期，停留 350ms | 10 | 9s |
| `alternate` | 一只低另一只高，交替 | 2 | 75–105°，5 周期，停留 300ms | 10 | 8s |

`wiggle` 故意设计为约 20 秒的小幅动作，让用户有足够时间输入 `motion stop`；这也补上了第一阶段“动作太快无法人工停止”的观察条件。

状态机（全部基于 `millis()`，不阻塞）：

- `start()` 先检查两个控制器 `ready()` 和参数合法性，设置 `stepsPerCycle_`、`totalSteps_ = stepsPerCycle × cycles`，并立即下发第 1 步目标。
- `update()` 在 `WaitMove` 阶段等待两只都不再运动；若有停留时间，进入 `Dwell`，用回绕安全的 `(int32_t)(now - deadline) >= 0` 判断结束。
- 还有下一步时调用 `beginStep()`；全部走完后两只 `center()`，进入 `Center`，等两只到位后清空名称、步数和目标，回到 `idle`，输出保持开启并锁定在中位。
- `setAngle()` 任一步失败会调用 `stop()`，避免只停一半；不会留下“继续跑”的旧目标。
- `stop()`：停止两只、关闭脉冲，状态记为 `stopped`，清空序列；`cancel()`：只丢弃序列，不动任何输出，供手动命令接管。

状态查询为一行 `MOTION`，例如：

```text
MOTION name=wiggle state=running phase=dwell step=8 total=24 angle1=75 target1=75 moving1=0 output1=on angle2=90 target2=90 moving2=0 output2=on
```

### 3.3 `mood::Controller`：表情与动作的唯一入口

`src/mood_controller.h/.cpp` 把一个表情和一个动作参数绑定起来，是将来云端 AI 可以直接调用的一层：

| mood | 表情 | 动作 | 参数 | 总步数 |
| --- | --- | --- | --- | --- |
| `happy` | happy | wiggle | 80–100°，4 周期，停留 350ms | 16 |
| `sad` | sad | wiggle | 85–95°，3 周期，停留 700ms | 12 |
| `angry` | angry | alternate | 82–98°，4 周期，停留 150ms | 8 |
| `normal` | normal | neutral | 中位 | 1 |

行为约定：

- `start()` 先启动动作，成功后才切换表情；动作启动失败时表情保持不变，避免“脸变了但没动”。
- `mood stop` 停止动作、关闭两路脉冲，**屏幕保留当前表情**；回复明确写出 `screen=kept expression=...`。
- `mood status` 先输出 `MOOD mood=... expression=... motion=...`，随后输出一行完整 `MOTION` 状态。
- 直接 `eyes <表情>` 会清除 mood 标签，但不会停止正在运行的动作；动作结束后也不会重新套用表情。
- 直接 `motion ...` 会清除 mood 标签，但不会重置表情。
- 手动 `servo`/`servo1`/`servo2` 会丢弃自动序列并清除 mood 标签；只有被命令的那一路舵机改变状态，另一路保持原输出和最后目标（与第一阶段独立性一致）。
- `servo both stop`、`motion stop` 会停止两只并清除序列；前者同时清除 mood 标签，后者屏幕保持。
- 所有取消都是单向的：不自动恢复、不重新排队。

## 4. 串口接口

大小写不敏感，行尾支持 LF/CR/CRLF，仍受 32 字符缓冲和非法字符保护。

### 4.1 第一阶段的舵机命令（保持不变）

| 命令 | 行为 | 典型回复 |
| --- | --- | --- |
| `servo center` | 舵机 1 回中位（实验 005 兼容） | `OK servo=center angle=90` |
| `servo <60-120>` | 舵机 1 渐进到角度（实验 005 兼容） | `OK servo=target angle=75` |
| `servo status` | 查询舵机 1，输出 `SERVO ...` | `SERVO state=... channel=0` |
| `servo stop` | 停止舵机 1 并关闭其脉冲 | `OK servo=stopped output=off` |
| `servo1 center` / `<角度>` / `status` / `stop` | 显式控制舵机 1 | `OK servo1=...` / `SERVO1 ...` |
| `servo2 center` / `<角度>` / `status` / `stop` | 控制舵机 2 | `OK servo2=...` / `SERVO2 ...` |
| `servo both center` | 两只同时回中位 | 两行 `OK servo1=center ...`、`OK servo2=center ...` |
| `servo both stop` | 两只同时停止、关闭脉冲，并清除动作和 mood | 两行 `OK servo1=stopped ...`、`OK servo2=stopped ...` |

### 4.2 第二阶段的新命令

| 命令 | 行为 | 典型回复 |
| --- | --- | --- |
| `motion neutral` | 两只回中位，动作结束保持输出 | `OK motion=neutral steps=1` |
| `motion wiggle` | 约 20 秒的小幅交替摆动 | `OK motion=wiggle steps=24` |
| `motion together` | 两只同步摆动 | `OK motion=together steps=10` |
| `motion alternate` | 两只反向交替摆动 | `OK motion=alternate steps=10` |
| `motion stop` | 立即停止两只并关闭脉冲，清除波动 | `OK motion=stopped output=off` |
| `motion status` | 名称、状态、阶段、步数、两只角度/目标/输出 | 一行 `MOTION ...` |
| `mood happy` / `sad` / `angry` / `normal` | 同时设置表情和对应动作 | `OK mood=happy expression=happy motion=wiggle` |
| `mood stop` | 停止动作、关闭脉冲，屏幕保留表情 | `OK mood=stopped output=off screen=kept expression=happy` |
| `mood status` | mood、表情和动作状态 | 两行 `MOOD ...` + `MOTION ...` |

非法用法统一回复：`ERR motion_usage; use help`、`ERR mood_usage; use help`；控制器未就绪时为 `ERR servo_not_ready`。空参数、未知名称、多余参数、超长行和非法字符都不会改变当前动作。

## 5. 构建与烧录结果

- 第二阶段最终三环境构建：`diagnostics`、`rgb_gpio48`、`rgb_gpio38` 全部 SUCCESS。
- `rgb_gpio48`：Flash 331341 字节（5.1%），静态 RAM 22300 字节（6.8%）。
- GPIO48 固件烧录约 21.7 秒，写入区域 `Hash of data verified`。
- 启动日志：

```text
[experiment 006-2] OLED eyes + dual SG90 motion/mood / Arduino
I2C_INIT ready=1 sda=8 scl=9 frequency_hz=100000 timeout_ms=25
[hardware] chip=ESP32-S3 cores=2 flash=16777216 psram_chip=8388608 psram_heap=8386279
SERVO1_INIT ready=1 pin=4 channel=0 requested_hz=50 actual_hz=50 resolution_bits=14 output=off center=90 range=60-120 pulse_us=600-2400 speed_dps=60 step_ms=20
SERVO2_INIT ready=1 pin=5 channel=1 requested_hz=50 actual_hz=50 resolution_bits=14 output=off center=90 range=60-120 pulse_us=600-2400 speed_dps=60 step_ms=20
EYES_MODE driver=SH1106 expression=normal auto_blink=1
```

两个通道初始化成功，均从 0 占空比开始，没有上电运动；上电不会自动启动任何动作或 mood。原始构建、烧录和测试日志在 `work/`，被 Git 忽略，未归档入库。

## 6. 自动化测试

### 6.1 第一阶段记录（历史，557 项）

脚本 `scripts/test_serial_dual_servo.py`，557 项检查全部通过。覆盖实验 002/003/004 回归、双通道初始化、旧命令兼容、越界拒绝、角度/脉宽映射、单只停止不影响另一只、`servo both center|stop`、快速连续目标和 OLED 并行；2 分钟连续运行无失败、无复位、堆稳定。详细结果保留在本文档此前的记录中（见 Git 历史）。

### 6.2 第二阶段（893 项，2026-11-07）

脚本：`.venv/bin/python scripts/test_serial_motion.py`（先关闭监视器，外部 5V 断开）。脚本核对设备身份后复位板卡，回归实验 002/003/004 与全部第一阶段命令，再覆盖第二阶段。

结果：**893 项检查全部通过**，约 146 秒。主要新增覆盖：

- `motion`/`mood` 的空参数、未知名称、多余参数、超长行和非法字符全部拒绝，且不改变现有序列。
- 上电和手动移动后 `MOTION` 为 `none/idle`、步数 0；`motion neutral` 最终 90/90、输出保持。
- `motion wiggle` 总步数 24，运行期间轮询到多个不同步号；两只角度始终在 75–105°。
- 动作期间 `eyes` 仍为 `mode=eyes`、自动眨眼计数增加，最大区域传输 4431µs，未出现阻塞式长传输。
- `motion stop` 立即把两只变为 `stopped`、`pulse_us=0`、输出关闭；等待 1 秒后仍为 `stopped`，没有恢复旧步骤。
- `motion alternate` 运行中切换到 `motion together`，步号从 1 重新计数、总步数 10，旧序列不残留；`together` 完成后回到 90/90 并保持输出。
- 手动 `servo1 80` 取消序列：mood 和动作名称清空、引擎 `idle`，被命令的舵机目标 80，另一只保持使能和中位；`servo both stop` 可在动作中同时停止两只。
- mood 映射逐一核对：happy → wiggle 16 步、80–100°；sad → wiggle 12 步、85–95°；angry → alternate 8 步、82–98°；normal → neutral。
- `mood stop` 回复 `screen=kept`，mood 标签清除、表情保留、两路输出关闭。
- `eyes sad` 只清除 mood 标签、不停止动作；`motion alternate` 清除 mood 但保留 happy 表情；手动 `servo2 80` 同时清除 mood 和序列；`servo both stop` 清除 mood 与动作但保留 sad 表情。
- 动作进行中的非法 `motion sway`、`servo1 abc` 不会取消当前序列。
- 结束时两只舵机停止、脉冲为 0、RGB 熄灭、SH1106 眼睛画面恢复，堆 `364088` 字节、`min_heap` `358436` 字节。

测试暴露并修正了两个问题：

- **手动接管误停另一只**：最初的 `takeManualServoControl()` 调用 `motionEngine.cancel()` 时同时关闭两只脉冲，导致 `servo2 stop` 把正在保持的舵机 1 也停掉，破坏第一阶段“停止一只不影响另一只”的已验收行为。改为“只丢弃序列、不碰输出”，手动命令只改变被命令的通道。
- **测试正则分组错误**：新增的 `MOTION` 正则按字段顺序分组，测试最初把 `moving` 当成 `output`、把 `output1` 当成 `angle2`，造成误报；修正分组后全部通过，固件无此问题。

### 6.3 连续运行（2 分钟）

脚本 `work/006-2-soak.py`（本机临时文件，被 Git 忽略），每 8 秒轮换 `motion wiggle/alternate/together` 和 `mood happy/sad/angry/normal`，每 4 条命令后追加一次 `motion stop`；每秒查询一次 `motion status` 和 `eyes status`。

结果：`elapsed_s=122 commands=17 samples=96 blinks=0->22 min_heap=358764 failures=0`。96 次采样中两只角度始终在 60–120°，自动眨眼持续发生，无复位、无卡死。

测试期间外部 5V 始终保持断开，因此只验证固件、串口和 PWM 逻辑，**没有观察到任何舵机的实际运动**。

## 7. 实物验收步骤

### 7.1 第一阶段：舵机 1（2026-11-07 已确认）

用户按原步骤测试 `servo1 center/75/105/center/stop`，确认舵机 1 动作渐进、方向正常，舵机 2 不动。

### 7.2 第一阶段：舵机 2（2026-11-07 已确认）

用户把舵机 2 信号接 GPIO5 后测试 `servo2 center/75/105/center/stop`，确认舵机 2 单独运动正常，舵机 1 保持不动。

### 7.3 第一阶段：双舵机（2026-11-07 已确认，含边界）

用户确认 `servo both center` 和两只同时按各自目标运动正常；运动中 `servo both stop` 因 60°/s 太快未能人工复现，只有软件证据。第二阶段的 `motion wiggle` 持续约 20 秒，可用于补做这项观察。

### 7.4 第二阶段：动作与表情联动（2026-11-07 已完成）

准备：保持两只舵机按当前接线（舵机 1 → GPIO4，舵机 2 → GPIO5，外部 5V 共地），不装摇臂；先运行 `servo both stop` 和 `eyes normal`，再给外部 5V 上电。上电后两只都不应自动运动。

逐步执行并在每一步后反馈现象，确认无误再做下一步：

1. **`motion neutral`**：两只使能并回到中位。若本来就在 90°，可能看不到明显动作，这是正常的；`motion status` 应为 `name=none state=idle`、角度 90/90、输出 `on`。
2. **`motion wiggle`**：舵机 1 先小幅摆到 75°、105°，再轮到舵机 2；另一只保持中位。动作约 20 秒，结束时回到 90°。观察动作是否平滑、方向是否符合预期、电源和舵机是否异常发热。
3. **`motion together`**：两只同时向同一方向摆到 75°、105°，再同时回摆，约 9 秒后停在 90°。
4. **`motion alternate`**：一只到低角度时另一只到高角度，交替进行，约 8 秒后回到 90°。确认两只不会相互碰撞（当前无摇臂、无限位机械结构）。
5. **中途停止**：重新输入 `motion wiggle`，在它仍在运动时输入 `motion stop`。两只应立即停止并放松（可用手轻推确认无保持力），之后不再自行恢复；`motion status` 应为 `state=stopped`、两路 `output=off`。可再输入 `motion wiggle`，在其中途用 `servo both stop` 重复一次，补做第一阶段的实物边界。
6. **`mood happy`**：屏幕切到 happy 表情，同时两只做 80–100° 的轻柔摆动（16 步），结束后停在 90° 并保持。观察表情和动作是否同时出现。
7. **`mood sad`**：屏幕切到 sad 表情，动作更慢、更小（85–95°，停留 700ms）。确认与 happy 的节奏差异可辨。
8. **`mood angry`**：屏幕切到 angry 表情，两只快速反向交替（82–98°，停留 150ms），约 3–4 秒结束。
9. **`mood normal`**：屏幕回到 normal，两只回到中位。
10. **`mood stop`**：再执行一次 `mood happy`，动作期间输入 `mood stop`。两只立即停止并放松，屏幕**保持 happy 表情**；随后 `eyes sad` 应能正常切换表情，且不会重新启动动作。
11. 全部完成后输入 `servo both stop`、`eyes normal`、`off`，再断开外部 5V。

若出现堵转、异常发热、抖动、线缆松动或动作方向与预期不符，立即断开外部 5V 并记录命令、现象和时间；不要继续下一步。

2026-11-07 用户按上述步骤在外部 5V 上电条件下实测，逐项反馈“正常”：`motion neutral`、`motion wiggle`、`motion together`、`motion alternate` 均正常；`motion wiggle` 运动中的 `motion stop` 正常；`mood happy`、`sad`、`angry`、`normal` 均正常；`mood stop` 步骤正常。反馈为逐项确认，没有提供角度、方向、噪声或温度的定量描述。第 5 步中可选的 `servo both stop` 动作中补测未执行，该边界仍只有软件证据。

## 8. 结果与边界

- **第一阶段：已验收（2026-11-07）。** 舵机 1、舵机 2 单独测试和双舵机同时运动获用户确认；`servo both center` 正常；运动中 `servo both stop` 未取得实物观察，只有软件检查证据。
- **第二阶段：已验收（2026-11-07）。** 三环境构建、GPIO48 烧录校验、893 项串口/软件检查和 2 分钟连续运行均通过；用户随后在外部 5V 上电条件下逐项确认四个动作、运动中 `motion stop`、四个 mood 和 `mood stop` 正常。验收依据是用户观察，动作方向、幅度、噪声和温度没有定量测量；`servo both stop` 的动作中实物补测未执行，仍只有软件证据。
- 动作参数只限制在 60–120° 软件限位以内；舵机层仍会拒绝越界目标，动作引擎不提供绕过路径。
- 双舵机同时动作的供电余量、电压跌落、堵转电流未测量；平滑度、噪声、实际角度和发热只做了主观观察，未用仪器测量。
- 角度、脉宽、状态机只证明固件按设计输出，不能证明舵机实际到达对应角度；没有角度标定、电流测量或带载测试。
- 关闭 PWM 不是切断电源或机械制动；`stop` 后外力仍可推动舵机，角度模型会因此偏离。
- 第二阶段尚未接入 Wi-Fi 或云端 AI；`mood` 是未来云端调用的软件入口，不是已经存在的联网能力。

## 9. 已解决问题

- **通道共用定时器**：Arduino-ESP32 2.0.17 中通道 0/1 共用定时器 0；两个实例都使用 50Hz、14 位，重复 `ledcSetup` 不会改变有效配置。
- **旧命令兼容**：`servo ...` 保留为舵机 1 的别名，回复仍为 `OK servo=...`；新接口使用 `servo1`/`servo2` 前缀。
- **动作不阻塞**：动作引擎只设置目标并等待 `moving()`，PWM 步进仍在舵机层；OLED 区域刷新和串口解析共享同一个 `loop()`。
- **手动接管边界**：最初手动命令取消序列时顺带关闭了两路脉冲，破坏单只独立性；现改为只丢弃序列，手动命令仅改变自己的通道，另一只完成最后目标并保持。
- **测试时序**：`motion neutral` 从中位出发可能在状态查询前就完成，测试最初强制要求动作名称仍为 `neutral` 而误报；现已允许 `neutral` 或已完成后的 `none`。
- **测试分组**：`MOTION` 正则新增字段后分组序号变化，测试曾把 `moving` 当 `output`；修正后通过，固件行为未变。

## 10. 尚未解决的问题

- 双舵机同时动作的电流、电压跌落和供电余量未测量。
- 第二阶段的动作方向、幅度、停止效果和 mood 区分度已获用户“正常”确认，但没有定量测量；若后续装摇臂或增加负载，需要重新观察。
- 运动中 `servo both stop` 的实物补测仍未执行（第一阶段遗留边界）；`motion stop` 已在实物上确认。
- 600–2400µs 与 60–120° 是否需要按两只实物分别校准，尚未确定。
- 无位置反馈；`servo stop` 后手搬摇臂会使角度模型失效。
- 动作序列与 Wi-Fi/云端 AI 的接口尚未设计；当前只有串口命令和 `mood::Controller` 这一层软件入口。

## 11. 学习要点

- **分层**：`servo::Controller` 管 PWM 与限位，`motion::Engine` 管序列，`mood::Controller` 管表情与动作的组合；每层只做一件事，新增动作不需要改 PWM 代码。
- **非阻塞状态机**：用“当前阶段 + millis 截止时间”代替 `delay()`，才能让 OLED、串口和两只舵机共享一个 `loop()`。
- **明确终点**：每个动作都有有限步数和固定的收尾中位，避免上电自动运动和无限循环；需要持续动作时应由上层重新发起。
- **取消语义**：停止（关脉冲）和取消（只丢弃序列）是两件事；手动控制一只舵机时不应擅自关闭另一只。
- **验证边界**：构建成功、PWM 数值正确、状态机到达 `idle`，都不能证明舵机实际运动或表情可读；实物验收必须分步、可中断、可复现。
