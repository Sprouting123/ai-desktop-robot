# 实验 009：MAX98357A I²S 功放与扬声器首次发声

- 状态：**已验收**（第一阶段 2026-11-08 用户确认首次发声；第二阶段中文语音同日晚由用户接通外部 5V 试听确认成功；音质、音量与供电的定量指标未测量）
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

## 9. 第二阶段：播放中文 AI 语音（2026-11-08）

### 9.1 目标与范围

在已验收的 MAX98357A 通路上播放一句自然的中文语音“你好，我是你的 AI 桌宠！”，
并保留以后接入实时云端语音的接口。本阶段：

- 不自行录音、不使用机械拼接音；用现成的中文 TTS 在 Ubuntu 上生成音频。
- 不在 ESP32 上部署 TTS 模型；ESP32 只做只读 PCM 播放。
- 不产生任何付费 API 调用；不接入云端实时 TTS、WebSocket 音频或 Opus 解码。
- 上电仍然静音，只有 `audio hello` 才播放。

### 9.2 TTS 选型

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| A. Edge TTS（免费、非官方 Microsoft 接口） | **采用** | 普通话自然、声音多、无需账号与密钥、无费用；在本机离线调用在线接口，仅联网合成一次 |
| B. 开源本地 TTS（如 CosyVoice） | 备选 | 音质可接受但需下载数 GB 模型与依赖，对“只生成一句话”过重 |
| C. 商业云 TTS | 未采用 | 需要账号、密钥与计费；本阶段未经用户授权不产生付费调用 |

对比的三个普通话声音（同一句、同一语速）：

| 声音 ID | 风格 | 结果 |
| --- | --- | --- |
| `zh-CN-XiaoxiaoNeural` | 女声，Warm | **选用**，语气自然、清晰，适合小扬声器 |
| `zh-CN-XiaoyiNeural` | 女声，活泼 | 语速偏快、音调偏高，试听后未选用 |
| `zh-CN-YunxiNeural` | 男声，Lively | 可听，但与当前桌宠形象不如女声贴合 |

最终参数：`zh-CN-XiaoxiaoNeural`，语速 `-5%`，其余默认。

### 9.3 音频生成与转换

1. 在临时虚拟环境 `work/tts-venv` 安装 `edge-tts 7.3.1`（不进入仓库、不写入依赖清单）。
2. 合成 MP3 到 `work/tts/`（忽略目录，不提交）。
3. 用 ffmpeg 去首尾静音、加 10ms 淡入淡出，再转成 ESP32 直接可用的裸 PCM：

```bash
ffmpeg -i work/tts/hello_zh-CN-XiaoxiaoNeural.mp3 \
  -af "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,areverse,afade=t=in:st=0:d=0.01,areverse,afade=t=in:st=0:d=0.01,areverse" \
  -ar 16000 -ac 1 -sample_fmt s16 -f s16le assets/audio/hello_zh.raw
```

4. 用 `ffprobe` 与逐样本统计核对**实际数据**，而不是只看扩展名：

| 项目 | 实测值 |
| --- | --- |
| 格式 | 16kHz、16bit 有符号小端、单声道裸 PCM（无文件头） |
| 大小 / 帧数 | 78,828 字节 / 39,414 帧 |
| 时长 | 2.463s |
| 峰值 / 平均值 | 约 −3.5dBFS / −18.9dBFS |
| 非零样本 | 39,251（确为真实语音，不是静音或模拟波形） |

第一次转换使用 `silenceremove=stop_periods=1`，在句中第一个停顿处被截断，
只得到 0.44s；改为“去头 → 反转 → 去头 → 反转”后得到完整 2.463s。
音频来源、声音 ID、许可说明见 `assets/audio/README.md`。

### 9.4 存储与播放结构

| 文件 | 作用 |
| --- | --- |
| `assets/audio/hello_zh.raw` | 只读 PCM 资源（78,828 字节） |
| `src/voice_clips.h` | 链接器符号、采样率、音量与 `audio::Clip` 元数据 |
| `src/audio_source.h/.cpp` | `Source` 抽象、`ToneSource`、`FlashClipSource` |
| `src/audio_engine.h/.cpp` | I²S/DMA 输出层，拉取式播放 `ToneSource` 或 `FlashClipSource` |
| `src/main.cpp` | `audio hello` 命令与启动元数据日志 |

- `platformio.ini` 用 `board_build.embed_files = assets/audio/hello_zh.raw` 把文件
  链接进 flash，生成 `_binary_assets_audio_hello_zh_raw_start/_end` 符号；
  固件用两者之差得到真实长度，不手写可能漂移的常量。
- **不把整段音频一次性复制到 RAM**：`FlashClipSource::fill()` 每次只用
  `memcpy_P` 读取 240 帧（480 字节）到 15ms 的静态缓冲，转成双声道并做音量缩放。
- 上电只安装 I²S 驱动并清零 DMA；`audio hello` 才启动播放，不自动播放。
- `Source` 接口只有 `restart()`、`totalFrames()`、`fill()` 三个方法。以后 Wi-Fi
  实时 PCM、Opus 解码或云端流式 TTS 只需实现同一接口，`Engine` 的 DMA 写路径不变。

### 9.5 输出层的两个关键修正

1. **字节指针偏移**：`chunkSent_` 是已写入的**字节数**。原实现写作
   `chunk_ + chunkSent_`，而 `chunk_` 是 `int16_t*`，会按 2 倍字节前进；一旦
   `i2s_write` 只接受部分数据，下一轮就会跳过样本。现在改为
   `reinterpret_cast<const uint8_t*>(chunk_) + chunkSent_`。正常整块写入时两者
   结果相同，因此旧回归没有暴露该问题；本阶段由代码审查确认并修正。
2. **自然结束不截尾**：原实现播放一结束就 `i2s_zero_dma_buffer()`，会把 DMA
   队列里尚未播完的最后几个块清零，语音尾音被切掉。现在区分两种结束：
   - 自然结束：源返回 0 后进入 drain 状态，等待
     `dmaBufferCount × 240 ÷ 16000 + 20ms`（约 80ms）让队列播完，不写零；
     `tx_desc_auto_clear` 保证之后是静音。
   - `audio stop`：仍然立即清零 DMA，做到“马上安静”。
   `plays` 只统计启动次数，自然结束不增加 `stops`。

### 9.6 新增命令

| 命令 | 行为 |
| --- | --- |
| `audio hello` | 播放一次内嵌中文语音；播放中再次发送从头重启并回复 `restarted=1` |
| `audio beep` | 与第一阶段相同（880Hz、300ms、15%） |
| `audio stop` | 立即停止提示音或语音，清空 DMA |
| `audio status` | 增加 `source=tone\|clip\|none`、`clip=名字`、`bytes=`、`frames=` |

`audio status` 空闲时 `source=none clip=- bytes=0 frames=0`；播放语音时为
`source=clip clip=hello_zh bytes=78828 frames=39414`。

### 9.7 验证结果

- 三环境构建：`diagnostics`、`rgb_gpio48`、`rgb_gpio38` 全部 SUCCESS。
- `rgb_gpio48`：Flash 914,909 字节（14.0%），静态 RAM 52,328 字节（16.0%）；
  烧录与哈希校验通过。
- 链接符号核对：`_binary_assets_audio_hello_zh_raw_end - _start = 0x133EC =
  78,828`，与文件大小一致。
- 启动日志新增
  `AUDIO_CLIP name=hello_zh bytes=78828 frames=39414 sample_rate_hz=16000 volume_pct=60`；
  `AUDIO_INIT` 与上电静音行为不变。
- `scripts/test_serial_wifi.py` 完整回归：**1103 项检查全部通过**（Wi-Fi 已连接，
  含 HTTP）。新增检查覆盖：内嵌资源长度、`audio hello` 回复与 `restarted`、
  `source=clip`/`bytes`/`frames`、播放期间 OLED 与动作命令仍响应、播放中重启、
  `audio stop` 中断并清空源、停止后不自动恢复、自然播完回到 `idle`、
  自然结束不增加 `stops`、`errors=0`、堆无异常下降。
  该次回归按规则**保持外部 5V 断开**，功放未供电，验证的是固件行为与状态机，
  **不能证明可听声音**；实际听音随后由用户在 9.8 节确认。
- 部分写入路径（`i2s_write` 只接受部分字节）未被脚本强制触发；该修正是代码级
  修正，正常整块路径由回归持续覆盖。

### 9.8 听音验收（2026-11-08，用户观察）

用户接通外部 5V 后发送 `audio hello`，试听后报告**试听成功**。
这次确认了语音可以通过 MAX98357A 与扬声器实际播放；用户未逐项说明句尾完整性、
爆音与音量主观评价，也未做声压或电流测量。按项目规则，此项记为**已验收
（证据为用户观察）**，不能据此声称音质已定量达标。

本次听音按建议未同时驱动两只舵机。若以后需要调整音量，只改
`src/voice_clips.h` 的 `kHelloVolumePercent`（1–100），不需要改音频文件。
播放中 `audio stop` 的实物复测仍可用这段 2.46 s 语音补做。

### 9.9 后续演进（本阶段不实现）

- 云端实时 TTS：由服务器合成，ESP32 通过 WebSocket/HTTP 接收流式音频。
- Opus 解码：参考 xiaozhi-esp32 的“解码队列 → 播放队列 → 输出任务”结构；
  下行的 Opus 帧解码后作为新的 `Source` 交给现有输出层。
- 网络 PCM 流：实现一个带缓冲和欠载处理的 `StreamSource`，与
  `FlashClipSource` 共用同一拉取接口。
