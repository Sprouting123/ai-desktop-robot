# AI 桌宠机器人项目协作规则

本文件适用于整个仓库。项目根目录固定为 `/home/hy/ai-desktop-robot`；在现有工程内继续开发，保留已有文件与 Git 历史。

## 项目目标与分工

- 长期目标：ESP32-S3 通过 Wi-Fi 连接云端 AI，逐步实现 OLED 表情、双舵机运动、语音交互和视觉感知；日常运行不依赖电脑或树莓派。
- 用户决定需求与阶段优先级，完成必要的接线、按键及实物观察。
- ChatGPT 负责技术指导、原理讲解和阶段验收；Codex / Work 负责代码、命令执行、调试、实验记录及获授权的 Git 操作。
- 用中文简明汇报实际结果和学习要点，避免直接粘贴大段代码。需要人手操作时给出明确的一步，并说明如何判断完成。
- 不把计划、编译成功、烧录成功、日志输出和实物验收混为一谈；没有观察到的结果明确标为未验证。

## 每次开始工作

1. 阅读本文件、[当前进度](docs/progress.md)及与本次任务相关的实验记录。
2. 检查 `git status --short --branch --untracked-files=all`，读取准备修改的文件，保留用户及其他会话的改动。
3. 从进度中的“下一步”继续，结合当前用户指令调整；已有的验收结论作为起点，只在设备、接线、配置改变或出现新问题时重新核验。
4. 硬件访问前核对目标设备与当前连接；串口编号可能变化，不沿用未经核对的编号打开设备。

## 已验证的硬件与开发约束

详细证据见[实验 001](docs/experiments/001-rgb-led.md)。

- 板卡外观标识：屏蔽罩 `S3-N16R8`、背面 `ESP32-S3`；双 USB-C，分别标记 `COM` / `USB`。厂家、完整 PCB 型号/版本及正式模组型号尚未确认，不能据模板名称或照片外形断定官方板卡版本。
- 实测芯片 ESP32-S3，Flash 16 MB、物理 PSRAM 8 MB。Flash 使用 QIO，PSRAM 使用 OPI，Arduino memory type 为 `qio_opi`，分区为 `default_16MB.csv`。
- 本块板的 RGB 数据引脚为 **GPIO48**，依据原板脚本和用户实物验收；`rgb_gpio48` 是默认环境。`rgb_gpio38` 仅为其他板卡接线版本保留，不作为本板的默认尝试。
- 当前通过 COM 口的 USB 串口桥烧录与监视，UART0、115200 baud，`ARDUINO_USB_CDC_ON_BOOT=0`。改用原生 USB 时需同时核对端口与控制台配置。
- 已确认的设备路径为 `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00`；实验时映射至 `/dev/ttyACM1`。优先使用固定 by-id，并在连接变化后核对。
- 实验中的 `/dev/ttyACM0` 属于电脑摄像头，不能把它作为开发板串口；这是一条已确认的设备记录，不是对未来编号的永久假设。
- 串口临时 ACL 权限在重新插拔后可能失效；遇到拒绝访问时检查实际权限。需要管理员密码时让用户在本机终端输入，不索取密码，不扩大到所有串口的权限。
- 首个实验只连接 USB。新增模块前先确认其型号、供电、接线与所占 GPIO，再修改代码和连接硬件。
- `ESP.getPsramSize()` 是堆容量，略小于物理 8 MB；容量校验应区分物理容量与分配器开销，参照当前程序实现。
- ESP32-S3 的 LEDC 最大分辨率为 14 位；50Hz 舵机 PWM 不能沿用经典 ESP32 的 16/20 位配置。实验 005 使用 14 位，实测 `actual_hz=50`。Arduino-ESP32 2.0.17 中通道 0/1 共用定时器 0（`timer = (channel / 2) % 4`），同组通道必须使用相同频率和分辨率；实验 006 的两只舵机均为 50Hz/14 位，因此可以分别使用通道 0 和 1。
- 开发板排针上的 `5Vin` 是**供电输入**，只进不出；实测悬空约 2V，不能给 MAX98357A、舵机等外部负载供电。外部负载使用独立外部 5V 并与 ESP32 共地。

## 当前固件接口（实验 010）

- 当前 `src/main.cpp` 保留[串口命令实验 002](docs/experiments/002-serial-led.md)，上电 `off`，按 `red` / `green` / `blue` / `off` 改变并保持状态；`status` 和 `help` 不改变灯光。不再自动循环。启动标记为 `[experiment 010] INMP441 microphone input / Arduino`。
- `i2cscan` 使用 Wire、SDA GPIO8 / SCL GPIO9、100kHz，扫描 0x08–0x77；每次事务超时 25ms。扫描为同步命令，期间暂不处理新串口命令，不改变 RGB 状态；应答地址不能证明 OLED 型号或显示效果。详见[实验 003](docs/experiments/003-i2c-scan.md)。
- OLED 使用 U8g2 2.36.17；上电默认 SH1106 128×64 并直接进入眼睛画面。`oled_sh1106` / `oled_ssd1306` 仍可切换测试图，`oled_status` 查询当前驱动与画面类型（`screen=eyes|test`）。复位恢复 SH1106 与 normal 表情，不持久化选择；`off` 仅关闭 RGB。地址保持 0x3C，硬件 I²C 保持 100kHz。日志中的绘图调用和 ACK 不代表光学验收或型号鉴定。
- 实验 004 新增 `eyes <normal|happy|angry|sad|embarrassed|sympathy|comfort|melancholy|left|right>`、`eyes blink`、`eyes status`，以及仅用于软件调试的 `eyes dump`（输出 64×32 ASCII 帧缓冲，不发 I²C，约阻塞串口 0.2s）。表情引擎用 `millis()` 非阻塞状态机，自动眨眼 3–5s（悲伤/安慰/忧郁/尴尬更慢），闭眼保持 200ms；只在画面变化时重绘，并按 32 字节区域增量传输，每轮 `loop()` 最多传输一个区域，串口命令始终优先处理。详见[实验 004](docs/experiments/004-oled-eyes.md)。
- 实验 005 新增、实验 006 扩展为两只独立的 SG90：舵机 1 信号 GPIO4 / LEDC 通道 0，舵机 2 信号 GPIO5 / LEDC 通道 1，均 50Hz、ESP32-S3 最大 14 位分辨率；软件限位 60–120°，脉宽 600–2400µs（90° 为 1500µs），中位 90°，60°/s、20ms 步进。参数集中在 `src/servo_controller.h`（`makeConfig()`、`kDefaultConfig`、`kServo2Config`），两个 `servo::Controller` 实例各自保存角度、目标、运动与停止状态。开机只配置 LEDC 并写 0 占空比，不输出脉冲；显式命令才使能输出。`servo stop` 只停止对应舵机并关闭其脉冲，另一只不受影响；重新使能时从最后已知角度渐进到新目标。详见[实验 006](docs/experiments/006-dual-servo.md)。
- 舵机命令：旧 `servo center`、`servo <60-120>`、`servo status`、`servo stop` 保持实验 005 含义，仍指舵机 1，回复文本不变；`servo1 ...`、`servo2 ...` 分别控制对应通道；`servo both center`、`servo both stop` 同时作用于两只。状态行以 `SERVO`/`SERVO1`/`SERVO2` 开头并带 `channel=`。`servo both` 只接受 `center` 和 `stop`，执行前先检查两个实例都就绪。
- 实验 006 第二阶段新增 `src/motion_engine.*` 与 `src/mood_controller.*`。`motion neutral|wiggle|together|alternate|stop|status` 用 `millis()` 非阻塞状态机协调两只已有控制器，不复制 PWM；参数集中在 `motion_engine.h` 的 `Profile`。默认：neutral 90/90×1；wiggle 75–105°×6 周期（每周期 4 步、停留 350ms，共 24 步、约 20 秒，便于人工中途停止）；together 75–105°×5 周期（2 步/周期、350ms）；alternate 75–105°×5 周期（2 步/周期、300ms）。每个动作有限步数，完成后两只回中位 90° 并保持输出；`motion stop` 立即停止两只、关闭脉冲、清空序列；新动作覆盖旧动作；手动 `servo`/`servo1`/`servo2` 只丢弃序列（`cancel()` 不改输出），仅改变被命令的通道，另一只完成最后目标并保持；`servo both stop` 停止两只并清除序列。取消后不自动恢复或重新排队。
- `mood happy|sad|angry|normal|status|stop` 把一个表情和一个动作绑定为云端 AI 的软件入口：happy → happy + wiggle 80–100°×4（16 步）；sad → sad + wiggle 85–95°×3、停留 700ms（12 步）；angry → angry + alternate 82–98°×4、停留 150ms（8 步）；normal → normal + neutral。`start()` 先启动动作，失败时表情不变；`mood stop` 停止动作、关闭脉冲，**屏幕保留当前表情**并在回复中写 `screen=kept`；`eyes <表情>` 只清除 mood 标签而不停止动作；`motion ...` 清除 mood 标签但保留表情。所有 `eyes` 命令保留，不会隐式启动动作。
- SG90 供电必须使用外部 5V：红线接外部正极、棕线接外部负极、信号接对应 GPIO（1 → GPIO4、2 → GPIO5），ESP32 GND 与外部电源负极共地；禁止把外部 5V 接到 3V3 或任何 GPIO。首次测试不安装摇臂；开发、烧录和自动串口测试期间保持外部 5V 断开；实物运动必须由用户上电观察确认。2026-11-07 用户已先后确认舵机 1、舵机 2 单独测试和双舵机同时运动正常，`servo both center` 的实物效果也正常；运动中 `servo both stop` 因 60°/s 动作过快未能人工复现，只有软件检查证据（第二阶段约 20 秒的 `motion wiggle` 可用于补做）。双舵机供电余量、实际角度、方向标定、电流和带载情况未测量。第二阶段已于 2026-11-07 由用户接通外部 5V 逐项确认四个动作、运动中 `motion stop`、四个 mood 和 `mood stop` 正常；验收以用户观察为依据，未做定量测量。
- 实验 007：2026-11-08 用户确认纸板机械原型完成后，安装的两只舵机与 OLED 情绪联动运行正常；纸板尺寸、电流、供电稳定性、实际角度、噪声与带载未测量。详见[实验 007](docs/experiments/007-cardboard-prototype.md)。
- 实验 009 新增 `src/audio_engine.h/.cpp`：ESP-IDF legacy I²S TX 驱动（Arduino-ESP32 2.0.17 自带 `driver/i2s.h`），端口 0、BCLK GPIO7 / LRC GPIO15 / DIN GPIO6、无 MCLK；16kHz、16bit、双声道同一样本；4×240 帧 DMA；`tx_desc_auto_clear`。播放内容通过 `src/audio_source.*` 的 `Source` 接口拉取：`ToneSource`（880Hz、300ms、满量程 15%、首尾 5ms 淡入淡出）和 `FlashClipSource`（flash 内只读单声道 PCM，每块 240 帧、`memcpy_P`，不整段进 RAM）。`audio beep`、`audio hello`（内嵌中文语音）、`audio stop`（立即静音）、`audio status`（含 `source/clip/bytes/frames`）；上电只初始化不发声。`update()` 每轮最多写一块，`i2s_write` 超时为 0，DMA 满时下一轮再写；`chunkSent_` 是字节数，指针必须按字节偏移（`reinterpret_cast<const uint8_t*>(chunk_) + chunkSent_`），不能用 `int16_t*` 元素偏移。自然播放结束进入约 80ms 的 drain，等待 DMA 队列播完，不调用 `i2s_zero_dma_buffer()`；只有 `audio stop` 立即清零。初始化失败每次命令重试一次并返回 `ERR audio_not_ready`；无效 clip 元数据返回 `ERR audio_clip_invalid` 且不读取资源。详见[实验 009](docs/experiments/009-audio-output.md)。
- MAX98357A 供电与接线：VIN、SD → 外部 5V 正极（与两只 SG90 共用，标称 5V 5A，带载未测量）；GND → 外部 5V 负极并与 ESP32 GND 共地；DIN/BCLK/LRC → GPIO6/7/15、GAIN 悬空；扬声器只接 SPK+/SPK−，**不得把扬声器任一极接电路 GND**。开发板 `5Vin` 是输入引脚、不能对外供电（实测约 2V）；首次发声必须由用户发送 `audio beep` 触发；构建、烧录和自动测试期间舵机外部 5V 保持断开。出现爆音、功放异常发热、电压下跌或 ESP32 重启时立即断开外部 5V。2026-11-08 用户确认外部 5V 供电、SD 接高后首次发声正常。语音首次试听同样由用户触发 `audio hello`，保持固件音量 60%、不同时驱动两只舵机；自动回归期间外部 5V 保持断开。2026-11-08 用户接通外部 5V 后发送 `audio hello`，报告试听成功，第二阶段记为已验收（证据为用户观察，句尾、爆音与音量未逐项说明，未做定量测量）。
- 中文语音资源：`assets/audio/hello_zh.raw`（16kHz/16bit/单声道裸 PCM，78,828 字节、39,414 帧、2.463s）由 Edge TTS `zh-CN-XiaoxiaoNeural` 在本机生成，经 `platformio.ini` 的 `board_build.embed_files` 只读链接进 flash；`src/voice_clips.h` 用 `_binary_assets_audio_hello_zh_raw_start/_end` 取得真实长度，音量由 `kHelloVolumePercent` 控制。来源、转换命令与再分发限制见 `assets/audio/README.md`；Edge TTS 为非官方接口，音频仅用于本项目实验，不提交凭据、不调用付费 API、不擅自公开分发语音资源。
- 实验 010 第一阶段新增 `src/microphone_engine.h/.cpp`：INMP441 使用 `I2S_NUM_1` RX（主模式），SCK GPIO16 / WS GPIO17 / SD GPIO18，标准 I²S、16kHz、32bit 槽、`I2S_CHANNEL_FMT_ONLY_RIGHT` + `I2S_CHANNEL_MONO`，4×256 帧 DMA；读取 32bit 字后算术右移 8 位得到 24bit 有符号样本。上电只打印 `MIC_CONFIG`，不安装驱动、不采集；首次 `mic start` 才安装并启动 RX，`mic stop` 用 `i2s_stop()` 停止但保留驱动。`mic status` 报告 `state/ready/port/引脚/采样率/frames/blocks/reads/timeouts/zero_blocks/errors/last_error`；`mic level` 报告最近 32 块（约 0.5s）窗口的 `peak/rms/peak_pct/rms_pct/window_frames/window_blocks` 与 `signal=idle|no_data|zero|ok`。`update()` 每轮最多一次 `i2s_read(...,0)`，不阻塞。全零只说明数据为零，悬空数据线可能给出随机非零值，**不能**据此宣称采集实物成功。麦克风 VDD 必须接 3V3（不得接 5V），外部 5V 仅用于舵机与功放；烧录与回归期间保持外部 5V 断开。2026-11-08 实测：L/R 接 GND（用户已核对确认）时左声道全零，右声道有正常数据（约满量程 12%），说明该模块数据实际落在右声道槽；固件读取右声道并同步日志/`MIC_RE` 的 `channel=right`。用户讲话观察：安静 peak 1% → 说话 peak 6%，`mic stop` 后计数冻结，第一阶段记为已验收（证据为用户读数，未做定量测量）。详见[实验 010](docs/experiments/010-microphone.md)。
- 实验 010 第二阶段新增 `mic record` / `mic dump`：固定 3.000 秒、48,000 帧、96,000 字节的 16kHz/16bit/单声道录音，缓冲首次使用时优先 `heap_caps_malloc(..., MALLOC_CAP_SPIRAM)`、失败退回内部堆，只存在于 RAM（复位丢失）；`i2s_start` 后先丢弃 `kSettleFrames = 8000`（0.5s）启动瞬态再采集。录满后计算标准 CRC-32（0xEDB88320，与 Python `zlib.crc32` 一致）、`i2s_stop()`、状态转为 `record=ready`，打印 `MIC_RECORD_DONE frames=48000 bytes=96000 sample_rate_hz=16000 sample_format=s16le channels=1 crc32=...`。`mic dump` 仅在 `ready` 时启动，每行 48 字节（96 个十六进制字符、6 位字节偏移），共 2,000 行，由 `PCM_BEGIN ... crc32=` / `PCM_END lines=2000 ...` 包围；每轮 `loop()` 最多发一行，且受 `Serial.availableForWrite()` 限制，不阻塞 OLED、动作、Wi-Fi/HTTP。错误路径：未录音 dump → `ERR mic_no_recording`；录音中 `mic start|record|dump` → `ERR mic_recording`；dump 中 → `ERR mic_dump_busy`；录音中 `mic stop` 丢弃并回到 `record=idle`；完成后 `mic stop` 保留 `ready`；再次 `mic record` 覆盖上一段。`mic status` 带 `record/record_frames/record_bytes/record_crc`。录音与传输都不写 Flash、不发起网络请求。`scripts/capture_mic_wav.py` 在主机关闭监视器后核对设备身份、默认 5 秒倒计时、录音、dump，校验 2,000 行偏移/96,000 字节/CRC，30Hz 一阶高通去直流后峰值归一化到 70%（增益上限 64×），输出 `work/mic-*.wav`；可加 `--delay`、`--gain`、`--no-normalize`、`--out`。2026-11-08 用户试听最终 WAV（CRC `ac9af219`，3.000 秒）确认能听清说话内容，第二阶段记为已验收；有效语音仅约 0.6 秒，音频定量指标未测量。样本 WAV、诊断脚本与日志仅在本机 `work/`，被 Git 忽略。
- 实验 008 新增 `src/wifi_manager.*`、`src/web_server.*`、`src/web_ui.h`、`src/secrets.example.h`；`main.cpp` 每轮 `loop()` 先调用 `wifiManager.update()` 与 `webServer.update()`，再更新 OLED 与动作/情绪，全部非阻塞。新增串口命令 `wifi status`、`wifi reconnect`、`web status`（`WEB listening=... requests=... writes=... rejected=... rate_limited=... auth=...`）。详见[实验 008](docs/experiments/008-wifi-control.md)。
- Wi-Fi 仅 STA、家庭 2.4GHz；状态机为 disabled/connecting/connected/backoff，单次连接超时 20s，失败退避 2/5/10/20/30s，`setAutoReconnect(false)`、`setSleep(false)`、`persistent(false)`。SSID 为空时打印 `WIFI_DISABLED` 且不启动 Wi-Fi。日志含 `WIFI_CONNECTING`、`WIFI_CONNECTED`（IP、RSSI、channel）、`WIFI_TIMEOUT`、`WIFI_RETRY`、`WIFI_LOST`、`WIFI_RECONNECT`；密码与令牌绝不打印。
- 局域网 HTTP 使用基于 `WiFiServer` 的自实现最小服务器（内置 `WebServer` 会先读完整请求体，不满足上限要求）：80 端口、单连接、`Connection: close`、每轮最多读 64 字节；请求缓冲 1024 字节、请求体上限 128 字节、头/体超时 3s；响应用 `MSG_DONTWAIT` 分多轮发送，客户端停止读取不会卡住主循环，5s 未发完即关闭。接口仅 `GET /`、`GET /api/status`、`GET /favicon.ico`、`POST /api/mood`、`POST /api/motion`；名称走允许列表并复用现有 `MoodController`/`MotionEngine`，无串口透传，不能绕过 60–120° 限位。
- HTTP 写操作必须带 `X-Auth-Token` 头（16–64 个可打印 ASCII 字符）；缺失 401、错误 403、服务端未配置令牌 503。令牌不得进入 URL、串口日志或 HTTP 响应；限流为 10s 内 30 个请求、10 个写请求，超出 429。页面为 PROGMEM 单文件、无 CDN 或外网请求；令牌只保存在当前页面 JavaScript 内存，刷新后需重新输入；停止按钮只关闭软件 PWM，不是断电或机械制动。该方案仅为可信家庭局域网的明文 HTTP，禁止公网端口映射或不受控 AP。
- Wi-Fi 凭据：`src/secrets.example.h` 是模板；实际 `src/secrets.h` 必须被 `.gitignore` 忽略（当前仅本机存在，已用 `git check-ignore` 验证），令牌用 `openssl rand -hex 16` 生成；不得提交、打印或写入测试日志。SSID 为空时 Wi-Fi 为 disabled；`API_TOKEN` 也为空时网页写操作返回 503。
- 截至 2026-11-08：三环境构建通过；`scripts/test_serial_wifi.py` 在 Wi-Fi 凭据为空的固件上 910 项、在临时不可达 SSID 固件上 903 项（HTTP 跳过）检查通过，验证了 20s 超时、2s 退避、串口/OLED/动作不被阻塞且无复位。用户填入家庭 2.4GHz 凭据后，实测 `WIFI_CONNECTED ip=192.168.31.17 rssi=-40 channel=3`，含 HTTP 的完整回归 **1038 项通过**；该 IP 由 DHCP 分配，重启后可能变化，以 `wifi status` 为准。2026-11-08 用户报告浏览器/手机页面与远程控制测试通过，实验 008 记为已验收（证据为用户观察，未细分项目、未做定量测量）。
- 眼睛画面固定使用已验收的 SH1106 路径；从 SSD1306 测试图返回时重新初始化 SH1106。十种表情命令会重置当前表情的动画计时；`eyes blink` 在眨眼进行中返回 `started=0`，不排队。
- OLED 用户报告接线：VCC → 3V3、GND → GND、SDA → GPIO8、SCL → GPIO9；控制器和分辨率待确认。
- 接收使用固定 32 字符缓冲，每轮最多读取 64 个已到达字节；支持 CR、LF、CRLF、首尾空白和大小写。过长或非法的一整行必须丢弃，到换行后再恢复，不能执行截断前缀或后缀。
- `status` 表示最后命令状态，不代表光学测量。串口 ACK 与用户灯光验收分别记录。
- 监视器已配置 `monitor_echo=yes`、`monitor_eol=LF` 和 `send_on_enter`，在终端直接输入英文命令并按回车发送。
- 当前实机回归脚本为 `.venv/bin/python scripts/test_serial_wifi.py`；先关闭其他监视器，并保持舵机外部 5V 断开，除非用户明确同意让自动测试驱动舵机。脚本核对设备身份，会复位、回归实验 002/003/004 与全部舵机/动作/情绪命令、检查十种表情与 ASCII 帧缓冲、眨眼/自动眨眼、双通道状态、旧命令兼容、两只舵机的解析/限位/渐进运动/独立停止/`servo both`、动作序列与 mood 映射，并新增 Wi-Fi 启动状态、`wifi`/`web` 串口命令和令牌泄漏检查。设备已连接 Wi-Fi 且本地 `src/secrets.h` 中有有效 `API_TOKEN` 时，还覆盖页面、`/api/status`、401/403、允许列表、畸形/超大请求、GET/POST 方法限制、令牌误放 URL、限流、动作期间 HTTP 与 OLED 并行、`wifi reconnect` 后 HTTP 恢复；加 `--no-http` 可跳过。2026-11-08 Wi-Fi 凭据为空的固件 910 项、临时不可达 SSID 固件 903 项检查全部通过；随后在真实 Wi-Fi 下含 HTTP 的完整回归 1038 项通过（外部 5V 接通经用户授权）。实验 009 追加音频初始化/命令解析/空闲停止检查，并用 `--no-audio-sound` 跳开发声项，完整回归 1050 项通过；2026-11-08 首次发声确认后，完整回归（不加该参数，含播放/重启/停止状态机）1075 项通过；第二阶段加入 `audio hello` 与内嵌语音检查（资源长度、播放/重启/停止/自然结束、播放期间 OLED 与动作响应），完整回归 **1103 项通过**（外部 5V 断开）。实验 010 第一阶段追加麦克风启动/停止、Rx 驱动配置、统计窗口、`signal` 一致性、采集期间 OLED/动作/音频并发与错误计数检查，左声道版本完整回归 **1152 项**、右声道版本 **1151 项**通过（Wi-Fi 已连接含 HTTP，外部 5V 断开；计数差 1 来自 `servo_wait_idle` 轮询时机，不是失败项）；2026-11-08 用户讲话观察安静 peak 1% → 说话 peak 6%，第一阶段记为已验收。第二阶段追加录音状态与传输检查（`mic record` 分配与状态、录音中命令拒绝、`MIC_RECORD_DONE`、`mic stop` 保留、dump 头部/2,000 行偏移/96,000 字节/`zlib.crc32`/结束行、录音中止丢弃），完整回归 **1187 项通过**，烧录 920,368 字节并输出 `Hash of data verified`；2026-11-08 用户试听最终 WAV 确认能听清说话内容，第二阶段记为已验收。脚本会过滤 `WIFI_*`、`WEB_LISTEN`、`WEB_AUTH`、`WEB_REJECT` 等异步日志。`scripts/test_serial_motion.py` 对应实验 006 第二阶段固件，`scripts/test_serial_dual_servo.py` 对应第一阶段，`scripts/test_serial_servo.py` 对应实验 005，`scripts/test_serial_eyes.py` 对应实验 004，`scripts/test_serial_led.py` 对应实验 003，均保留为历史记录。
- `diagnostics` 仍不驱动 LED，颜色命令返回 `ERR led_disabled`；`rgb_gpio38` 仍仅为其他版本的备选。本板保持 `rgb_gpio48`。
- 实验 001–007 文档是历史验收记录，后续程序进入新实验时保留该记录；旧固件实现通过对应 Git 历史查阅。实验 008 的软件、联网与用户验收均已完成，细节见[实验 008](docs/experiments/008-wifi-control.md)；实验 009 第一阶段的构建、回归与首次发声验收已完成，第二阶段的 `audio hello` 软件、1103 项回归与用户听音验收也已完成，细节见[实验 009](docs/experiments/009-audio-output.md)；实验 010 第一阶段的构建、回归与用户讲话验收已完成，第二阶段的 3 秒录音、CRC 校验传输、`capture_mic_wav.py` WAV 导出、1187 项回归与用户试听验收也已完成，细节见[实验 010](docs/experiments/010-microphone.md)。

## 工程与验证方法

- VS Code + PlatformIO + Arduino；依赖版本以 `platformio.ini`、`requirements-dev.txt` 为准。无任务需要时不更换已验证的框架或库版本。
- 工具使用项目内 `.venv/bin/pio`，工具包在 `.pio-core/`；构建结果在 `.pio/`，原始日志及临时文件在 `work/`。
- 默认构建：`.venv/bin/pio run`。
- 检查所有现有环境：`.venv/bin/pio run -e diagnostics -e rgb_gpio48 -e rgb_gpio38`。
- 烧录：`.venv/bin/pio run -t upload`；串口监视：`.venv/bin/pio device monitor`，Ctrl-C 退出。
- 本机终端可能继承 ROS 的 `PYTHONPATH`；若导致 Python 包冲突，用 `env -u PYTHONPATH` 运行项目 CLI，不随意修改系统 ROS。
- 根据变更选择验证：固件改动需要适当构建；涉及设备行为时补充烧录、日志和必要的实物观察。纯文档修改检查事实、链接及 `git diff --check`，无需重复烧录。
- 灯光、声音、运动等无法由日志完整证明的现象，必须记录用户观察或实际测量来源；未取得时状态为“待实物验收”。

## 文档维护与完成条件

- **`AGENTS.md` 保存长期规则。** 协作方式、目录、命令、硬件约束或稳定决策发生变化时，同步更新此文件；日常执行日志放到进度与实验记录。
- **`docs/progress.md` 保存当前状态。** 每次产生项目变更、完成一个阶段、遇到/解除阻塞或得到新验收结果时，在结束工作前更新：日期、当前目标、已完成内容、验证证据、未决问题及一个明确的下一步。
- **`docs/experiments/NNN-topic.md` 保存实验过程。** 新实验按顺序编号；开始前写目标、硬件/接线和验收标准，结束时补齐具体配置、执行步骤、真实现象、结果、故障处理与学习要点。实验未开始时不要占用编号或编造结果。
- 进度状态统一使用“待规划 / 未开始 / 进行中 / 待实物验收 / 已验收 / 阻塞”，每个重要结论附实验文档、日志、提交或用户观察依据。编译通过不能直接记为已验收。
- 已完成的历史结果保留原日期；后续补充标记新日期。使用用户所在时区 Asia/Shanghai。
- 同步 README 的必要导航与当前功能说明，避免文档相互矛盾。
- 每次交接说明：做了什么、怎样验证、还缺什么、下一步从哪里继续。原始照片或日志未进入仓库时明确写出，不能声称已归档。
- 任务收尾时确认代码/配置与文档一致、验证状态准确、已授权的 Git 同步已完成；若受权限或硬件限制未完成，写明阻塞和用户需要执行的一步。

## Git 与同步规则

- Git 提交和推送遵从用户在当前工作范围内的授权；已经明确授权且范围未变时继续执行，不重复索取确认。若用户在新任务明确要求先确认，以最新要求为准，不能沿用旧任务许可跳过。没有授权时，先完成可审查的改动和验证，再询问是否提交或推送。
- 提交前检查差异和状态，只暂存本次任务相关文件；不要用全量暂存混入他人未完成内容。
- 实验变更与相关进度、记录尽量在同一提交中保存；规则变更同步纳入 `AGENTS.md`。不要在文档中填入尚未生成的自身提交号。
- push 前重新检查 `git status`、远程分支变化及待推送提交；按正常流程处理分歧，不自动强制推送、重写历史或丢弃工作区内容。
- 推送后核对本地提交与远程分支一致，并如实报告剩余未提交文件。
- `.venv/`、`.pio-core/`、`.pio/`、`work/` 和本机 VS Code 设置保持忽略。凭据、密钥与含敏感信息的日志不入库。
- 提交失败、推送失败或仅保存在本地时分别记录与说明，不把它们都称为“已同步”。
