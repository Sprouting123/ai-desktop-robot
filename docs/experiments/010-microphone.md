# 实验 010：INMP441 I²S 数字麦克风采集

- 状态：**第一阶段已验收**（2026-11-08 用户讲话观察：安静 peak 1% → 说话 peak 6%；三环境构建、烧录与 1151–1152 项回归通过；固件读取右声道）
- 日期：2026-11-08（Asia/Shanghai）
- 前置实验：[009 MAX98357A 音频输出](009-audio-output.md)、[008 Wi-Fi 控制](008-wifi-control.md)

## 1. 目标

第一阶段：在不影响扬声器、OLED、舵机、Wi-Fi 与 HTTP 的前提下，用 INMP441
采集麦克风数据，并通过串口查看近期峰值、RMS 与采样计数。

1. 新建独立的 `microphone_engine` 模块。
2. 使用 Arduino-ESP32 2.0.17 自带的 ESP-IDF legacy I²S 驱动，优先使用
   `I2S_NUM_1` 的 RX 模式。
3. 标准 I²S，16kHz、32bit 接收槽；正确处理 INMP441 的 24bit 有符号采样与
   左声道（实测该模块数据在右声道，最终改为右声道且数据格式不变，见 6.3）。
4. DMA 分块读取，主循环不等待。
5. 新增 `mic status`、`mic start`、`mic level`、`mic stop`。
6. 上电默认不采集、不保存、不上传；未连接或全零数据不虚报成功。

第二阶段（待第一阶段实物确认后）：3 秒 RAM/PSRAM 录音、可靠传输与完整性校验、
Ubuntu 生成 16kHz/16bit/单声道 WAV 并试听。本阶段不接入在线识别、云端 AI 或
任何付费 API。

## 2. 接线（用户报告，待实际接线确认）

| INMP441 | ESP32-S3 | 说明 |
| --- | --- | --- |
| VDD | 3V3 | 模块供电，**不得接 5V** |
| GND | GND | 与 ESP32 共地 |
| SCK | GPIO16 | I²S 位时钟（BCLK） |
| WS | GPIO17 | 左右声道时钟（LRC） |
| SD | GPIO18 | 串行数据（DIN） |
| L/R | GND | 按数据手册应选择左声道；实测该模块仍只在右声道槽输出数据 |

- 用户报告按上表接线，并于 2026-11-08 核对确认接线正确。实测左声道全零、
  右声道有正常数据，因此固件改为读取右声道（详见 6.3），接线本身不改。
- 以上引脚为计划值。用户实际接线与此不同时，以用户确认结果为准，并同步修改
  `src/microphone_engine.h` 的 `kDefaultConfig`。
- INMP441 只使用 3V3；外部 5V 仍只供舵机与 MAX98357A。
- 开发、烧录与自动回归期间保持外部 5V 断开，避免回归中舵机运动与功放发声。

## 3. 设计

### 3.1 I²S 参数

| 项目 | 值 |
| --- | --- |
| 端口 | `I2S_NUM_1`，仅 RX，主模式 |
| 引脚 | BCLK GPIO16、WS GPIO17、DIN GPIO18、无 MCLK |
| 格式 | 标准 I²S（Philips） |
| 采样率 | 16 kHz |
| 槽宽 | 32 bit（`I2S_BITS_PER_SAMPLE_32BIT`） |
| 声道 | `I2S_CHANNEL_FMT_ONLY_RIGHT` + `I2S_CHANNEL_MONO`（实测该模块数据在右槽） |
| DMA | 4 × 256 帧（16 kHz 下每块 16ms，约 64ms 余量） |

- INMP441 输出 24bit 二进制补码，在 32bit 槽内左对齐，低 8 位补零。固件读取
  32bit 字后算术右移 8 位还原 24bit 有符号值；满量程为 2²³ = 8,388,608。
- 扬声器仍使用 `I2S_NUM_0` TX 与 GPIO6/7/15，两个端口、两组引脚互不重叠。

### 3.2 按需初始化

- 上电只调用 `begin()` 打印配置，**不安装 RX 驱动**：不输出时钟、不分配 DMA、
  不采集；`mic status` 显示 `state=idle ready=0`。
- 首次 `mic start` 才安装驱动并开始 RX；`mic stop` 调用 `i2s_stop()` 停止
  外设但保留驱动，便于快速重启。
- `update()` 每轮最多调用一次 `i2s_read(..., 0)`；没有数据立即返回，不阻塞。
- 驱动安装失败时 `mic start` 返回 `ERR mic_not_ready`，`mic status` 显示
  `state=error` 与 `last_error`。

### 3.3 近期统计与静音判断

- 每个 256 帧块记录峰值、平方和与“是否全零”。
- 最近 32 块（约 0.5 秒）组成滑动窗口，`mic level` 输出窗口内的峰值、RMS、
  采样数与块数；停止采集后保留最后一个窗口供查看。
- `signal` 判定：
  - `idle`：未采集；
  - `no_data`：窗口内还没有样本；
  - `zero`：窗口内所有块全部为 0；
  - `ok`：窗口内存在非零样本。
- `mic level` 的 `peak`/`rms` 是 24bit 原始值，另给出相对满量程的整数百分比。
- 注意：非零不代表数据可信。INMP441 未接时数据线悬空可能读到随机噪声，
  固件无法区分“真实环境声”和“悬空噪声”；只有用户对着麦克风讲话并看到
  数值随声音变化，才构成第一阶段实物验收。

### 3.4 串口命令

| 命令 | 行为 |
| --- | --- |
| `mic status` | `MIC state=... ready=... port=1 bclk=16 ws=17 din=18 sample_rate_hz=16000 ... frames=... blocks=... reads=... timeouts=... zero_blocks=... errors=... last_error=...` |
| `mic start` | 开始采集；已运行时回复 `restarted=1` 并重置窗口与计数 |
| `mic level` | `MIC_LEVEL state=... signal=... window_frames=... window_blocks=... peak=... rms=... peak_pct=... rms_pct=... total_frames=... zero_blocks=...` |
| `mic stop` | 停止采集；保留驱动与最后一个窗口，帧计数冻结 |

非法子命令或多余参数返回 `ERR mic_usage; use help`。所有命令都不会保存音频、
写 Flash 或发起网络请求。

## 4. 安全与边界

- 开发、烧录和自动回归期间断开外部 5V；麦克风只用 3V3。
- INMP441 VDD 不得接 5V；SD/SCK/WS 为 3.3V 逻辑。
- 不使用、不保存用户语音；第一阶段只输出统计值，不传输原始音频。
- 保持舵机 60–120° 软件限位与所有既有命令不变。

## 5. 验收标准

1. **软件**：三环境构建通过；原有 1103 项回归继续通过；新增麦克风命令解析、
   启动/停止、统计窗口与错误路径检查。
2. **实物**：用户对麦克风说话时，`mic level` 的 `peak`、`rms` 随音量明显变化，
   安静与大声有明显差异；`mic stop` 后计数不再增加。
3. **兼容**：采集期间 OLED、串口、Wi-Fi/HTTP 与 `audio beep`/`audio hello` 正常。
4. **不虚报**：未接线或数据全零时显示 `signal=zero`/`no_data`，不宣称采集成功。

## 6. 验证结果

### 6.1 构建与烧录

- 三环境 `diagnostics`、`rgb_gpio48`、`rgb_gpio38` 均构建通过。
- 默认环境 `rgb_gpio48`：Flash 918,361 字节（14.0%）、静态 RAM 54,204 字节
  （16.5%）。
- 2026-11-08 通过 COM 口烧录，esptool 写入 918,720 字节并校验哈希通过。

### 6.2 自动回归

- 外部 5V 断开，运行 `.venv/bin/python scripts/test_serial_wifi.py`：
  左声道版本 **1152 项通过**，改为右声道后 **1151 项通过**（实验 009 的 1103 项
  + 49 项麦克风检查），Wi-Fi 已连接且含 HTTP 检查；无复位，`errors=0`、
  `timeouts=0`。两次总计数差 1 来自 `servo_wait_idle` 轮询次数随舵机停止时机
  变化，不是失败项，也不是麦克风检查增减。
- 右声道版本回归中 `mic level` 返回 `signal=ok`，`peak≈1,342,808`、
  `rms≈1,010,716`（约满量程 16%/12%），`zero_blocks=0`；仍未与用户讲话做相关性
  验证。
- 新增检查覆盖：启动只打印 `MIC_CONFIG` 且 `state=idle ready=0`；端口与
  GPIO16/17/18；16kHz/32bit 槽；`mic` 用法错误；空闲 `mic stop`；首次
  `mic start` 的 `MIC_INIT` 与运行状态；窗口累积与 `signal` 一致性；采样计数
  递增；采集期间 OLED、动作与 `audio beep` 正常；重启与停止；停止后计数冻结、
  保留最后窗口；错误计数保持 0。
- 回归证明命令解析与状态机，**不能**证明麦克风实际采集到声音。

### 6.3 串口实测（2026-11-08）

- 启动日志包含 `MIC_CONFIG installed=0 port=1 bclk=16 ws=17 din=18 ...`，
  上电未安装驱动、未采集。
- `mic start` 后驱动安装成功、`timeouts=0`，但按左声道读取时
  `signal=zero`、`peak=0`、`rms=0`、`zero_blocks` 等于全部块数。
- 临时改用右声道读取（诊断构建，未保留）后 `signal=ok`，
  `peak≈1,031,410`、`rms≈835,611`（约满量程 12%/9%），数值随环境声变化，
  `errors=0`。说明 INMP441 已供电且数据正常，但数据出现在**右声道**槽。
- 用户随后核对并确认接线正确（L/R 接 GND），重新发送 `mic status` 仍为
  `signal=zero`、`peak=0`、`rms=0`（`total_frames=301056`）。因此不是接线
  松动，而是该模块的数据实际落在右声道槽，与数据手册的 L/R 低电平=左声道
  不一致（可能为模块丝印/内部选择差异）。
- 结论：固件按实测结果改为 `I2S_CHANNEL_FMT_ONLY_RIGHT` + `I2S_CHANNEL_MONO`，
  仍保持 16kHz/32bit 槽与 24bit 右移 8 位解析；日志和 `mic status` 的
  `channel=` 字段同步改为 `right`。三环境重新构建、烧录，右声道版本完整回归
  1151 项通过，回归中 `signal=ok`；讲话相关性仍待用户观察。

### 6.4 实物验收（2026-11-08 用户观察）

外部 5V 断开，用户通过串口监视器发送命令并记录读数：

| 场景 | peak | peak_pct | rms | rms_pct | 其他 |
| --- | --- | --- | --- | --- | --- |
| 安静 | 163,042 | 1% | 113,461 | 1% | `signal=ok`、`zero_blocks=0` |
| 说话（10–20cm） | 526,968–536,016 | 6% | 102,740–167,133 | 1% | `signal=ok`、`zero_blocks=0` |

- 说话时峰值约为安静的 3.3 倍，说明采集数据与用户讲话相关；
  `rms` 绝对值很小、变化不明显（窗口内间歇讲话与背景声混合），未做定量测量。
- `mic stop` 后连续两次 `mic status` 的 `frames` 均停在 7,370,496，
  `timeouts=0`、`errors=0`，停止后计数冻结。
- 一次误输入 `mic stop\`（多出反斜杠）返回 `ERR mic_usage; use help`，未执行；
  随后正确输入生效，属于预期的非法参数保护。
- 结论：第一阶段实物验收通过，证据为用户提供的串口读数与操作观察；
  音量、灵敏度、频响、噪声底与长时间稳定性未测量。可以进入第二阶段
  （3 秒录音与 WAV 导出）。

