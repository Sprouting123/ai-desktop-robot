# ai-desktop-robot

AI 桌宠机器人：ESP32-S3 通过 Wi-Fi 连接云端 AI，逐步实现表情、运动、语音和视觉。

## 项目管理入口

- [协作规则](AGENTS.md)：工作流程、硬件约束、当前串口接口与 Git 同步规则。
- [当前进度与交接](docs/progress.md)：里程碑、验证证据、未决问题和下一步。
- [实验 011：本地中文语音识别（ASR）](docs/experiments/011-asr.md)：Ubuntu 独立虚拟环境中 CPU 运行 FunASR Paraformer-large（Apache 2.0，模型缓存 848 MiB），新增 `scripts/asr_local.py`；最终录音识别为“一二三”，推理 0.10 s、RTF 0.034，2026-11-08 用户确认录音内容与识别一致；第二次录音验证新提示能捕获开头，但 3 秒窗口把“开始测试，这是一个AI测试”的结尾截掉，下一步需延长录音；未改固件、不调用付费 API、不上传录音。
- [实验 010：INMP441 麦克风采集与录音](docs/experiments/010-microphone.md)：I²S1 RX、`mic status/start/level/stop` 与近期峰值/RMS 统计；`mic record`/`mic dump` 固定 3 秒录音、CRC-32 校验传输与 WAV 导出；三环境构建、烧录与 1187 项回归通过；该模块数据实际只在右声道槽，固件读取右声道；2026-11-08 用户讲话观察与 WAV 试听均验收通过。
- [实验 009：MAX98357A I²S 音频](docs/experiments/009-audio-output.md)：I²S 提示音引擎、内嵌中文语音（`audio hello`）与非阻塞播放；第一阶段首次发声与第二阶段中文语音试听均已由用户于 2026-11-08 确认；第二阶段 1103 项回归通过。
- [实验 008：Wi-Fi 联网与局域网控制](docs/experiments/008-wifi-control.md)：非阻塞 STA 连接、令牌保护的 HTTP API、手机控制页；已联网并通过 1038 项回归，用户报告页面与远程控制验收通过。
- [实验 007：纸板机械原型](docs/experiments/007-cardboard-prototype.md)：已验收的整机机械安装记录与未测量边界。
- [实验 006：双 SG90 舵机协同控制](docs/experiments/006-dual-servo.md)：GPIO4/GPIO5 双通道、旧命令兼容（第一阶段已验收）；动作序列、表情联动、中途取消与手动接管（第二阶段已验收）。
- [实验 005：SG90 单舵机控制](docs/experiments/005-servo.md)：GPIO4、50Hz PWM、限位、渐进运动，以及 2026-11-07 已通过的实物验收记录与复验步骤。
- [实验 004：OLED 桌宠表情引擎](docs/experiments/004-oled-eyes.md)：十种表情、眨眼、动画状态机和验收步骤。
- [实验 003：I²C 扫描与 OLED 首次显示](docs/experiments/003-i2c-scan.md)：I²C 扫描与双驱动测试图、验证状态及边界。
- [实验 002：串口命令控制 RGB](docs/experiments/002-serial-led.md)：已验收的 RGB 命令基线、串口测试及 VS Code 操作步骤。
- [实验 001：RGB 自动循环](docs/experiments/001-rgb-led.md)：已归档的首次实验，记录保持不变。

## 当前功能：I²S 提示音与中文语音、INMP441 麦克风采集与 3 秒 WAV 录音、本地中文语音识别（ASR）、Wi-Fi 局域网控制、OLED 表情、双 SG90 动作序列与表情联动、串口控制 RGB、I²C 扫描与 OLED 测试

Ubuntu + VS Code / PlatformIO + Arduino；ESP32-S3、16 MB Flash、8 MB PSRAM、GPIO48 均已验证。默认环境 `rgb_gpio48`。

程序上电熄灯，并在 SH1106 128×64 OLED 上显示两只机器人眼睛。通过 UART0 / 115200 发送 `eyes normal`、`eyes happy`、`eyes angry`、`eyes sad`、`eyes embarrassed`、`eyes sympathy`、`eyes comfort`、`eyes melancholy`、`eyes left`、`eyes right` 可切换持续表情；`eyes blink` 触发一次眨眼后恢复原表情，`eyes status` 查询表情、动画阶段和计数。眼睛使用 `millis()` 非阻塞动画，约 3–5 秒自动眨眼一次，闭眼约 200ms，串口命令始终可用。`eyes dump` 输出 64×32 ASCII 帧缓冲，供无屏幕时做软件调试。

两只 SG90 分别通过 GPIO4（舵机 1，LEDC 通道 0）和 GPIO5（舵机 2，LEDC 通道 1）以 50Hz PWM 控制，各自独立保存角度、目标和停止状态。旧命令 `servo center`、`servo 60`–`servo 120`、`servo status`、`servo stop` 保持实验 005 的行为，仍指舵机 1；新增 `servo1 ...`、`servo2 ...` 显式选择通道，以及 `servo both center`、`servo both stop` 同时作用于两只。上电只配置 PWM 并写 0 占空比，不输出脉冲，首次显式命令才使能；两只都采用 60–120° 软件限位、600–2400µs 脉宽和 60°/s 渐进运动。舵机必须使用外部 5V 并与 ESP32 共地，不能把外部 5V 接到 3V3 或 GPIO；首次测试不装摇臂。2026-11-07 用户已确认两只舵机单独测试和双舵机同时运动正常；运动中 `servo both stop` 因动作过快未能人工复现，供电余量未测量。

在此之上新增非阻塞动作序列：`motion neutral`、`motion wiggle`（约 20 秒小幅交替，便于中途停止）、`motion together`、`motion alternate`、`motion stop`、`motion status`。每个动作都有固定步数和终点，结束后两只停在 90° 并保持输出；`motion stop` 立即停止两路脉冲，不自动恢复。`mood happy|sad|angry|normal` 把表情与动作绑定为统一入口：happy/sad 为不同节奏的轻微摆动，angry 为较快的反向交替，normal 回到中位；`mood stop` 只停止动作并关闭脉冲，屏幕保留当前表情，回复中明确写出 `screen=kept`。所有 `eyes` 命令仍可单独使用，不会隐式启动动作。第二阶段已通过构建、烧录、893 项串口/软件检查和 2 分钟连续运行；2026-11-07 用户接通外部 5V 逐项确认动作、运动中停止、四个 mood 与 `mood stop` 均正常，记为已验收（未做定量测量）。

实验 008 增加 Wi-Fi STA 与局域网控制。启动标记为 `[experiment 008] Wi-Fi LAN control / Arduino`；Wi-Fi 连接由非阻塞状态机管理，单次超时 20s，失败按 2/5/10/20/30s 退避，串口可随时用 `wifi status` 查询、`wifi reconnect` 重连。OLED、双舵机、动作与串口在联网、超时或掉线期间继续工作。SSID/密码/令牌放在本机 `src/secrets.h`（已被 `.gitignore` 忽略），模板为 `src/secrets.example.h`；不要把真实凭据提交到仓库。

设备联网后可在同一局域网访问 `http://<设备IP>/`：页面显示 Wi-Fi/IP/RSSI、表情、动作与两只舵机状态，提供开心/难过/生气/平静、摆动/同步/交替按钮和醒目的停止按钮。`GET /api/status` 返回状态 JSON，`POST /api/mood`、`POST /api/motion` 复用现有控制器；写操作必须带 `X-Auth-Token` 请求头，令牌只在页面内存中保存，不进入 URL 或浏览器持久存储。服务限制请求体（128 字节）、请求缓冲（1024 字节）和频率（10s 内 30 请求/10 写），未授权请求不会触发动作。该 HTTP 为明文，仅限可信家庭局域网，禁止公网端口映射；停止按钮只关闭软件 PWM，不是物理断电或机械制动。截至 2026-11-08：构建通过；Wi-Fi 凭据为空/不可达 SSID 的串口回归 910/903 项通过；填入家庭 2.4GHz 凭据后实测联网成功（`ip=192.168.31.17 rssi=-40`），含 HTTP 的完整回归 1038 项全部通过；用户报告浏览器/手机页面与远程控制测试通过，实验 008 记为已验收（证据为用户观察，未做定量测量），见[实验 008](docs/experiments/008-wifi-control.md)。

实验 009 增加独立的 I²S 音频输出：MAX98357A 功放 DIN → GPIO6、BCLK → GPIO7、LRC → GPIO15；VIN 与 SD → 外部 5V 正极（与两只舵机共用），GND 与 ESP32 共地，扬声器只接 SPK+/SPK−。开发板 `5Vin` 是输入引脚，不能给功放供电。`audio beep` 播放一次 880Hz、300ms、15% 幅度的提示音（首尾 5ms 淡入淡出），`audio hello` 播放内嵌的中文语音“你好，我是你的 AI 桌宠！”（Edge TTS `zh-CN-XiaoxiaoNeural`，16kHz/16bit/单声道，78,828 字节、2.463s，固件音量 60%），`audio stop` 立即停止并静音，`audio status` 查询源、资源长度、驱动与播放状态。语音由 `board_build.embed_files` 只读链接进 flash，播放时每次只取 240 帧，不整段复制到 RAM；`AudioEngine` 分块驱动 DMA，`i2s_write` 超时为零，不阻塞 OLED、Wi-Fi 与串口；上电只初始化，不自动发声。三环境构建、烧录与 1103 项完整回归通过（外部 5V 断开）；2026-11-08 用户确认第一阶段首次发声，并在接通外部 5V 后确认 `audio hello` 试听成功。音量、音质与供电余量未测量，见[实验 009](docs/experiments/009-audio-output.md) 与 `assets/audio/README.md`。功放与舵机共用外部 5V，不要同时满负荷运行。

实验 010 增加 INMP441 数字麦克风输入：VDD → 3V3、GND → GND、SCK → GPIO16、WS → GPIO17、SD → GPIO18、L/R → GND，使用 `I2S_NUM_1` RX、16kHz/32bit 槽、4×256 帧 DMA，与扬声器的 `I2S_NUM_0` 互不影响。该模块实测数据只出现在右声道槽，固件按右声道读取。上电只打印配置、不安装驱动也不采集；`mic start` 启动采集，`mic level` 输出最近约 0.5 秒窗口的 `peak`/`rms`、百分比、采样计数与 `signal=idle|no_data|zero|ok`，`mic stop` 停止并保留最后窗口，`mic status` 查询驱动与计数。`mic record` 在 RAM/PSRAM 中录固定 3.000 秒、16kHz/16bit/单声道音频（48,000 帧、96,000 字节），开始采集后先丢弃 0.5 秒启动瞬态；录满后计算 CRC-32 并进入 `record=ready`，`mic dump` 以每行 48 字节、共 2,000 行非阻塞传回，带偏移、长度与 CRC 校验。主机运行 `.venv/bin/python scripts/capture_mic_wav.py`（先关闭监视器）会核对设备、倒计时准备、在录音启动 0.6 秒后提示 `>>> SPEAK NOW`、录音、校验传输、30Hz 去直流并归一化，写出 `work/mic-YYYYmmdd-HHMMSS.wav`。采集、录音与传输都不保存到 Flash、不上传网络。2026-11-08 用户实测安静时 peak 1%、说话时 peak 6%，第一阶段验收通过；随后试听 3 秒 WAV 确认能听清说话内容，第二阶段验收通过；实验 011 中用户补充该样本只有“一二三”，前面的字未被录到，已据此修正提示时序；第二次录音验证开头已捕获，但 3 秒窗口在“开始测试，这是一个AI测试”中途结束，结尾仍被截断；灵敏度、噪声底、频响与失真未测量，见[实验 010](docs/experiments/010-microphone.md)。

实验 011 开始把录音转成中文文字：在 Ubuntu 主机上用独立虚拟环境 `work/asr-venv` 运行 FunASR Paraformer-large（模型 `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`，来源 ModelScope，Apache 2.0，模型缓存约 848 MiB），不修改 ESP32 固件、不调用付费 API、不上传录音。`scripts/asr_local.py <wav>` 先校验 16 kHz/16 bit/单声道，再在 CPU 上识别，输出识别文字、音频时长、模型加载/推理耗时、RTF、CPU 时间与峰值内存；模型、虚拟环境、录音与日志都放在被 Git 忽略的 `work/`。最终样本 `work/mic-20261108-181323.wav` 识别为“一二三”，缓存后加载 2.76 s、推理 0.10 s、RTF 0.034、峰值 RSS 2,261 MB；已知内容 TTS 对照“你好，我是你的 AI 桌宠！”识别为“你好我是你的ai捉宠”，仅一处同音字错误。2026-11-08 用户确认录音中实际能听到的就是“一二三”，识别正确；用户此前还说了几个字但未被录到。原因是旧提示从倒计时“3”开始说话，而录音在倒计时结束后才启动、固件还丢弃 0.5 秒，开头约 2.5 秒被截掉；`capture_mic_wav.py` 已改为录音启动 0.6 秒后提示 `>>> SPEAK NOW`。同日第二次录音（`mic-20261108-190250.wav`）验证开头已被捕获：用户说“开始测试，这是一个AI测试”，ASR 输出“开始测试这是”，未录到的“一个AI测试”被 3 秒窗口截掉；识别与已录内容一致，当前瓶颈是录音长度。无有效语音的录音会被模型“脑补”为文字，后续需把录音延长到 5–10 秒并加能量门限/VAD，见[实验 011](docs/experiments/011-asr.md)。

原有串口命令保留：`red`、`green`、`blue`、`off`、`status`、`help`、`i2cscan`、`oled_sh1106`、`oled_ssd1306`、`oled_status`。颜色持续保持，不自动切换；输入长度有上限，异常行不会执行。`i2cscan` 使用 GPIO8/9、100kHz 扫描 0x08–0x77；OLED 测试图与眼睛画面可互相切换，`oled_status` 显示当前驱动和画面类型。SH1106 已获用户实物显示确认，SSD1306 测试图由用户反馈异常，因此眼睛固定使用 SH1106；控制器型号仍未鉴定。实验 004 的十种表情与眨眼已于 2026-11-07 获用户实物验收，最新实测状态见实验 004。实验 007 的纸板机械原型于 2026-11-08 获用户确认：安装后两只舵机与 OLED 情绪联动正常；尺寸、电流和供电稳定性未测量。

在 VS Code 运行 **PlatformIO: Serial Monitor**，点击监视器终端后直接输入命令并按 Enter。已启用本地回显与回车发送，Ctrl-C 退出。表情逐项验收步骤见实验 004。

在项目根目录使用 `.venv/bin/pio run` 构建、`.venv/bin/pio run -t upload` 烧录、`.venv/bin/pio device monitor` 打开监视器。关闭监视器并保持舵机外部 5V 断开后，可运行 `.venv/bin/python scripts/test_serial_wifi.py` 重复当前固件的实机检查；脚本会复位板卡、回归旧命令、检查十种表情与双舵机通道，覆盖动作序列、中途停止、切换、手动接管和 mood 映射，以及音频初始化、命令解析、提示音/中文语音的播放、重启、停止与自然结束状态机，和麦克风的按需初始化、启动/停止、统计窗口、并发播放与错误计数，并检查 3 秒录音的状态机、录音中命令拒绝、`MIC_RECORD_DONE`、`mic dump` 的 2,000 行偏移/96,000 字节/CRC-32 与录音中止丢弃；在设备已联网且本地令牌可用时测试 HTTP API 与页面（`--no-http` 可跳过），最后关闭两只舵机输出、音频静音、RGB 熄灯、恢复 SH1106 眼睛画面。首次实际发声前使用 `--no-audio-sound` 跳过发声项；当前固件完整回归为 **1187 项**，外部 5V 保持断开。录音试听使用 `.venv/bin/python scripts/capture_mic_wav.py`，默认 5 秒准备倒计时，看到 `>>> SPEAK NOW` 后再开始说话，WAV 写到 `work/`；该目录与诊断日志被 Git 忽略，不上传。`scripts/test_serial_motion.py` 对应实验 006 第二阶段固件，`scripts/test_serial_dual_servo.py` 对应第一阶段，`scripts/test_serial_servo.py` 对应实验 005，`scripts/test_serial_eyes.py` 对应实验 004，均保留为历史记录。

代码分为 `src/main.cpp`（串口、RGB、I²C、屏幕、舵机、动作与网络命令）、`src/eyes_state.*`（纯时间状态机）、`src/eyes_render.*`（表情绘图）、`src/eyes_engine.*`（动画调度与增量刷新）、`src/servo_controller.*`（PWM、限位与渐进运动）、`src/motion_engine.*`（动作序列状态机）、`src/mood_controller.*`（表情与动作映射）、`src/wifi_manager.*`（非阻塞 STA 状态机）、`src/web_server.*`（受限 HTTP API）、`src/web_ui.h`（手机页面）、`src/audio_engine.*`（I²S/DMA 输出层）、`src/audio_source.*`（提示音与 flash PCM 源）、`src/voice_clips.h`（语音资源元数据），`src/microphone_engine.*`（INMP441 I²S RX、近期统计与 3 秒录音/串口导出），主机端录音脚本 `scripts/capture_mic_wav.py`、本地 ASR 脚本 `scripts/asr_local.py`，音频资源在 `assets/audio/`，配置在 `platformio.ini`，本地凭据在 `src/secrets.h`（不入库）。`diagnostics` 不驱动 LED；`rgb_gpio38` 仅保留作其他板卡版本的备选。当前由 USB 供电；用户报告 OLED VCC/GND/SDA/SCL 分别接 3V3/GND/GPIO8/GPIO9，舵机 1 信号接 GPIO4，红/棕线接外部 5V 正/负极并与 ESP32 共地；舵机 2 信号接 GPIO5。2026-11-07 用户已确认两只舵机单独测试与双舵机同时运动正常；运动中 `servo both stop` 未实物复现，实际角度与电流未测量；完整厂家与 PCB 版本仍未确认。
