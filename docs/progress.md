# 项目进度与交接

最后更新：2026-11-09（Asia/Shanghai）

## 当前状态

- **实验 001 已验收：** GPIO48 板载 RGB LED 红 → 绿 → 蓝循环，每色约 1 秒；构建、烧录校验、串口和用户实物观察均有记录。
- **管理机制已建立：** 规则、进度和交接入口已提交为 `93c9ce6`；继续随项目状态维护。
- **实验 002 已验收：** 六个串口命令已实现、构建与烧录通过、38 项实机串口检查通过；用户在 VS Code Monitor 中确认红绿蓝保持且 off 熄灯。实验 002 验收时设备启动为 off，不再自动循环。
- **实验 003 第一阶段：已验收（I²C 通信）。** 三环境构建、GPIO48 烧录及写入校验通过，52 项实机串口检查通过；连续两次只发现 0x3C，设备数 1、错误数 0。实验 003 阶段设备运行该版本；当前设备运行实验 009。OLED 型号未确认；第一阶段历史记录保留，第二阶段状态见下一条。见[实验 003](experiments/003-i2c-scan.md)。
- **实验 003 第二阶段：已验收（SH1106 首次显示）。** U8g2 2.36.17 已加入；默认 SH1106，支持串口切换 SSD1306。最终三环境构建和 GPIO48 烧录校验通过，65 项实机串口检查全部通过；用户已确认 SH1106 画面完整、没有问题；SSD1306 对比画面由用户反馈异常，显示未通过；保留 SH1106 为默认方案。
- **实验 004 已验收：** 十种持续表情、一次性眨眼、状态查询与 ASCII 帧缓冲调试已实现；默认开机进入 normal 眼睛画面。三环境构建通过，GPIO48 烧录及区域 hash 校验通过；`scripts/test_serial_eyes.py` 的 244 项串口/软件检查全部通过，十种表情帧缓冲哈希互不相同，自动眨眼在命令服务期间正常发生，内部堆与最大区域传输时间稳定。用户于 2026-11-07 按实验 004 第 9 节逐项观察，确认十种表情、手动/自动眨眼与显示均正常，见[实验 004](experiments/004-oled-eyes.md)。
- **实验 005 已验收：** SG90 单舵机控制已实现：GPIO4、50Hz LEDC、14 位分辨率、软件限位 60–120°、默认输出关闭、非阻塞渐进运动和 `servo stop` 放松策略。三环境构建、GPIO48 烧录校验和 `scripts/test_serial_servo.py` 的 348 项串口/软件检查通过，2 分钟连续运行无失败、无复位、堆稳定。2026-11-07 用户上电完成第 8 节观察，反馈 `servo center`/`75`/`105`/`120`/`60`、运动中 `servo stop` 与恢复、OLED 并行运行全部正常，见[实验 005](experiments/005-servo.md)。
- **实验 006 第一阶段：已验收。** 两个独立 `servo::Controller` 实例：舵机 1 GPIO4/通道 0，舵机 2 GPIO5/通道 1，均 50Hz、14 位、60–120°。保留旧 `servo ...` 命令（仍指舵机 1），新增 `servo1 ...`、`servo2 ...`、`servo both center|stop`。三环境构建、GPIO48 烧录校验和 `scripts/test_serial_dual_servo.py` 的 557 项串口/软件检查通过，2 分钟连续运行无失败、堆稳定。2026-11-07 用户先后确认舵机 1、舵机 2 单独测试和双舵机同时运动正常；运动中 `servo both stop` 因动作过快未能人工复现，仅有软件证据；供电余量与电流未测量。
- **实验 006 第二阶段：已验收。** 新增 `motion neutral|wiggle|together|alternate|stop|status` 非阻塞动作序列和 `mood happy|sad|angry|normal|status|stop` 表情联动；动作参数 75–105°，mood 80–100°、85–95°、82–98°，全部在 60–120° 限位内。新脚本 `scripts/test_serial_motion.py` 的 893 项检查通过（含第一阶段的独立停止回归），2 分钟连续运行 `failures=0`、无复位、堆稳定；GPIO48 已烧录实验 006-2 固件。2026-11-07 用户在外部 5V 上电条件下逐项确认四个动作、运动中 `motion stop`、四个 mood 及 `mood stop` 均正常；验收以用户观察为依据，未做定量测量，见[实验 006](experiments/006-dual-servo.md)。
- **实验 007 已验收：** 纸板机械原型完成后，用户于 2026-11-08 报告安装的两只舵机与 OLED 情绪联动运行正常。证据为用户观察，没有归档照片、视频或测量数据；结构尺寸、电流、供电稳定性、实际角度、噪声与带载均未测量。见[实验 007](experiments/007-cardboard-prototype.md)。
- **实验 008 已验收（2026-11-08 用户报告测试通过）：** 新增非阻塞 Wi-Fi STA、受限 HTTP API 与手机控制页。三环境构建通过；`scripts/test_serial_wifi.py` 在 Wi-Fi 凭据为空的固件上 910 项、临时不可达 SSID 固件上 903 项（HTTP 跳过）检查通过。2026-11-08 用户填入家庭 2.4GHz 凭据后，设备实测 `WIFI_CONNECTED ip=192.168.31.17 rssi=-40 channel=3`，`GET /` 返回 200（8980 字节），`GET /api/status` 返回合法 JSON；完整回归（含 HTTP 401/403/405/413/429 限流、令牌不进响应、`wifi reconnect` 后 HTTP 恢复）**1038 项全部通过**。测试期间外部 5V 接通并由用户授权驱动舵机；2026-11-08 用户报告浏览器/手机页面与远程控制测试通过，记为已验收，证据为用户观察（未细分项目、未做定量测量）。见[实验 008](experiments/008-wifi-control.md)。
- **实验 009 第一阶段已验收（2026-11-08 用户确认首次发声）：** 新增独立 `src/audio_engine.h/.cpp`，用 ESP-IDF legacy I²S TX 驱动（GPIO7 BCLK / GPIO15 LRC / GPIO6 DIN）驱动 MAX98357A；16kHz、16bit、立体声同行样本、4×240 帧 DMA、880Hz/300ms、15% 幅度、5ms 淡入淡出；`i2s_write(...,0)` 非阻塞，上电只初始化不发声。新增 `audio beep|stop|status`。排查发现开发板 `5Vin` 是输入引脚、不能给功放供电（实测约 2V）；改由与舵机共用的外部 5V 给 VIN/SD 供电并共地后，用户发送 `audio beep` 确认听到提示音。见[实验 009](experiments/009-audio-output.md)。
- **实验 009 第二阶段：已验收（2026-11-08 用户试听成功）。** 用 Edge TTS（免费、非官方 Microsoft 接口）在本机生成“你好，我是你的 AI 桌宠！”，声音 `zh-CN-XiaoxiaoNeural`、语速 −5%，转成 16kHz/16bit/单声道裸 PCM（78,828 字节、2.463s），经 `board_build.embed_files` 只读链接进 flash；新增 `Source`/`ToneSource`/`FlashClipSource` 与 `audio hello`，每次只 `memcpy_P` 读取 240 帧，不整段复制到 RAM；修正 `i2s_write` 部分写入时按 `int16_t*` 偏移的字节指针错误，并新增自然结束 drain（约 80ms）避免尾音被 DMA 清零截断。三环境构建通过（Flash 914,909 字节、静态 RAM 52,328 字节），烧录校验通过，完整回归 **1103 项通过**（外部 5V 断开）。未产生付费 API 调用；上电不自动播放。2026-11-08 用户接通外部 5V 后发送 `audio hello`，报告试听成功，记为已验收（证据为用户观察，未逐项说明句尾、爆音与音量，未做定量测量）。
- **实验 010 第一阶段：已验收（2026-11-08 用户讲话观察）。** 新增 `src/microphone_engine.h/.cpp`：INMP441 使用 `I2S_NUM_1` RX、SCK GPIO16 / WS GPIO17 / SD GPIO18、16kHz/32bit 槽、4×256 帧 DMA；上电不安装驱动、不采集，`mic start` 才初始化，`mic stop` 用 `i2s_stop()` 停止；`mic status`/`mic level` 输出近期 0.5s 窗口峰值、RMS、采样计数与 `signal=ok|zero|no_data|idle`。三环境构建通过（`rgb_gpio48` Flash 918,361 字节、静态 RAM 54,204 字节），烧录校验通过，含麦克风检查的完整回归左声道版本 **1152 项**、右声道版本 **1151 项**通过（Wi-Fi 已连接含 HTTP，外部 5V 断开；计数差 1 来自舵机轮询时机，非失败项）。实测左声道全零、右声道有正常数据；用户核对并确认接线正确后，固件改为 `I2S_CHANNEL_FMT_ONLY_RIGHT` 并重新烧录，回归中 `signal=ok`（peak≈1,342,808、rms≈1,010,716）。用户随后在串口监视器实测：安静时 peak 163,042（1%）、说话时 526,968–536,016（6%），`mic stop` 后帧计数冻结在 7,370,496；第一阶段记为已验收（证据为用户提供的读数，未做定量测量），见[实验 010](experiments/010-microphone.md)。
- **实验 010 第二阶段：已验收（2026-11-08 用户试听）。** 新增 `mic record`/`mic dump`：固定 3.000 秒（48,000 帧、96,000 字节）16kHz/16bit/单声道录音，缓冲优先 PSRAM、复位后丢失；每次开始采集先丢弃 8,000 帧启动瞬态；录满后计算 CRC-32（与 Python `zlib.crc32` 一致）、停止 RX 并进入 `record=ready`；`mic dump` 按每行 48 字节、共 2,000 行非阻塞输出，带偏移、长度与 CRC 校验。新增 `scripts/capture_mic_wav.py`：核对设备、倒计时、录音、传输、逐行/长度/CRC 校验，30Hz 去直流后做峰值归一化并写入 `work/mic-*.wav`。三环境构建通过（`rgb_gpio48` Flash 920,009 字节、静态 RAM 54,236 字节），烧录 920,368 字节且 `Hash of data verified`，完整回归 **1187 项通过**（Wi-Fi 含 HTTP，外部 5V 断开）。最终样本 `work/mic-20261108-181323.wav`（CRC `ac9af219`，原始峰值 6,844、去直流后 4,825/14.7%、增益 ×4.75）有效语音约 0.62–1.25 秒，用户试听后确认“能听清说话内容”，第二阶段记为已验收（证据为用户听感，未做定量测量；WAV、诊断脚本与日志在本机 `work/`，未入库）。见[实验 010](experiments/010-microphone.md) 第 7、8 节。
- **实验 011-1 本地 ASR：已验收（识别部分）。** 在独立 `work/asr-venv`（torch 2.14.1+cpu、FunASR 1.4.24、ModelScope 1.40.2）中用 CPU 运行 Paraformer-large（ModelScope `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`，Apache 2.0，模型目录 848 MiB）；新增 `scripts/asr_local.py`，本阶段不修改固件、不调用付费 API、不上传录音。`work/mic-20261108-181323.wav`（3.000 秒）识别为“一二三”，模型加载 2.76 s、推理 0.10 s、RTF 0.034、峰值 RSS 2,261 MB；已知内容 TTS 对照“你好，我是你的 AI 桌宠！”识别为“你好我是你的ai捉宠”（仅“桌”→“捉”）。2026-11-08 用户确认录音中实际能听到的就是“一二三”，识别正确；用户此前还说了几个字但未被录到，原因是旧提示从倒计时“3”开始说话、录音开始前约 2.5 秒被截掉。`capture_mic_wav.py` 已改为录音启动 0.6 秒后提示 `>>> SPEAK NOW`。同日第二次录音（`mic-20261108-190250.wav`，CRC `91756ef3`）验证提示生效：用户说“开始测试，这是一个AI测试”，语音从约 1.20 秒持续到 3.000 秒，开头已捕获，但 3 秒窗口在句子中间结束，ASR 只得到“开始测试这是”，结尾被截断。识别本身与已录内容一致，当前主要限制变成录音长度，见[实验 011](experiments/011-asr.md)。
- **实验 013 第一阶段：已验收（2026-11-08）。** 新增 `mic upload` 无线音频上传：ESP32 作为 HTTP 客户端，把已录好的 320,000 字节 16kHz/16bit/单声道 PCM 以二进制 POST 发送到 Ubuntu `192.168.31.29:8080/upload`；分块非阻塞写入、TCP connect 上限 1 秒、5 秒停滞/响应超时、最多 3 次重试，只有显式 `mic upload` 才发送，上电不录音、不上传。主机新增 `scripts/audio_receiver.py`，校验令牌（缺 401、错 403）、长度/格式（400/413）与 CRC-32（422）后才原子写入 `work/audio/mic-*.wav`，任何拒绝路径都不生成 WAV。令牌与主机地址只在被忽略的 `src/secrets.h` 和 `work/audio_upload_token`；未调用付费 API、未部署云服务器、未新增硬件。三环境构建通过（`rgb_gpio48` Flash 923,625 字节、静态 RAM 55,300 字节），烧录 923,984 字节且 `Hash of data verified`，完整回归 **1198 项通过**，接收端本地测试 **30/30 通过**。真实上传先后暴露两个缺陷：① Arduino-ESP32 2.0.17 的 `WiFiClient` 未实现 `availableForWrite()`（恒为 0），首次上传实际未发出数据、三次 `stall`，已改为 `MSG_DONTWAIT` 非阻塞 socket 发送，并给接收端增加请求头超时；② 成功响应解析要求 `bytes=` 与 `crc32=` 连续，而接收端响应中间还有 `frames=`，导致第二次上传已被接收端接受并保存 WAV（CRC `fdfbf19b` 一致）时固件仍误报 `bad_response`，已改为分别匹配各字段。第二次修复后重新烧录，用户于 20:34 重新录音并上传：固件上报 `MIC_UPLOAD_DONE ... crc32=ee814fb9 attempts=1`，接收端保存 320,000 字节 PCM、CRC 一致，峰值 28.12%，本地 ASR 输出 `开始记录这是一个AI测试的测试我正在说话`，用户试听确认内容正确、句尾清楚，第一阶段记为已验收（证据为用户听感与串口/接收端记录，未做定量测量）。见[实验 013](experiments/013-wifi-audio-upload.md)。
- **实验 013 第二阶段进行中（2026-11-09 硬件接触故障已定位）。** 前一晚 21:04 上传的录音为 320,000 字节全零，随后 OLED 表情在重插后消失；串口显示 `ERR oled_no_ack address=0x3C`、`i2cscan devices=0`。排查过程：模块 VCC/SDA/SCL 均约 3.3V（模块自带 I2C 上拉使空闲线为高，不能证明连通）；544 次连续扫描仅偶尔出现 0x28/0x46/0x59/0x63 等随机地址，属总线噪声；加入临时命令 `i2c_pins low` 将 GPIO8/9 同时拉低 10 分钟，实测模块 SCL 跟随到 0V、**SDA 仍为 3.3V**，而开发板 GPIO8 为 0V，确认 SDA 线板端未真正接触 GPIO8。把 SDA 杜邦母头直接顶住引脚时表情立即恢复，更换 SDA 线后彻底正常。重新烧录恢复正式固件（临时 `i2c_pins` 已移除），启动日志 `EYES_MODE driver=SH1106 expression=normal auto_blink=1`、`I2C_FOUND address=0x3C`，`eyes status` 有 96 次区域传输；三环境构建通过。麦克风重新接插后 `mic level` 恢复 `signal=ok`（说话 peak 18%、安静 2%、`zero_blocks=0`），说明 21:04 全零最可能是同类接触问题；`mic probe` 的 left/right 标号与正式右声道配置相反，属诊断命令标号问题，不影响正式采集。主机 IP 仍为 `192.168.31.29`，接收端未运行。
- **实验 013 第二阶段：已验收（2026-11-09 用户核对识别文本逐字一致）。** 接收端已加入自动 ASR（未提交）：WAV 写入 `work/audio/` 后排队调用 `work/asr-venv/bin/python scripts/asr_local.py --json`，结果写入 `work/asr/`；本次以 `--once` 启动（`asr=on queue=2`）。用户按绿灯提示在 10 秒窗口内说话：串口 `MIC_RECORD_DONE frames=160000 bytes=320000 ... crc32=0aa5589a`，`mic upload` 后 `MIC_UPLOAD_DONE bytes=320000 crc32=0aa5589a attempts=1`（一次成功，无重试）；接收端 `[receiver] ok remote=192.168.31.17 bytes=320000 crc32=0aa5589a file=mic-20261109-230828.wav`，保存 320,044 字节 WAV，PCM CRC 与固件一致；自动 ASR `status=success`，峰值 7.0%、高通 RMS 0.595%、有效语音 2.96 秒，识别为“这是一个AI测试你能听到吗我正在讲话”（推理 281 ms、RTF 0.028）。WAV 与 JSON 仅在 `work/audio/`、`work/asr/`，未入库。2026-11-09 用户确认实际所说就是该句，第二阶段记为已验收（证据为用户核对；未做定量音频测量）。接收端自动 ASR、`mic probe` 与相关测试仍未提交。
- **实验 012 10 秒录音：已验收（2026-11-08 用户整句试听与 ASR 对照）。** 把 `mic record` 的固定窗口从 3.000 秒延长到 **10.000 秒（160,000 帧、320,000 字节）**，PSRAM 缓冲与 0.5 秒启动瞬态丢弃不变；为避免 320,000 不能被 48 整除且整行超过默认 128 字节串口 TX FIFO，`mic dump` 改为每行 **50 字节（112 字节/行）、6,400 行**。三环境构建通过（`rgb_gpio48` Flash 920,009 字节、静态 RAM 54,236 字节），烧录 920,384 字节并输出 `Hash of data verified`，完整回归 **1188 项通过**（Wi-Fi 含 HTTP，外部 5V 断开）：`frames=160000 duration_ms=10000`、`MIC_RECORD_DONE ... bytes=320000 ... crc32=2e3614fa`、6,400 行偏移连续、320,000 字节、主机 `zlib.crc32` 与固件一致、`PCM_END lines=6400`。用户用 `capture_mic_wav.py` 完整说出“开始测试，这是一个AI测试”：WAV `work/mic-20261108-193259.wav` 为 10.000 秒，CRC `bf9753e4`，原始峰值 4,535、去直流后 3,437（10.5%）、增益 ×6.67；10 ms 窗能量显示语音约 1.19–4.54 秒（有效 2.27 秒），之后 5.46 秒静音，整句在窗口内说完。`asr_local.py` 识别为 `开始测试这是一个ai测试`，与用户实际所说逐字一致（仅无标点、`AI` 小写）；模型加载 2.69 s、推理 0.20 s、RTF 0.020、峰值 RSS 2,255.2 MB。用户确认句尾“AI测试”清楚，记为已验收（证据为用户听感与逐字对照，未做定量音频测量），见[实验 012](experiments/012-10s-recording.md) 5.5。
- **Git 同步：** 用户于 2026-11-07 确认实验 004 验收后授权提交与推送；实现与验收提交 [ba460c2](https://github.com/Sprouting123/ai-desktop-robot/commit/ba460c2b2763706f5aa557e41cc617b28469fd61) 已推送至 `origin/main`，远程分支 commit 与本地一致。实验 006 第一阶段的实现、测试脚本与文档提交 [4693430](https://github.com/Sprouting123/ai-desktop-robot/commit/469343005ba6b7cd3d704b25fd1d6d338ad52d4d) 已于 2026-11-07 推送并核对远程一致。实验 003 两阶段实现提交 [252d4b7](https://github.com/Sprouting123/ai-desktop-robot/commit/252d4b73d483bdb89321c18138efef540e6a40c8) 已推送并核对一致。此前实验 002 用户已授权提交与推送。实验 002 实现提交 [e702fc1](https://github.com/Sprouting123/ai-desktop-robot/commit/e702fc14f8708e335d48b849d8a28a41e2ebfc62) 已于 2026-11-07 推送到 `origin/main`，并通过远程查询核对一致。实验 009 第二阶段的实现、测试、文档与语音资源提交 [498d4f8](https://github.com/Sprouting123/ai-desktop-robot/commit/498d4f8af6cf453eaa65ea5e618ffe462f4aaca5) 于 2026-11-08 推送，`git ls-remote` 核对远程与本地一致。实验 010 第二阶段的固件、测试脚本、WAV 导出脚本与文档提交 [78b74fc](https://github.com/Sprouting123/ai-desktop-robot/commit/78b74fc0895c163dbcf0b61523a68394f9521ae0) 于 2026-11-08 经用户确认后推送，`git ls-remote` 核对远程与本地一致；样本 WAV 与 `work/` 诊断资料未入库。实验 011-1 的 ASR 脚本、录音提示修正与文档提交 [b0fb4d6](https://github.com/Sprouting123/ai-desktop-robot/commit/b0fb4d64fe41f917490307d06a05395427c10378) 于 2026-11-08 经用户确认后推送；第二次录音结果文档提交 [ea4b039](https://github.com/Sprouting123/ai-desktop-robot/commit/ea4b03955c272a8ad501ee2c8752cd57f7a23287) 随后推送；实验 012 的固件、脚本与文档提交 [874eca1](https://github.com/Sprouting123/ai-desktop-robot/commit/874eca1a01b8a29aac891c9253fe287542d0da95) 也于 2026-11-08 经用户确认后推送，`git ls-remote` 核对远程与本地一致；实验 013 第一阶段的固件、接收端脚本、测试与文档提交 [a026bda](https://github.com/Sprouting123/ai-desktop-robot/commit/a026bdab8a12205914ed644adbd6409b98e3caf4) 于 2026-11-08 经用户确认后推送，`git ls-remote` 核对远程与本地一致。实验 013 第二阶段的接收端自动 ASR、`mic probe`、测试与文档提交 [0cdd04a](https://github.com/Sprouting123/ai-desktop-robot/commit/0cdd04acd83868d92d728ac17d8518e419dd06d2) 于 2026-11-09 经用户确认后推送，`git ls-remote` 核对远程与本地一致。模型、虚拟环境与录音资料未入库。
- 项目固定路径：`/home/hy/ai-desktop-robot`。
- 仓库：[Sprouting123/ai-desktop-robot](https://github.com/Sprouting123/ai-desktop-robot)，开发分支 `main`。
- 工作规则：[AGENTS.md](../AGENTS.md)；当前实验：[013-wifi-audio-upload.md](experiments/013-wifi-audio-upload.md)；前置实验：[012-10s-recording.md](experiments/012-10s-recording.md)、[011-asr.md](experiments/011-asr.md)、[010-microphone.md](experiments/010-microphone.md)、[009-audio-output.md](experiments/009-audio-output.md)、[008-wifi-control.md](experiments/008-wifi-control.md)、[007-cardboard-prototype.md](experiments/007-cardboard-prototype.md)、[006-dual-servo.md](experiments/006-dual-servo.md)、[005-servo.md](experiments/005-servo.md)；更早：[004-oled-eyes.md](experiments/004-oled-eyes.md)；I²C/显示基线：[003-i2c-scan.md](experiments/003-i2c-scan.md)；RGB 基线：[002-serial-led.md](experiments/002-serial-led.md)；已归档实验：[001-rgb-led.md](experiments/001-rgb-led.md)。

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
| 实验 007：纸板机械原型 | 已验收 | 2026-11-08 用户报告安装后的两只舵机与 OLED 情绪联动正常；证据为用户观察，未归档照片/视频，结构尺寸、电流、供电稳定性、实际角度未测量，见[实验 007](experiments/007-cardboard-prototype.md) |
| 实验 008：Wi-Fi 与局域网控制 | 已验收 | 三环境构建通过；凭据为空 910 项、不可达 SSID 903 项通过；2026-11-08 真实联网成功（IP 192.168.31.17、RSSI -40）且含 HTTP 的完整回归 1038 项通过；用户报告浏览器/手机页面与远程控制测试通过，证据为用户观察，见[实验 008](experiments/008-wifi-control.md) |
| 实验 010：INMP441 麦克风采集与录音 | 已验收（两阶段） | 第一阶段：三环境构建、烧录与回归通过（左声道 1152 项、右声道 1151 项）；`I2S_NUM_1` RX、GPIO16/17/18、16kHz/32bit 槽、非阻塞 DMA、`mic status/start/level/stop`；实测数据只在右声道，固件改为右声道；用户讲话观察安静 peak 1% → 说话 peak 6%。第二阶段：`mic record`/`mic dump` 固定 3 秒录音、CRC-32 校验传输与 `capture_mic_wav.py` WAV 导出；三环境构建、烧录哈希校验、1187 项回归通过（外部 5V 断开）；2026-11-08 用户试听最终 WAV 确认能听清说话内容。未做定量音频测量，见[实验 010](experiments/010-microphone.md) |
| 实验 009：MAX98357A I²S 音频 | 已验收 | 第一阶段：2026-11-08 用户确认听到提示音，完整回归 1075 项通过。第二阶段：内嵌 Edge TTS 中文语音与 `audio hello`，三环境构建、烧录与 1103 项完整回归通过（外部 5V 断开），用户接通外部 5V 后报告试听成功；音质与供电余量未测量，见[实验 009](experiments/009-audio-output.md) |
| 实验 011：本地中文语音识别（ASR） | 已验收（识别部分；录音起始截断） | 独立 `work/asr-venv` 中 CPU 运行 FunASR Paraformer-large（ModelScope，Apache 2.0，模型目录 848 MiB）；新增 `scripts/asr_local.py`，不改固件、不调用付费 API、不上传录音。最终录音 `mic-20261108-181323.wav` 识别为“一二三”，模型加载 2.76 s、推理 0.10 s、RTF 0.034、峰值 RSS 2,261 MB；已知 TTS 对照有一处同音字错误（桌→捉）。2026-11-08 用户确认录音中实际能听到的就是“一二三”，识别正确；其前面还说了几个字但未被录到，属录音起始截断。见[实验 011](experiments/011-asr.md) |
| 实验 012：10 秒麦克风录音 | 已验收 | 固定录音 3 秒 → 10 秒（160,000 帧、320,000 字节），`mic dump` 每行 50 字节、6,400 行；三环境构建、烧录 920,384 字节且哈希校验、1188 项回归通过（录音 CRC `2e3614fa`、320,000 字节与主机 `zlib.crc32` 一致）。2026-11-08 用户完整说出“开始测试，这是一个AI测试”，10 秒 WAV（CRC `bf9753e4`）语音约 1.19–4.54 秒、后接 5.46 秒静音，句尾未被截断；ASR 输出“开始测试这是一个ai测试”，逐字一致，用户确认句尾清楚。未做定量音频测量，见[实验 012](experiments/012-10s-recording.md) |
| 实验 013：Wi-Fi 无线音频上传（第一阶段） | 已验收（2026-11-08） | 新增 `mic upload`/`mic upload status|cancel` 与 `upload::Client`：把已录 320,000 字节 PCM 以二进制 POST 发到 Ubuntu 8080，独立令牌 + 长度/格式 + CRC-32 校验，分块非阻塞、connect 上限 1 秒、最多 3 次重试；新增 `scripts/audio_receiver.py` 与 30 项本地测试；三环境构建、烧录 923,984 字节（哈希校验）与 1198 项回归通过。真实上传暴露并修复两个缺陷：2.0.17 `availableForWrite()` 恒为 0（改 `MSG_DONTWAIT`）与成功响应字段被要求连续（改分别匹配）。最终固件一次上传成功（CRC `ee814fb9`、`attempts=1`），WAV CRC 一致，ASR 输出 `开始记录这是一个AI测试的测试我正在说话`，用户试听确认句尾清楚，见[实验 013](experiments/013-wifi-audio-upload.md) |
| 实验 013：接收端自动 ASR（第二阶段） | 已验收（2026-11-09） | 接收端保存 WAV 后自动调用 `scripts/asr_local.py --json`；真实录音 CRC `0aa5589a`、上传 `attempts=1`、两端 CRC 一致，ASR 输出“这是一个AI测试你能听到吗我正在讲话”，用户核对逐字一致；WAV/JSON 在 `work/`，未入库，见[实验 013](experiments/013-wifi-audio-upload.md) 5.6 |

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
| Wi-Fi | STA、家庭 2.4GHz；SSID/密码/令牌位于本机 `src/secrets.h`（被 Git 忽略）；2026-11-08 实测连接成功：`ip=192.168.31.17 rssi=-40 channel=3`，电脑同网段（192.168.31.29）可 ping 通；IP 由 DHCP 分配，重启后可能变化 |
| 局域网控制 | HTTP 80 端口、明文，仅限可信家庭局域网；写操作需 `X-Auth-Token`；禁止公网端口映射或不受控 AP |
| 音频上传（实验 013） | ESP32 → Ubuntu `192.168.31.29:8080/upload`（本次 DHCP 地址，可能变化）；二进制 HTTP POST，独立 `AUDIO_UPLOAD_TOKEN`，与网页 `API_TOKEN` 分开；令牌在 `src/secrets.h` 与 `work/audio_upload_token`，均被 Git 忽略；仅限可信局域网，明文 HTTP |
| INMP441 麦克风（用户报告接线 + 2026-11-08 实测） | VDD → 3V3、GND → GND、SCK → GPIO16、WS → GPIO17、SD → GPIO18、L/R → GND；不得接 5V。用户已确认接线正确；该模块数据实际只在右声道槽，固件改为读取右声道 |
| MAX98357A 功放（用户报告 + 2026-11-08 实测） | VIN、SD → 外部 5V 正极（与两只 SG90 共用，标称 5V 5A）；GND → 外部 5V 负极并与 ESP32 共地；DIN → GPIO6、BCLK → GPIO7、LRC → GPIO15；GAIN 悬空；扬声器只接 SPK+/SPK−，不得接 GND。开发板 `5Vin` 为输入、不能对外供电（实测约 2V）；带载能力与并发电流未测量；模块型号未鉴定 |
| 本地 ASR 主机（2026-11-08） | Ubuntu、i5-12400F（6 核 12 线程）、15 GiB RAM、无 NVIDIA GPU；独立 `work/asr-venv`（torch 2.14.1+cpu、FunASR 1.4.24、ModelScope 1.40.2，约 1.7 GiB）；模型 `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`（Apache 2.0，约 848 MiB）缓存在 `work/models`；仅主机端，不参与固件 |

用户此前报告已备有 OLED、两个 SG90、INMP441、MAX98357A 与扬声器、5V 5A 电源及基础工具。OLED 已按用户报告接线，实验 003 已确认 0x3C 地址应答，SH1106 首次显示获用户确认，实际控制器型号仍待确认；第一只 SG90 接 GPIO4、第二只接 GPIO5，均由外部 5V 供电并与 ESP32 共地；实验 005 和实验 006 第一阶段的软件与 2026-11-07 实物验收均已通过；实验 009 已完成 MAX98357A 的接线、供电排查、首次发声与内嵌中文语音试听验收；INMP441 等其余模块尚未在本工程逐项核验或完成接线实验；机器人摄像头尚未选型，不能与电脑的 USB 摄像头混为一谈。

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

## 实验 007 的验证摘要

- 用户把已验收的 OLED 与两只 SG90 装入纸板机械结构，使用实验 006 第二阶段固件运行；接线与引脚没有改动。
- 2026-11-08 用户报告：纸板机械原型已经完成，安装后的两只舵机与 OLED 情绪联动运行正常。实验 007 记为已验收。
- 没有保存照片、视频、串口日志或测量数据；纸板尺寸、重量、摇臂长度、电流、电压跌落、发热、实际角度、噪声和带载均未测量，不能据本次验收推断。

## 实验 008 的验证摘要

- 新增 `src/wifi_manager.*`（非阻塞 STA 状态机）、`src/web_server.*`（基于 `WiFiServer` 的受限 HTTP/1.1 服务器）、`src/web_ui.h`（PROGMEM 单页）、`src/secrets.example.h`；`main.cpp` 增加 `wifi status|reconnect`、`web status`，每轮 `loop()` 先更新 Wi-Fi/HTTP 再更新 OLED 与动作。
- Wi-Fi：仅 STA、2.4GHz；单次超时 20s；退避 2/5/10/20/30s；`setAutoReconnect(false)`、`setSleep(false)`、`persistent(false)`；SSID 为空进入 `disabled`。密码与令牌不打印。
- HTTP：80 端口、单连接、`Connection: close`；请求缓冲 1024 字节、请求体 128 字节、超时 3s；响应用 `MSG_DONTWAIT` 分多轮发送（5s 未发完即关闭），客户端停止读取不阻塞主循环；`GET /`、`GET /api/status`、`GET /favicon.ico`、`POST /api/mood`、`POST /api/motion`；写操作须带 `X-Auth-Token`（401/403/503），限流 30 请求/10 写每 10s（429）；名称走允许列表并复用现有控制器，无串口透传、不绕过限位。
- 页面：无 CDN/外网请求；令牌只存于当前页面 JavaScript 内存；停止按钮仅关闭软件 PWM，不是断电或机械制动。明文 HTTP 仅限可信局域网。
- `.gitignore` 已加入 `src/secrets.h`，`git check-ignore` 验证通过；实际凭据只在本机。
- 构建：`diagnostics`、`rgb_gpio48`、`rgb_gpio38` 全部 SUCCESS；`rgb_gpio48` Flash 812681 字节、静态 RAM 50672 字节；填入真实凭据后 Flash 812717 字节，烧录写入 813088 字节。
- Wi-Fi 凭据为空的固件：`scripts/test_serial_wifi.py` 910 项检查通过；HTTP 按预期跳过，启动为 `WIFI_DISABLED`、`WEB listening=0`。
- 临时不可达 SSID 固件：50 秒捕获显示 20.9s `WIFI_TIMEOUT`、`WIFI_RETRY delay_ms=2000`、22.9s 第二次尝试；连接期间 `motion` 与串口正常应答，`wifi reconnect` 立即返回并开始第三次尝试，`WEB listening=0`。该固件完整回归 903 项通过，HTTP 跳过，无复位或卡死；测试后已恢复本地凭据并重新烧录。最终构建（仅 HTTP 响应发送改为非阻塞）再以 910 项串口回归确认。
- 真实 Wi-Fi（2026-11-08）：用户填好 `src/secrets.h` 后重新构建烧录（813088 字节），串口依次打印 `WIFI_CONNECTING`、`WIFI_CONNECTED ip=192.168.31.17 rssi=-40 channel=3`、`WEB_LISTEN state=listening port=80`；电脑（有线 192.168.31.29）ping 通、`curl` 取得页面 200（8980 字节）与合法 `/api/status` JSON。测试期间舵机外部 5V 保持接通，用户明确授权自动测试驱动舵机。
- 含 HTTP 的完整回归：`scripts/test_serial_wifi.py` **1038 项全部通过**（结束时设备 `uptime_ms=187245`，约 3 分钟），覆盖页面/CSP/无外网资源、状态 JSON 字段、缺失/错误令牌 401/403 且不改变状态、合法 mood/motion 复用控制器、非法名称与畸形/超大请求、GET/POST 方法限制、令牌误放 URL、动作期间轮询与 OLED 并行、写限流 429 与窗口恢复、`wifi reconnect` 后 HTTP 恢复、固件计数器、所有响应不含令牌；结束时两路脉宽为 0、RGB 熄灭、屏幕回到眼睛画面。
- Ubuntu 浏览器与手机的实际页面操作、远程情绪/动作实物效果仍需用户观察确认；断路由器后的自动重连、长时间联网稳定性未验证。
- 原始捕获与备份在 `work/`（`008-wifi-fail-capture.py`、`secrets.h.backup-008`），被 Git 忽略，未归档入库。

## 实验 009 的验证摘要

- 新增 `src/audio_engine.h/.cpp`：ESP-IDF legacy I²S TX 驱动，端口 0、主模式、BCLK GPIO7 / LRC GPIO15 / DIN GPIO6、无 MCLK；16kHz、16bit、双声道同一样本；4×240 帧 DMA（约 60ms）；`tx_desc_auto_clear`；不启用 APLL。
- 提示音：880Hz、300ms、满量程 15%（约 −16.5dBFS）、首尾 5ms 线性淡入淡出；`beep()` 可播放中重启，`stop()` 立即清零 DMA，`update()` 每轮最多写一块且 `i2s_write` 超时为 0。
- 命令：`audio beep|stop|status`；上电只安装驱动、`AUDIO_INIT ready=1`、`state=idle plays=0`，不发声；非法参数 `ERR audio_usage; use help`；初始化失败重试一次后返回 `ERR audio_not_ready`。
- 三环境构建：`diagnostics`、`rgb_gpio48`、`rgb_gpio38` 全部 SUCCESS；`rgb_gpio48` Flash 833789 字节（12.7%）、静态 RAM 51736 字节（15.8%）。
- 烧录后 `scripts/test_serial_wifi.py --no-audio-sound`：**1050 项检查全部通过**（约 3 分钟），原有 1038 项 Wi-Fi/HTTP/OLED/双舵机/动作/情绪回归继续通过，新增音频初始化、命令解析、空闲停止与“拒绝命令不启动播放”检查；结束状态为音频静音、两路脉宽 0、RGB 熄灭、眼睛画面。
- 首次发声后再次运行完整回归（不加 `--no-audio-sound`，外部 5V 按规则断开、功放未供电）：**1075 项检查全部通过**，新增播放状态机检查——`state=playing`、播放中重复触发 `restarted=1`、播放中 `audio stop`、播放期间动作与串口不被阻塞、播放结束回到 `idle`、上电不自动发声。
- 首次发声排查：功放 VIN 原接开发板 `5Vin`，`audio beep` 返回成功且 `plays` 增加、`errors=0`，但完全无声；万用表测得 `5Vin` 对 GND 约 2V，确认 `5Vin` 是供电输入、不能对外供电。扬声器用 1.5V 电池瞬碰可听到“咔”声，排除扬声器故障。
- 改为外部 5V 供电（与两只 SG90 共用）：功放 VIN、SD 接外部 5V 正极，功放 GND 与 ESP32 GND 共地，扬声器仍只接 SPK+/SPK−。2026-11-08 用户发送 `audio beep`，确认听到一次短促提示音，实验 009 记为已验收。
- 未测量项：音量、失真、爆音、功放发热、外部 5V 在功放与舵机同时工作时的电压跌落；播放中 `audio stop` 因提示音仅 300ms 未能人工复测，由回归覆盖。

第二阶段（中文语音）补充：

- TTS 选型：Edge TTS 7.3.1（免费、无账号密钥、非官方 Microsoft 接口）；未使用任何付费 API。对比 `zh-CN-XiaoxiaoNeural`、`zh-CN-XiaoyiNeural`、`zh-CN-YunxiNeural` 后选 Xiaoxiao（Warm）。
- 资源：`assets/audio/hello_zh.raw`，16kHz/16bit/单声道裸 PCM，78,828 字节、39,414 帧、2.463s，峰值约 −3.5dBFS；用 ffmpeg 去首尾静音并加 10ms 淡入淡出，`ffprobe` 与逐样本统计确认是真实语音。来源、声音 ID 与许可说明见 `assets/audio/README.md`（文件不入库前需用户确认分发范围）。
- 存储：`platformio.ini` 的 `board_build.embed_files` 把资源链接进 flash；`_binary_assets_audio_hello_zh_raw_start/_end` 之差即长度，链接核对为 0x133EC = 78,828 字节。`FlashClipSource` 每个块只拷贝 240 帧（480 字节），不整段进 RAM。
- 输出层修正：`chunkSent_` 是字节数，原 `chunk_ + chunkSent_` 在部分写入时会按 2 倍偏移跳过样本，现改为 `reinterpret_cast<const uint8_t*>(chunk_) + chunkSent_`；自然结束改为等待 DMA 队列约 80ms 播完再回 `idle`，不再清零截尾，`audio stop` 仍立即清零。
- 命令：新增 `audio hello`（播放中重启 `restarted=1`），`audio status` 增加 `source/clip/bytes/frames` 字段；`audio beep|stop` 含义不变。
- 验证：三环境构建通过，`rgb_gpio48` Flash 914,909 字节（14.0%）、静态 RAM 52,328 字节（16.0%），烧录与哈希校验通过；启动新增 `AUDIO_CLIP name=hello_zh bytes=78828 frames=39414 sample_rate_hz=16000 volume_pct=60`；完整回归 **1103 项通过**（Wi-Fi 已连接含 HTTP，外部 5V 断开），覆盖 hello 启动/重启/停止/自然播完、播放期间 OLED 与动作响应、`errors=0` 与堆检查。回归不能证明可听声音。
- 听音：2026-11-08 用户接通外部 5V（未同时驱动舵机）后发送 `audio hello`，报告**试听成功**，实验 009 第二阶段记为已验收（证据为用户观察）。句尾完整性、爆音与音量未逐项说明，声压、电流与供电余量未测量；`i2s_write` 部分写入路径未被脚本强制触发，属代码级修正。

## 实验 010 的验证摘要

第一阶段（采集）：

- 新增 `src/microphone_engine.*`：`I2S_NUM_1` RX、GPIO16/17/18、16kHz/32bit 槽、4×256 帧 DMA、`i2s_read(...,0)` 非阻塞；按需安装驱动，`mic start/stop/level/status`。
- 实测该 INMP441 数据只在右声道槽，固件改为 `I2S_CHANNEL_FMT_ONLY_RIGHT` + `I2S_CHANNEL_MONO`；左声道版本回归 1152 项、右声道版本 1151 项通过。
- 2026-11-08 用户讲话观察：安静 peak 1%（163,042）→ 说话 peak 6%（526,968–536,016），`mic stop` 后 `frames` 冻结在 7,370,496；证据为用户读数，未做定量测量。

第二阶段（3 秒录音与 WAV）：

- 固件：`mic record` 首次分配 96,000 字节（优先 PSRAM，失败退回内部堆），丢弃 8,000 帧（0.5 秒）启动瞬态后录 48,000 帧；完成后 CRC-32、`i2s_stop()`、`record=ready`。`mic dump` 每行 48 字节、2,000 行，带偏移/长度/CRC，`Serial.availableForWrite()` 不足时下一轮再发。录音中 `mic start/record/dump` 返回 `ERR mic_recording`，dump 中返回 `ERR mic_dump_busy`，录音中 `mic stop` 丢弃本次录音。
- 主机：`scripts/capture_mic_wav.py` 核对设备身份，默认 5 秒倒计时（只用于准备），发送 `mic record` 并等待 0.6 秒后提示 `>>> SPEAK NOW`，等待 `MIC_RECORD_DONE` 后 dump，校验 2,000 行偏移、96,000 字节与 `zlib.crc32`，30Hz 一阶高通去直流，峰值归一化到 70% 满量程（增益上限 64×），写 16kHz/16bit/单声道 WAV 到 `work/`。2026-11-08 实验 011 发现旧提示“数到 3 开始说话”会截掉开头约 2.5 秒，故改为当前提示；第二次录音验证开头已捕获，但 3 秒窗口把整句结尾截断。
- 诊断：复位后立即录音的前约 0.4–0.5 秒为满幅衰减伪影，预启动 2 秒后消失，因此加入 settle 丢弃；原始波形有数个百分点满量程的直流偏置与慢漂移，主机 30Hz 高通去除；1kHz 声音测试在 1000Hz 处出现幅度约 816 的峰值（相邻频点 2–5）；`mic level` 安静峰值 4–5%，5–10cm 大声说话依次出现 53%/24%/14%/12%。此前“只有噪声”的样本经实时电平对比，判断与说话太轻、太远或起录太晚有关。
- 构建与烧录：`diagnostics` Flash 916,641 字节 / RAM 54,188 字节；`rgb_gpio48` 与 `rgb_gpio38` Flash 920,009 字节 / RAM 54,236 字节。烧录 920,368 字节，`Hash of data verified`。
- 回归：外部 5V 断开、Wi-Fi 已连接，`scripts/test_serial_wifi.py` **1187 项通过**（含 HTTP、录音状态、传输与 CRC 检查），无复位。日志在本机 `work/regression-010-phase2d.log`，被 Git 忽略。
- 试听：`work/mic-20261108-181323.wav`，3.000 秒，固件 CRC `ac9af219`，原始峰值 6,844，去直流后 4,825（14.7%），增益 ×4.75；有效语音约 0.62–1.25 秒。用户确认“能听清说话内容”，第二阶段记为已验收（证据为用户听感；灵敏度、噪声底、频响、失真与声压级未测量；WAV 与诊断资料未入库）。

## 实验 011 的验证摘要

- 方案：FunASR Paraformer-large，模型 ID `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`，来源 ModelScope，Apache 2.0；下载前说明约 889 MB，实际模型目录 848 MiB（`model.pt` 880,502,012 字节、`seg_dict` 8,287,834 字节），10 个文件约 30 秒下载完成。
- 环境：独立 `work/asr-venv`（约 1.7 GiB），torch 2.14.1+cpu、torchaudio 2.11.1+cpu、funasr 1.4.24、modelscope 1.40.2、soundfile 0.14.0；`MODELSCOPE_CACHE=work/models`；运行 `env -u PYTHONPATH`，未改动 PlatformIO `.venv`。
- 脚本：新增 `scripts/asr_local.py`，校验 PCM/16 kHz/16 bit/单声道，保持原始输入；输出模型、时长、加载/推理耗时、RTF、CPU 时间与平均核数、峰值 RSS、识别文本与错误原因；失败退出码 1。
- 识别：`work/mic-20261108-181323.wav`（3.000 秒，10 ms 窗有效语音约 0.46 秒）→ **“一二三”**；缓存后模型加载 2.65–2.78 秒，推理 0.10–0.11 秒，RTF 0.032–0.035，CPU user 0.37–0.40 秒（约 3.8–3.9 核），峰值 RSS 2,254.5–2,270.4 MB；首次运行加载 33.00 秒（含下载）。
- 对照：其余 5 个无有效语音的录音输出 `啊`、`right is`、`the the the知嗯` 等无意义文本，说明模型会在静音/弱语音上“脑补”；已知内容 TTS“你好，我是你的 AI 桌宠！”识别为“你好我是你的ai捉宠”，仅“桌”误为同音“捉”，未输出标点。
- 验收：2026-11-08 用户确认录音中实际能听到的就是“一二三”，ASR 识别正确；用户此前还说了几个字但没有被录到。原因是旧提示让用户从倒计时“3”开始说话，而 `mic record` 在倒计时结束后才启动、固件还丢弃 0.5 秒，开头约 2.5 秒落在录音窗口外。该截断属于录音流程问题，不是 ASR 漏识。
- 修正与复测：`scripts/capture_mic_wav.py` 改为主机在 `mic record` 启动 0.6 秒后提示 `>>> SPEAK NOW`。同日第二次录音 `mic-20261108-190250.wav`（3.000 秒，CRC `91756ef3`，原始峰值 7,759，去直流 5,566/17.0%，增益 ×4.12）验证开头已捕获：用户说“开始测试，这是一个AI测试”，语音从约 1.20 秒持续到 3.000 秒，ASR 输出“开始测试这是”；识别与已录内容一致，未录到的“一个AI测试”落在 3 秒窗口之外。模型加载 2.71 s、推理 0.10 s、RTF 0.033、峰值 RSS 2,270.1 MB。本次只改主机提示时序，未改固件；结尾截断需靠更长录音解决。
- 范围：本阶段未修改 ESP32 固件，未调用付费 API，未上传录音，模型/venv/WAV/日志均在 `work/` 并被 Git 忽略。验收只覆盖“对已录制音频的识别”，录音完整性与整句识别待重录。

## 实验 012 的验证摘要

- 固件：`kRecordFrames` 48,000 → 160,000（10.000 秒），`kDumpBytesPerLine` 48 → 50；`mic record` 回复 `OK mic=recording frames=160000 duration_ms=10000`，`MIC_RECORD_DONE frames=160000 bytes=320000 ... crc32=...`；缓冲仍优先 PSRAM（实测 `MIC_RECORD_ALLOC bytes=320000 psram=1`），启动瞬态仍丢弃 8,000 帧。
- 传输：`PCM_BEGIN ... line_bytes=50`，6,400 行、每行 100 个十六进制字符，偏移 0、50、…、319,950，payload 320,000 字节；`PCM_END lines=6400 bytes=320000 crc32=...`。首次尝试 64 字节/行（140 字节/行）时，默认 128 字节串口 TX FIFO 导致 `Serial.availableForWrite()` 永远不足，dump 停在 `PCM_BEGIN` 之后；改为 50 字节/行（112 字节/行）后恢复。
- 主机等待修正：`read_until`/`collect_until` 现在等标记后的换行再返回，避免 `PCM_END lines=64` 这类截断行；`capture_mic_wav.py` 校验 `line_bytes=50`。
- 构建与烧录：`diagnostics` Flash 916,657 字节 / RAM 54,188 字节；`rgb_gpio48`/`rgb_gpio38` Flash 920,009 字节 / RAM 54,236 字节。烧录 920,384 字节，`Hash of data verified`。
- 回归：外部 5V 断开、Wi-Fi 已连接，`scripts/test_serial_wifi.py` **1188 项通过**（比实验 010 多 1 项，新增 `line_bytes=50` 检查）；录音 CRC `2e3614fa`，6,400 行偏移与 320,000 字节校验一致，无复位。日志在本机 `work/test_serial_012.log`，被 Git 忽略。
- 主机链路：`scripts/capture_mic_wav.py` 用环境声（未说话）跑通 10.000 秒 WAV，固件 CRC `157c65e7`，原始峰值 3,509、去直流 670（2.0%）、增益 ×34.25；文件 `work/mic-20261108-192708.wav` 仅在本机。
- 整句验收（2026-11-08）：用户完整说出“开始测试，这是一个AI测试”，WAV `work/mic-20261108-193259.wav` 为 10.000 秒（CRC `bf9753e4`），原始峰值 4,535、去直流后 3,437（10.5%）、增益 ×6.67；10 ms 窗能量显示语音约 1.19–4.54 秒（有效 2.27 秒），其后 5.46 秒静音。`asr_local.py` 输出“开始测试这是一个ai测试”，与实际内容逐字一致（仅无标点、`AI` 小写）；模型加载 2.69 s、推理 0.20 s、RTF 0.020、峰值 RSS 2,255.2 MB。用户试听确认句尾“AI测试”清楚，实验 012 记为已验收（证据为用户听感与逐字对照，未做定量音频测量）。

## 实验 013 的验证摘要

- 固件：新增 `src/audio_uploader.h/.cpp`，`mic upload` 只在 `record=ready` 时启动；`mic upload status`、`mic upload cancel`；上传中拒绝 `mic start/record/dump/upload`，`mic stop` 取消上传但保留录音。`microphone_engine.h` 增加 `recordedData()`/`sampleRate()` 只读接口，复用 320,000 字节录音缓冲与固件 CRC-32。
- 传输：HTTP/1.1 POST，头含 `X-Auth-Token`、`Content-Length: 320000`、`X-Audio-Format/Sample-Rate/Channels/Frames/Crc32`；每轮最多发送 1024 字节，直接对 socket 用 `MSG_DONTWAIT` 非阻塞发送；connect 超时 1000 ms，停滞与响应超时 5000 ms，最多 3 次尝试，重试从头发送；成功须同时包含 HTTP 200、`OK `、`bytes=` 与 `crc32=`，各字段分别匹配、不要求相邻。
- 主机：新增 `scripts/audio_receiver.py`（标准库、8080 端口、`work/audio_upload_token`、`hmac.compare_digest`），校验令牌、长度、格式头与 CRC 后写临时文件并 `os.replace` 为 `work/audio/mic-YYYYmmdd-HHMMSS.wav`；拒绝路径不产生 WAV；请求头与请求体都有 10 秒超时，`GET /health` 用于排查。`scripts/test_audio_receiver.py` 本地测试 **30/30 通过**（合法上传、401、403、长度/格式/CRC 错误、内容篡改、请求体截断、静默连接超时、错误路径、GET 405、WAV 参数与内容一致、无临时文件）。
- 构建与烧录：三环境构建通过；`rgb_gpio48` Flash 923,625 字节、静态 RAM 55,300 字节（`diagnostics` 920,245 / 55,244；`rgb_gpio38` 923,617 / 55,300）；烧录 923,984 字节，`Hash of data verified`；启动日志 `[experiment 013] Wi-Fi audio upload / Arduino` 与 `UPLOAD_CONFIG configured=1 host=192.168.31.29 port=8080 path=/upload`（不含令牌）。
- 回归：外部 5V 断开、Wi-Fi 已连接，`scripts/test_serial_wifi.py` **1198 项通过**（实验 012 为 1188 项），新增无录音拒绝、空闲状态、录音中拒绝、unknown 子命令和启动配置检查；回归未触发真实上传。日志在本机 `work/test_serial_013c.log`，被 Git 忽略。
- 第一次实物上传失败与修复：用户录音 CRC `ab425206`，三次 `mic upload` 均在 5 秒后 `reason=stall`。根因是 Arduino-ESP32 2.0.17 的 `WiFiClient` 未实现 `availableForWrite()`，继承实现恒为 0，固件实际未发送任何字节；接收端也被空连接无限等待。已改为 `MSG_DONTWAIT` socket 发送，并给接收端增加请求头超时与该场景测试（30/30）；修复后重新构建、烧录与 1198 项回归通过。失败时未生成 WAV，录音仍在 RAM 中，可直接重试。
- 第二次实物上传与响应解析修复：用户重新录音 CRC `fdfbf19b` 后上传，接收端打印 `ok remote=192.168.31.17 bytes=320000 crc32=fdfbf19b file=mic-20261108-202103.wav count=1`，保存的 WAV 为 320,000 字节/160,000 帧，CRC 一致；对该文件运行 `asr_local.py` 得到 `hello hello这是一个AI测试你在听吗`。但固件因要求 `OK bytes=320000 crc32=...` 连续出现（实际响应中间有 `frames=160000`）而误报 `MIC_UPLOAD_FAILED reason=bad_response attempts=1`。已新增 `responseMatches()` 分别匹配 ` 200 `、`OK `、`bytes=`、`crc32=`；修复后重新构建、烧录与 1198 项回归通过（`work/test_serial_013c.log`）。
- 最终验收（2026-11-08，用户观察）：20:31 的另一次上传先确认 `MIC_UPLOAD_DONE ... crc32=66e82f60 attempts=1`；20:34 用户重新录音并一次上传成功，串口为 `MIC_RECORD_DONE ... crc32=ee814fb9` → `MIC_UPLOAD_DONE bytes=320000 crc32=ee814fb9 attempts=1` → `OK mic=uploaded`。接收端保存 `work/audio/mic-20261108-203520.wav`，PCM 320,000 字节、CRC `ee814fb9` 与固件一致，峰值 28.12%、语音覆盖 10 秒；`asr_local.py` 输出 `开始记录这是一个AI测试的测试我正在说话`，用户试听确认内容正确、句尾清楚。实验 013 第一阶段记为**已验收**。
- 尚未验证：上传期间 OLED/舵机/音频的实际并行表现、人为断网/接收端中途退出等重试场景；主机防火墙未用管理员权限检查，但本次真实上传成功说明当前路径可用。

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
| 实验 006 Git 同步 | 已完成 | 第一阶段的实现与验收提交 [4693430](https://github.com/Sprouting123/ai-desktop-robot/commit/469343005ba6b7cd3d704b25fd1d6d338ad52d4d)、第二阶段的实现与验收提交 [cc9d642](https://github.com/Sprouting123/ai-desktop-robot/commit/cc9d642b9c0e6f273aca30947a9648985d465467) 均已推送至 `origin/main`；`git ls-remote` 核对远程与本地 commit 一致 |
| 实验 007 未测量项 | 未测量 | 结构尺寸、重量、摇臂、电流、电压跌落、发热、实际角度、噪声、带载均无数据；结构或负载变化后需重新观察 |
| 实验 008 真实 Wi-Fi 连接 | 已验证（自动） | 2026-11-08 实测 `WIFI_CONNECTED ip=192.168.31.17 rssi=-40 channel=3`，`WEB listening=1`；IP 为 DHCP 分配，重启后可能变化 |
| 实验 008 HTTP 页面与 API | 已验收（自动 + 用户观察） | 1038 项回归含 HTTP 通过；2026-11-08 用户报告页面与远程控制测试通过 |
| 实验 008 远程舵机实物效果 | 已验收（用户观察） | 自动测试在用户授权、外部 5V 接通时驱动过舵机；用户报告网页控制测试通过，未做定量测量 |
| 实验 008 安全边界 | 已知限制 | 明文 HTTP、令牌保护写操作、仅供可信局域网；禁止公网映射或不受控 AP；未做渗透测试 |
| 实验 008 Git 同步 | 已完成 | 实现与验收提交 [922e24d](https://github.com/Sprouting123/ai-desktop-robot/commit/922e24dcb025e71fe85d0ef7f203deca4d9351ad) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地 commit 一致 |
| 实验 009 首次发声 | 已验收（用户观察） | 2026-11-08 外部 5V 供电、SD 接高后，用户发送 `audio beep` 确认听到短促提示音；开发板 `5Vin` 是输入，不能给功放供电 |
| 实验 009 音质与供电 | 未测量 | 音量、失真、爆音、功放发热、电压跌落均未测；功放与舵机共用外部 5V，同时负载未验证 |
| 实验 009 播放中 `audio stop` | 第一阶段软件已验证，待长音频复测 | 提示音仅 300ms，人工输入来不及；2.463s 的 `audio hello` 可在听音时补做 |
| 实验 009 非阻塞 | 软件已检查 | 分块状态机与 `i2s_write(...,0)`；回归中播放与动作/串口并行通过 |
| 实验 009 第一阶段 Git 同步 | 已完成 | 实现与验收提交 [76914ed](https://github.com/Sprouting123/ai-desktop-robot/commit/76914ed4a6e14d098b4fe3550293fdf81efbfeed) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地一致 |
| 实验 009 第二阶段听音 | 已验收（用户观察） | 2026-11-08 用户接通外部 5V 后发送 `audio hello`，报告试听成功；未逐项说明句尾完整性、爆音与音量，未做定量测量 |
| 实验 009 第二阶段音频资源 | 已入库（用户授权） | `assets/audio/hello_zh.raw` 由 Edge TTS 生成并随本阶段提交；Edge TTS 为非官方接口，资源仅用于本项目实验，公开再分发前需用户确认或改用许可明确的 TTS |
| 实验 009 第二阶段 Git 同步 | 已完成 | 实现、测试、文档与语音资源提交 [498d4f8](https://github.com/Sprouting123/ai-desktop-robot/commit/498d4f8af6cf453eaa65ea5e618ffe462f4aaca5) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地一致 |
| 实验 010 第二阶段试听 | 已验收（用户观察） | 2026-11-08 用户试听 `work/mic-20261108-181323.wav` 后确认能听清说话内容；有效语音约 0.6 秒，未做定量测量 |
| 实验 010 音频定量指标 | 未测量 | 灵敏度、噪声底、频响、失真、声压级、3V3 供电余量与长时间稳定性均无数据；录音中的爆音与削波未评估 |
| 实验 010 录音文件归档 | 未入库 | WAV、`work/` 下的诊断脚本与回归日志只在本机并被 Git 忽略；是否入库或分发需用户明确同意 |
| 实验 010 第二阶段 Git 同步 | 已完成 | 2026-11-08 经用户确认，固件、测试脚本、WAV 导出脚本与文档提交 [78b74fc](https://github.com/Sprouting123/ai-desktop-robot/commit/78b74fc0895c163dbcf0b61523a68394f9521ae0) 已推送至 `origin/main`；`git ls-remote` 核对一致；样本 WAV 与 `work/` 资料未入库 |
| 实验 011 识别文字确认 | 已完成（用户确认） | 2026-11-08 用户确认 `work/mic-20261108-181323.wav` 中能听到的就是“一二三”，ASR 输出与之一致；实验 011-1 的识别部分记为已验收 |
| 实验 011 录音起始截断 | 已修正并复测 | 旧提示从倒计时“3”开始说话，距 `mic record` 启动约 2 秒，加 0.5 秒启动瞬态，开头被截掉；改为录音启动 0.6 秒后提示 `>>> SPEAK NOW`。第二次录音语音从约 1.20 秒持续到 3.000 秒，确认开头已被捕获 |
| 实验 011 录音结尾截断 | 已解决（实验 012 整句复核通过） | 第二次录音中用户说“开始测试，这是一个AI测试”，3 秒窗口在句子中间结束，ASR 只得到“开始测试这是”。实验 012 把窗口延长到 10 秒；2026-11-08 用户重录同一句，语音约 1.19–4.54 秒结束后还有 5.46 秒静音，句尾完整，ASR 得到“开始测试这是一个ai测试” |
| 实验 012 整句试听与识别 | 已验收（用户观察） | 2026-11-08 用户在 `>>> SPEAK NOW` 后完整说“开始测试，这是一个AI测试”，WAV `work/mic-20261108-193259.wav`（10.000 秒，CRC `bf9753e4`）试听确认句尾清楚；ASR 输出“开始测试这是一个ai测试”，与实际内容逐字一致（仅无标点、`AI` 小写） |
| 实验 012 Git 同步 | 已完成 | 经用户确认，固件、脚本与文档提交 [874eca1](https://github.com/Sprouting123/ai-desktop-robot/commit/874eca1a01b8a29aac891c9253fe287542d0da95) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地一致 |
| 实验 013 实物上传验收 | 已完成（用户观察） | 第一次 `mic upload` 因 `availableForWrite()` 恒为 0 三次 `stall`；第二次真实传输已保存 WAV（CRC `fdfbf19b`），但固件因响应解析要求字段连续而误报 `bad_response`；两个缺陷修复并重新烧录后，20:34 重新录音一次上传成功，`MIC_UPLOAD_DONE ... crc32=ee814fb9 attempts=1`，WAV CRC 一致，ASR 输出 `开始记录这是一个AI测试的测试我正在说话`，用户试听确认句尾清楚。证据见[实验 013](experiments/013-wifi-audio-upload.md) 5.5 |
| 实验 013 网络与防火墙 | 未验证 | 主机 `ufw` 状态因无管理员权限未能查看；首次失败已定位为固件发送逻辑而非防火墙；若修复后仍失败，再确认接收端在 8080 监听、`AUDIO_UPLOAD_HOST` 为当前 Ubuntu 地址并检查防火墙 |
| 实验 013 Git 同步 | 未提交（待用户确认） | 固件、接收端脚本、测试与文档尚未提交或推送；按规则需用户明确确认后再执行 |
| 实验 011 有效语音长度 | 已知限制 | 第一次样本有效语音约 0.46 秒；第二次约 1.1 秒且在说话中途被截断。需用 5–10 秒窗口重录整句，才能评估连续语音、长句、数字与专有名词 |
| 实验 011 静音/弱语音误输出 | 已知限制 | 多个无有效语音的录音输出 `the the the知嗯`、`right is` 等；后续在主机侧加能量门限或 FunASR `fsmn-vad`，不能把非空输出当作识别成功 |
| 实验 011 资源与归档 | 本机保存、未入库 | 模型缓存 `work/models` 848 MiB、虚拟环境 `work/asr-venv` 约 1.7 GiB、录音与日志都在 `work/`，被 Git 忽略；是否分发模型或录音需用户明确同意 |
| 实验 011 Git 同步 | 已完成 | 2026-11-08 经用户确认，ASR 脚本、录音提示修正与文档提交 [b0fb4d6](https://github.com/Sprouting123/ai-desktop-robot/commit/b0fb4d64fe41f917490307d06a05395427c10378)、第二次录音结果文档提交 [ea4b039](https://github.com/Sprouting123/ai-desktop-robot/commit/ea4b03955c272a8ad501ee2c8752cd57f7a23287) 已推送至 `origin/main`；`git ls-remote` 核对一致；模型、venv、录音与日志未入库 |

实验 003 已核对 USB 目标；测试完成后脚本关闭了串口，用户可打开 VS Code Monitor。后续烧录或自动测试前，应关闭用户的监视器。

## 下一步与后续候选

**当前下一步：实验 013 收尾与后续小项。** 第二阶段已于 2026-11-09 端到端验收：用户按绿灯提示完整说出一句，10 秒录音 CRC `0aa5589a`，`mic upload` 一次成功（`attempts=1`），接收端 CRC 一致并保存 WAV，自动 ASR 输出“这是一个AI测试你能听到吗我正在讲话”，用户核对逐字一致。此前 OLED 显示消失的根因——SDA 杜邦母头未接触 GPIO8——已定位并换线修复，麦克风重新接插后 `mic level` 恢复。下一步：评估静音/弱语音（本次峰值仅 7%）与短录音的 ASR 误识别，讨论 VAD/能量门限；整理接收端自动 ASR、`mic probe`、`test_asr_pipeline.py` 等未提交改动，经用户确认后提交。真实上传仍需用户明确触发。

实验 006 遗留的可选补测仍可在 `motion wiggle` 运行中输入 `servo both stop` 完成；实验 007 的机械/电气定量测量也尚未进行。

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
| 2026-11-07 | 实验 006 第二阶段：`motion` 非阻塞动作序列与 `mood` 表情联动，含中途停止、切换、手动接管、非法命令保护；三环境构建、烧录校验、893 项串口/软件检查及 2 分钟连续运行通过；用户接通外部 5V 逐项确认动作、停止、mood 与 `mood stop` 正常，记为已验收 | [实验 006](experiments/006-dual-servo.md)；实现与验收提交 [cc9d642](https://github.com/Sprouting123/ai-desktop-robot/commit/cc9d642b9c0e6f273aca30947a9648985d465467) 已推送并核对一致 |
| 2026-11-08 | 实验 007：纸板机械原型完成，用户确认安装后的两只舵机与 OLED 情绪联动正常，记为已验收；结构尺寸、电流、供电稳定性、实际角度未测量 | [实验 007](experiments/007-cardboard-prototype.md)；证据为用户观察，无归档照片/视频 |
| 2026-11-08 | 实验 008：非阻塞 Wi-Fi STA、受限 HTTP API、`X-Auth-Token` 写保护、手机控制页、本地凭据模板与忽略规则；三环境构建通过，Wi-Fi 凭据为空的固件 910 项、不可达 SSID 固件 903 项检查通过 | [实验 008](experiments/008-wifi-control.md)；本机捕获与备份在 `work/`，被 Git 忽略 |
| 2026-11-08 | 实验 008 真实联网：用户填入 2.4GHz 凭据后烧录，`WIFI_CONNECTED ip=192.168.31.17 rssi=-40 channel=3`；含 HTTP 的完整回归 1038 项通过；外部 5V 接通（用户授权）下自动测试驱动过舵机；用户随后报告浏览器/手机页面与远程控制测试通过，实验 008 记为已验收 | [实验 008](experiments/008-wifi-control.md)；IP 由 DHCP 分配；验收证据为用户观察 |
| 2026-11-08 | 实验 009 第一阶段：新增 `AudioEngine` 与 `audio beep|stop|status`，ESP-IDF legacy I²S TX、16kHz/16bit/立体声、非阻塞分块播放、低幅度 880Hz/300ms 提示音；三环境构建通过，烧录后 `--no-audio-sound` 完整回归 1050 项通过；首次实际发声待用户观察 | [实验 009](experiments/009-audio-output.md)；首次提示音保留给用户 |
| 2026-11-08 | 实验 009 首次发声验收：排查确认开发板 `5Vin` 为输入、不能给功放供电；改用与舵机共用的外部 5V 并共地后，用户确认听到提示音；完整回归 1075 项通过 | [实验 009](experiments/009-audio-output.md)；实现与验收提交 [76914ed](https://github.com/Sprouting123/ai-desktop-robot/commit/76914ed4a6e14d098b4fe3550293fdf81efbfeed) 已推送；证据为用户观察 |
| 2026-11-08 | 实验 009 第二阶段软件完成：Edge TTS 生成中文语音，内嵌 flash 播放，新增 `audio hello` 与 `Source` 抽象；修正字节指针偏移、加入自然结束 drain；三环境构建、烧录与 1103 项回归通过（外部 5V 断开） | [实验 009](experiments/009-audio-output.md)；音频资源与转换说明见 `assets/audio/README.md` |
| 2026-11-08 | 实验 009 第二阶段听音验收：用户接通外部 5V、未同时驱动舵机，发送 `audio hello` 报告试听成功；第二阶段记为已验收（证据为用户观察） | [实验 009](experiments/009-audio-output.md)；提交 [498d4f8](https://github.com/Sprouting123/ai-desktop-robot/commit/498d4f8af6cf453eaa65ea5e618ffe462f4aaca5) 已推送并核对一致 |
| 2026-11-08 | 实验 010 第一阶段开始：新增 `microphone_engine`（I²S_NUM_1 RX、GPIO16/17/18、16kHz/32bit 槽、左声道、4×256 DMA、非阻塞读取）与 `mic status/start/level/stop`；上电不采集，`mic level` 提供 0.5s 窗口峰值/RMS 与 zero/no_data 判定；三环境构建通过 | [实验 010](experiments/010-microphone.md)；接线为计划值，待用户确认 |
| 2026-11-08 | 实验 010 第一阶段软件验证：烧录校验通过，含麦克风检查的完整回归 1152 项通过（Wi-Fi 含 HTTP，外部 5V 断开）；实测左声道全零、右声道有正常数据 | [实验 010](experiments/010-microphone.md) 6.3、6.4；诊断构建未保留 |
| 2026-11-08 | 用户核对并确认 INMP441 接线正确，左声道仍全零（`total_frames=301056`、`peak=0`）；按实测把固件改为 `I2S_CHANNEL_FMT_ONLY_RIGHT`，日志与测试同步为 `channel=right`，三环境构建、烧录与 1151 项回归通过；回归中 `signal=ok`、`peak≈1,342,808`、`rms≈1,010,716` | [实验 010](experiments/010-microphone.md) 6.3 |
| 2026-11-08 | 实验 010 第一阶段实物验收：用户讲话观察安静 peak 163,042（1%）→ 说话 526,968–536,016（6%），`signal=ok`、`zero_blocks=0`、`errors=0`，`mic stop` 后 `frames` 冻结在 7,370,496；第一阶段记为已验收（未做定量测量） | [实验 010](experiments/010-microphone.md) 6.4；证据为用户提供的串口读数与操作观察 |
| 2026-11-08 | 实验 010 第二阶段实现：新增 `mic record`/`mic dump`，3.000 秒 PSRAM 录音、8,000 帧启动瞬态丢弃、CRC-32 校验、2,000 行非阻塞传输；新增 `scripts/capture_mic_wav.py`（设备核对、30Hz 去直流、峰值归一化、WAV 输出）与回归检查；三环境构建通过 | [实验 010](experiments/010-microphone.md) 第 7 节；样本与本机日志在 `work/`，被 Git 忽略 |
| 2026-11-08 | 实验 010 第二阶段验收证据：烧录 920,368 字节且哈希校验通过，完整回归 1187 项通过（Wi-Fi 含 HTTP、外部 5V 断开）；诊断确认启动瞬态与直流偏置并修正；用户试听 `mic-20261108-181323.wav`（CRC `ac9af219`）确认能听清说话内容，第二阶段记为已验收 | [实验 010](experiments/010-microphone.md) 第 8 节；证据为用户听感，未做定量音频测量 |
| 2026-11-08 | 实验 010 第二阶段经用户确认提交并推送：固件、回归脚本、`capture_mic_wav.py` 与文档；`git ls-remote` 核对本地与远程一致；WAV 与 `work/` 资料未入库 | 提交 [78b74fc](https://github.com/Sprouting123/ai-desktop-robot/commit/78b74fc0895c163dbcf0b61523a68394f9521ae0) |
| 2026-11-08 | 实验 011-1 本地 ASR：独立 `work/asr-venv` 中 CPU 运行 FunASR Paraformer-large（ModelScope，Apache 2.0，模型缓存 848 MiB）；新增 `scripts/asr_local.py`；最终录音识别为“一二三”（加载 2.76 s、推理 0.10 s、RTF 0.034、峰值 RSS 2,261 MB），已知 TTS 对照有一处同音字错误；未改固件、未调用付费 API、未上传录音 | [实验 011](experiments/011-asr.md)；模型、venv、录音与日志在 `work/`，被 Git 忽略；提交 [b0fb4d6](https://github.com/Sprouting123/ai-desktop-robot/commit/b0fb4d64fe41f917490307d06a05395427c10378) 已推送 |
| 2026-11-08 | 实验 011-1 识别验收与录音提示修正：用户确认录音中能听到的就是“一二三”，ASR 识别正确；其前面几个字未被录到，定位为旧提示从倒计时“3”开始说话导致开头约 2.5 秒被截断。`scripts/capture_mic_wav.py` 改为主机在录音启动 0.6 秒后提示 `>>> SPEAK NOW`；第二次录音验证开头已捕获 | [实验 011](experiments/011-asr.md) 5.2、6、7、9；[实验 010](experiments/010-microphone.md) 7.4、8.3、8.4；提交 [b0fb4d6](https://github.com/Sprouting123/ai-desktop-robot/commit/b0fb4d64fe41f917490307d06a05395427c10378) 已推送 |
| 2026-11-08 | 实验 011-1 第二次录音：新提示下用户说“开始测试，这是一个AI测试”，语音从约 1.20 秒持续到 3.000 秒，ASR 输出“开始测试这是”；识别与已录内容一致，但“一个AI测试”被 3 秒上限截掉。记录模型加载 2.71 s、推理 0.10 s、RTF 0.033、峰值 RSS 2,270.1 MB；下一步延长录音到 5–10 秒 | [实验 011](experiments/011-asr.md) 5.3；[实验 010](experiments/010-microphone.md) 8.4；提交 [ea4b039](https://github.com/Sprouting123/ai-desktop-robot/commit/ea4b03955c272a8ad501ee2c8752cd57f7a23287) 已推送；样本 WAV 在 `work/`，未入库 |
| 2026-11-08 | 实验 012 实现：固定录音 3 秒 → 10 秒（160,000 帧、320,000 字节），`kDumpBytesPerLine` 48 → 50（6,400 行）；启动标记改为实验 012；`capture_mic_wav.py` 与回归脚本同步 10 秒常量和超时，等待逻辑改为标记行完整后返回 | [实验 012](experiments/012-10s-recording.md) 第 3、5 节；未提交 |
| 2026-11-08 | 实验 012 首次 dump 失败与修正：64 字节/行（140 字节）超过默认 128 字节串口 TX FIFO，`availableForWrite()` 永远不足，dump 停在 `PCM_BEGIN`；改为 50 字节/行（112 字节）后恢复；同时修正主机等待截断行的问题 | [实验 012](experiments/012-10s-recording.md) 5.2；此为调试过程，未单独提交 |
| 2026-11-08 | 实验 012 软件验证：三环境构建通过，烧录 920,384 字节且 `Hash of data verified`；完整回归 1188 项通过（外部 5V 断开、Wi-Fi 含 HTTP），录音 CRC `2e3614fa`、6,400 行/320,000 字节/主机 `zlib.crc32` 一致；`capture_mic_wav.py` 环境声跑通 10.000 秒 WAV（CRC `157c65e7`） | [实验 012](experiments/012-10s-recording.md) 5.3、5.4；日志与 WAV 在 `work/`，被 Git 忽略；未提交 |
| 2026-11-08 | 实验 012 整句验收：用户完整说“开始测试，这是一个AI测试”，WAV `work/mic-20261108-193259.wav` 为 10.000 秒（CRC `bf9753e4`），语音约 1.19–4.54 秒、后接 5.46 秒静音，句尾未被截断；ASR 输出“开始测试这是一个ai测试”，与实际内容逐字一致（加载 2.69 s、推理 0.20 s、RTF 0.020、峰值 RSS 2,255.2 MB）；用户确认句尾清楚，实验 012 记为已验收 | [实验 012](experiments/012-10s-recording.md) 5.5；证据为用户听感与逐字对照；提交 [874eca1](https://github.com/Sprouting123/ai-desktop-robot/commit/874eca1a01b8a29aac891c9253fe287542d0da95) 已推送 |
| 2026-11-08 | 实验 013 第一阶段实现：新增 `audio_uploader`、`mic upload`/`mic upload status`/`mic upload cancel`；ESP32 以二进制 HTTP POST 上传 320,000 字节 PCM 到 Ubuntu 8080，独立令牌、长度/格式/CRC 校验、分块非阻塞、1 秒 connect 超时、最多 3 次重试；新增 `scripts/audio_receiver.py` 与 `scripts/test_audio_receiver.py` | [实验 013](experiments/013-wifi-audio-upload.md) 第 3、5 节；未提交 |
| 2026-11-08 | 实验 013 软件验证：三环境构建通过，烧录 923,744 字节且 `Hash of data verified`，启动 `UPLOAD_CONFIG configured=1`；完整回归 1198 项通过（外部 5V 断开、Wi-Fi 含 HTTP、未触发真实上传）；接收端本地测试通过；真实 ESP32 → Ubuntu 上传与 WAV/ASR 验收待用户执行 | [实验 013](experiments/013-wifi-audio-upload.md) 5.2–5.3；日志与令牌在 `work/`，被 Git 忽略；未提交 |
| 2026-11-08 | 实验 013 首次实物上传失败与修复：用户录音 CRC `ab425206`，三次 `mic upload` 均以 `reason=stall` 失败。根因是 Arduino-ESP32 2.0.17 的 `WiFiClient` 未实现 `availableForWrite()`（继承版本恒为 0），固件未发出任何字节；接收端也被静默连接无限等待。改为 `MSG_DONTWAIT` socket 发送，接收端增加请求头超时与静默连接测试（30/30）；三环境构建、烧录 923,984 字节（哈希校验）与 1198 项回归重新通过 | [实验 013](experiments/013-wifi-audio-upload.md) 5.4；失败时未生成 WAV；修复后真实上传待用户重试；未提交 |
| 2026-11-08 | 实验 013 第二次实物上传与响应解析修复：录音 CRC `fdfbf19b` 上传后，接收端保存 320,000 字节 WAV（`mic-20261108-202103.wav`，CRC 一致），`asr_local.py` 输出 `hello hello这是一个AI测试你在听吗`；固件却因成功响应中 `bytes=` 与 `crc32=` 之间有 `frames=` 而误报 `bad_response`。新增 `responseMatches()` 分别匹配各字段；修复后三环境构建（`rgb_gpio48` 923,625 字节）、烧录 923,984 字节、1198 项回归通过 | [实验 013](experiments/013-wifi-audio-upload.md) 5.4；`work/test_serial_013c.log`；WAV 与日志仅在本机，被 Git 忽略；未提交 |
| 2026-11-08 | 实验 013 第一阶段验收：修复后的固件于 20:31 与 20:34 两次真实上传均 `MIC_UPLOAD_DONE ... attempts=1`（20:34 录音 CRC `ee814fb9`）；接收端保存 `mic-20261108-203520.wav`，PCM CRC 一致，峰值 28.12%、语音覆盖 10 秒；`asr_local.py` 输出 `开始记录这是一个AI测试的测试我正在说话`，用户试听确认内容正确、句尾清楚。实验 013 第一阶段记为已验收 | [实验 013](experiments/013-wifi-audio-upload.md) 5.5；WAV 仅在 `work/audio/`，被 Git 忽略；未提交 |
| 2026-11-08 | 实验 013 Git 同步：经用户确认，固件、接收端脚本、测试与文档提交 [a026bda](https://github.com/Sprouting123/ai-desktop-robot/commit/a026bdab8a12205914ed644adbd6409b98e3caf4) 已推送至 `origin/main`；`git ls-remote` 核对远程与本地一致；密钥、WAV、模型、venv 与日志未入库 | 见[实验 013](experiments/013-wifi-audio-upload.md) |
| 2026-11-09 | 实验 013 第二阶段 Git 同步：经用户确认，接收端自动 ASR、`mic probe`、测试与文档提交 [0cdd04a](https://github.com/Sprouting123/ai-desktop-robot/commit/0cdd04acd83868d92d728ac17d8518e419dd06d2) 已推送至 `origin/main`，`git ls-remote` 核对远程与本地一致；提交前本地测试 `test_audio_receiver.py` 30/30、`test_asr_pipeline.py` 39/39 通过；密钥、WAV、模型与日志未入库 | [实验 013](experiments/013-wifi-audio-upload.md) 5.6 |
| 2026-11-09 | 实验 013 第二阶段端到端跑通：修复 OLED SDA 接触与麦克风接插后，接收端自动 ASR 首次真实运行；用户按绿灯提示完成 10 秒录音（CRC `0aa5589a`），`mic upload` 一次成功（`attempts=1`），接收端 CRC 一致并保存 `mic-20261109-230828.wav`，ASR 输出“这是一个AI测试你能听到吗我正在讲话”，用户核对该文本与实际所说逐字一致，第二阶段记为已验收 | [实验 013](experiments/013-wifi-audio-upload.md) 5.6；WAV 与 JSON 在 `work/`，被 Git 忽略；未提交 |

## 维护方法

- 每次项目状态有变化，更新日期、当前状态、里程碑、未决事项和下一步；已解决问题保留简短结论，避免重复排查。
- 每次新实验都链接到其独立记录；日志、实测和用户反馈各自标明来源。
- 稳定的协作或硬件约束变化时同时更新根目录 `AGENTS.md`；临时过程细节留在实验记录。
- 在同一任务的 Git 提交中同步相关进度，提交前检查差异，push 前检查状态和远程变化，push 后核对远程提交。
- 文档中的同步描述不能代替 Git 验证。提交号引用既有提交；本次提交与远程一致性由实际 Git 命令核查，避免预写成功状态或循环引用自身提交号。
