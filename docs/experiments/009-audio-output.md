# 实验 009：MAX98357A I²S 功放与扬声器首次发声

- 状态：**已验收**（2026-11-08 用户确认首次发声；播放状态机经回归验证；音质、音量与供电定量指标未测量）
- 日期：2026-11-08（Asia/Shanghai）
- 前置实验：[008 Wi-Fi 联网与局域网控制](008-wifi-control.md)、[007 纸板机械原型](007-cardboard-prototype.md)

## 1. 目标

1. 用 Arduino-ESP32 2.0.17 自带的 ESP-IDF I²S TX 驱动（legacy `driver/i2s.h`）驱动 MAX98357A，不升级平台、不引入新依赖。
2. 新建独立的 `AudioEngine` 模块，集中管理 I²S 时钟、数据引脚、DMA 缓冲、播放与错误状态。
3. 首次测试采用标准 I²S 格式（16kHz、16bit、双声道相同样本），兼容 MAX98357A 默认的左右混音方式。
4. 只生成简短、低幅度的正弦提示音；上电不自动发声，必须由用户显式发送 `audio beep`。
5. 音频播放非阻塞，OLED 眨眼、Wi-Fi/HTTP、动作引擎和串口响应保持正常。
6. 支持播放中停止、重复触发和初始化失败后的错误报告与恢复，不崩溃、不阻塞。

本阶段不接麦克风、不调用云端 AI、不下载 TTS、不扩展网页音频。

## 2. 硬件与接线（用户报告）

| 信号 | 开发板 / 电源 | 说明 |
| --- | --- | --- |
| MAX98357A VIN | 外部 5V 正极（与两只 SG90 共用，标称 5V 5A） | 开发板 `5Vin` 是输入引脚，不能对外供电；带载能力**待验证** |
| MAX98357A GND | 外部 5V 负极 + ESP32 GND | 必须共地 |
| MAX98357A DIN | GPIO6 | I²S 数据 |
| MAX98357A BCLK | GPIO7 | I²S 位时钟 |
| MAX98357A LRC | GPIO15 | I²S 左右声道时钟（WS） |
| MAX98357A GAIN | 悬空 | 常见模块悬空为默认增益（约 9dB）；模块具体型号未鉴定 |
| MAX98357A SD | 外部 5V 正极 | 拉高为左声道；悬空会使部分模块不工作，实测这样接后发声成功 |
| 扬声器 | 只接功放 SPK+ / SPK− | **扬声器负极不能接电路 GND**，否则是 BTL 输出短路 |

- 开发板排针上的 `5Vin` 是**供电输入**，只进不出；实测悬空约 2V，接功放 VIN 时功放不工作、完全无声。功放必须由外部 5V 供电。
- OLED GPIO8/9、舵机 GPIO4/5、RGB GPIO48 均保持不变。
- 舵机外部 5V 在构建、烧录和自动测试期间必须断开。
- 扬声器标称 3W；本实验只用低幅度短音，不做功率或声压测量。

## 3. 实现摘要

### 3.1 模块

| 文件 | 作用 |
| --- | --- |
| `src/audio_engine.h/.cpp` | I²S TX 初始化、正弦生成、DMA 非阻塞写、停止与状态查询 |
| `src/main.cpp` | `audio beep` / `audio stop` / `audio status` 命令与 `loop()` 调度 |

`AudioEngine` 不接触 OLED、舵机、动作或网络状态，也不被它们调用。音频命令只影响本地提示音。

### 3.2 I²S 配置

- 端口 `I2S_NUM_0`，主模式 TX。
- BCLK GPIO7、LRC/WS GPIO15、DIN GPIO6，MCLK 不输出。
- 16kHz、16bit、双声道（`I2S_CHANNEL_FMT_RIGHT_LEFT`），标准 I²S（Philips）格式。
- 4 个 DMA 缓冲，每个 240 帧（16kHz 下 15ms，共约 60ms 余量）。
- `tx_desc_auto_clear = true`：欠载时输出零，不重复最后一帧，避免结束后出现循环噪声。
- 不启用 APLL，不依赖外部时钟。

### 3.3 提示音与非阻塞

- 880Hz 正弦，300ms，幅度为满量程的 15%（约 −16.5dBFS），首尾各 5ms 线性淡入淡出以抑制爆音。
- `update()` 每轮最多渲染并写入一个 240 帧块；`i2s_write(..., 0)` 超时为零，DMA 满时立即返回 `ESP_ERR_TIMEOUT`，下一轮再写，不等待。
- 播放结束或 `audio stop` 时调用 `i2s_zero_dma_buffer()` 清除 DMA，保证静音。
- 初始化失败时 `beep()` 每次命令重试一次，失败返回 `ERR audio_not_ready`；不会崩溃或进入等待循环。
- 上电只安装驱动并清零 DMA，不发声。

### 3.4 串口命令

| 命令 | 行为 |
| --- | --- |
| `audio beep` | 播放一次提示音；播放中再次发送会从头重启并回复 `restarted=1` |
| `audio stop` | 立即停止并输出静音；空闲时也安全，回复 `OK audio=stopped output=silent` |
| `audio status` | 输出 `AUDIO state=... ready=... driver=i2s_std bclk=... lrck=... din=... rate_hz=... tone_hz=... duration_ms=... amplitude_pct=... plays=... stops=... errors=... last_error=...` |

非法子命令或多余参数返回 `ERR audio_usage; use help`，不改变播放状态。

## 4. 安全要求

- 构建、烧录与自动回归期间舵机外部 5V 保持断开；需要听声音的测试由用户接通外部 5V 后手动执行。
- 首次发声必须由用户亲自发送 `audio beep`；自动化回归在首次发声前使用 `--no-audio-sound` 跳过会发声的检查。
- 低音量、短时长；出现明显爆音、异常发热、供电电压下跌或 ESP32 重启时立即停止并断电检查。
- 扬声器只接 SPK+ / SPK−，不得把任一极接 GND，也不得把扬声器接到电源正负极。
- 功放与舵机共用外部 5V，电源带载能力与同时工作的电流未测量；两者不要同时满负荷运行。
- 外部 5V 不得接到开发板 `5Vin`、3V3 或任何 GPIO。

## 5. 验收标准

1. **软件**：三环境构建通过；原有串口/Wi-Fi/HTTP/OLED/双舵机回归继续通过；音频初始化、命令解析、停止与错误路径有测试。
2. **首次发声**：用户发送 `audio beep`，听到一次短促提示音；`audio stop` 在播放中能立即静音。
3. **非阻塞**：播放期间 OLED 继续眨眼、串口命令及时响应、Wi-Fi/HTTP 正常工作。
4. **无误触发**：上电及任何非 `audio beep` 命令都不会自动发声。

## 6. 验证结果（2026-11-08）

已完成的软件与构建验证：

- 三环境构建：`diagnostics`、`rgb_gpio48`、`rgb_gpio38` 全部 SUCCESS。
- `rgb_gpio48` 默认环境：Flash 833789 字节（12.7%），静态 RAM 51736 字节（15.8%）；烧录校验通过。
- 启动日志：`[experiment 009] MAX98357A I2S audio / Arduino`、`AUDIO_INIT ready=1 driver=i2s_std port=0 bclk=7 lrck=15 din=6 rate_hz=16000 bits=16 channels=2 dma=4 x 240 frames tone_hz=880 duration_ms=300 amplitude_pct=15`、`AUDIO state=idle ... plays=0 stops=0 errors=0 last_error=0`，确认上电不发声。
- `scripts/test_serial_wifi.py --no-audio-sound`：**1050 项检查全部通过**，原有 1038 项 Wi-Fi/HTTP/OLED/双舵机/动作/情绪回归继续通过，新增音频启动状态、引脚与格式、上电不播放、非法命令、空闲停止等检查。
- 首次发声后再次运行完整回归（不加 `--no-audio-sound`）：**1075 项检查全部通过**，新增播放状态机检查——`state=playing`、播放中重复触发 `restarted=1`、播放中 `audio stop`、播放期间动作与串口不被阻塞、播放结束回到 `idle`、上电仍不自动发声。该次回归按规则保持外部 5V 断开、功放未供电，验证的是固件行为，不能证明可听声音。

首次发声与故障排查（用户观察）：

1. 第一次把功放 VIN 接开发板标 `5Vin` 的排针，`audio beep` 返回成功、`plays` 增加、`errors=0`，但完全无声。
2. 万用表测 `5Vin` 对 GND 约 2V；确认 `5Vin` 是板子的**供电输入**，内部只进不出，不能给功放供电。
3. 扬声器用 1.5V 电池瞬碰可听到“咔”声，排除扬声器故障。
4. 改为外部 5V 供电：功放 VIN、SD 接外部 5V 正极，功放 GND 与 ESP32 GND 共地，扬声器仍只接 SPK+/SPK−。
5. 2026-11-08 用户发送 `audio beep`，确认听到一次短促提示音，首次发声通过。

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 首次短促提示音 | 已确认（用户观察） | 外部 5V 供电、SD 接高后听到 |
| 播放中 `audio stop` | 软件已验证，未人工复测 | 提示音仅 300ms，人工输入来不及；状态机由回归覆盖 |
| 上电不自动发声 | 已确认 | 启动后 `plays=0`，多次复位均无声音 |
| 音量、音质、爆音 | 未测量 | 15% 幅度、GAIN 悬空下的主观评价；用户未报告异常 |
| 功放发热与 5V 电压 | 未测量 | 与舵机共用外部 5V，同时负载未测试 |
| 播放时 OLED/Wi-Fi/串口并发 | 软件已检查 | 回归期间播放与动作/串口并行通过；可听声音下的并发未单独量化 |

## 7. 故障处理

- 无声：先确认 `audio status` 为 `ready=1`、`plays` 增加、`errors=0`；再量功放 VIN 对 GND 的电压（约 5V）。开发板 `5Vin` 是输入、不能对外供电（悬空约 2V），功放必须接外部 5V 并共地；SD 悬空可能使模块关闭，可接 5V 拉高；SPK 只接 SPK+/SPK−。
- 爆音或电流声：确认扬声器未接 GND，缩短引线，降低幅度；必要时增大淡入淡出。
- ESP32 重启或电压下跌：立即断开功放 VIN，改用独立 5V 供电并共地。
- 权限：串口重新插拔后临时 ACL 可能失效，用 `sudo setfacl -m u:<用户>:rw /dev/ttyACM1` 恢复，不扩大权限范围。

## 8. 学习要点

- MAX98357A 没有配置总线，采样率、位深由 BCLK/LRC 决定；SD/GAIN 的引脚电平决定声道模式与增益。
- 双声道写入相同样本，可以让左、右、混合三种默认模式都输出同一个音。
- I²S 播放必须由状态机分块喂 DMA；`i2s_write` 的超时要设为 0，否则会拖住主循环。
- `tx_desc_auto_clear` 与结束时的 DMA 清零，决定停止后是静音还是重复噪声。
- 开发板排针上的 `5Vin` 是输入，不能作为外部模块的电源；功放、舵机这类负载要用独立 5V 并共地。
- 三电平 SD 引脚不能悬空；接高电平最稳妥。
