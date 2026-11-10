# 实验 015：AI 语音回复（TTS 与 ESP32 无线播放）

状态：已验收（2026-11-10）。主机 TTS、回答存储与鉴权下载接口、ESP32
`voice` 命令与自动取回均已实现，并通过软件测试、真实 Edge TTS 生成和
实机链路检查；2026-11-10 用户已通过电脑蓝牙音箱（小度 A26）试听 Edge TTS
并确认“很清楚”，随后明确决定暂时跳过 CosyVoice 对比，以 Edge 作为当前
方案。当天用户接通外部 5V 后确认 ESP32 扬声器播放清楚、播放中 `voice stop`
立即停止，并完成一次由本人讲话触发的真实闭环：录音 → ASR → DeepSeek →
Edge TTS → ESP32 自动下载并在扬声器播出回答。第一、二阶段均记为已验收，
证据为用户听感与串口/接收端记录，未做定量声学测量。

## 1. 目标

把实验 014 的“语音 → ASR → DeepSeek 文字回答”继续接成可听见的对话：

1. 主机把 AI 文字回答合成为 16kHz/16bit/单声道 PCM，先在本机试听。
2. TTS 做成可切换供应商的独立模块：开发/兜底用 Edge TTS，长期部署优先
   阿里云百炼 CosyVoice 官方接口。
3. ESP32 通过已鉴权的局域网接口下载回答音频，复用 MAX98357A 与
   `AudioEngine` 播放；下载、重试、停止都不阻塞 OLED、舵机与 Wi-Fi。
4. 打通真实闭环：用户讲话 → 上传 → ASR → DeepSeek → TTS → ESP32 扬声器。

本实验不实现麦克风唤醒词、流式双向语音、Opus 解码或把原始录音发给大模型。
费用授权：用户已允许正常开发和测试中直接调用付费 API；仍需限制超时、字符数、
重试与并发，保护 Key，并记录实际用量和成本。Git 提交与推送仍需确认。

## 2. 硬件与现有基础

- ESP32-S3 N16R8，Arduino-ESP32 2.0.17，实验 013/014 固件；OLED、双舵机、
  RGB、Wi-Fi/HTTP、麦克风与 MAX98357A 均已验收。
- 音频输出：I²S TX，BCLK GPIO7 / LRC GPIO15 / DIN GPIO6，16kHz、16bit、
  双声道同一样本；`AudioEngine` 从 `Source` 拉取，每轮最多写一块 240 帧。
- 麦克风：INMP441，I²S1 RX，GPIO16/17/18，10 秒录音 320,000 字节。
- 主机：Ubuntu，项目 `.venv`；Edge TTS 与 ffmpeg 的依赖放在被 Git 忽略的
  `work/tts-venv`。
- 外部 5V 给 MAX98357A 与舵机供电；构建、烧录、自动回归期间保持断开，
  需要听声音时由用户接通。

## 3. 实际方案

| 层 | 实现 |
| --- | --- |
| TTS 适配 | `scripts/tts_client.py`：`TTSProvider` 接口；Edge TTS 与阿里云 CosyVoice 两个实现，可命令行切换 |
| 默认供应商 | Edge TTS `zh-CN-XiaoxiaoNeural`、语速 `-5%`；免费、不需要 Key，属非官方接口，仅作为开发与兜底 |
| 官方候选 | 阿里云百炼 CosyVoice HTTP/SSE，默认 `cosyvoice-v3-flash` + `longxiaochun_v3`、`format=pcm`、`sample_rate=16000`；代码与测试已完成，缺 Key 未做真实调用。用户于 2026-11-10 决定先跳过真实对比，Edge 为当前方案，后续可随时切换验证 |
| 统一输出 | 16kHz/16bit/单声道 little-endian PCM；同时保存可试听的 WAV；单句上限 300 字符、音频上限 60 秒 |
| 主机存储 | `work/tts/` 保存每次 TTS 的 PCM/WAV/JSON；`work/replies/` 保存最新回答及 `latest.json`，最多保留 20 条，全部被 Git 忽略 |
| 下载接口 | `GET /reply/latest`，可带 `?turn=<上传编号>`；要求 `X-Auth-Token`，返回原始 PCM 与长度/采样率/声道/帧数/CRC 头 |
| 上传衔接 | 接收端在 `200` 上传响应末尾追加 `turn=<id>`；ESP32 保存该编号，只取这一次录音对应的回答，避免重放旧回答 |
| ESP32 | `src/voice_receiver.*`：非阻塞下载状态机，PSRAM 缓冲、CRC-32 校验，复用 `AudioEngine::playClip`；新增 `voice ...` 命令 |
| 自动播放 | 固件默认 `voice auto on`，但只在一次显式 `mic upload` 成功且拿到 `turn` 后触发；手动 `voice fetch`/`voice play` 始终可用 |

费用按 2026-11-10 百炼价格页估算，仅作参考：`cosyvoice-v3-flash`
¥1.0/万输入字符，`cosyvoice-v3.5-flash` ¥0.8，`cosyvoice-v3-plus` ¥2.0，
`cosyvoice-v3.5-plus` ¥1.5，`cosyvoice-v2` ¥2.0；输出音频时长不计费。
Edge TTS 费用记为 0。实际供应商选择仍以用户试听、延迟和稳定性为准。

## 4. 验收标准

### 第一阶段（TTS）

1. 同一句 AI 回答能由 Edge TTS 和 CosyVoice（配置 Key 后）生成
   16kHz/16bit/单声道 PCM；记录生成时间、音频大小、时长与费用。
2. 用户在本机试听，确认中文自然、无明显爆音或截尾。
3. TTS 供应商可配置切换；缺 Key、超时、HTTP 错误、空音频时给出可读错误，
   不崩溃、不泄漏 Key，不产生失控重试。
4. 自动测试使用本地假服务器或假命令，不依赖真实付费调用。

### 第二阶段（ESP32 播放）

1. 鉴权下载：缺令牌 401、错令牌 403、无回答 404；返回 PCM 的长度、
   采样率、声道、帧数与 CRC 可被固件校验。
2. ESP32 下载并播放一句 AI 回答；`voice stop` 能立即停止播放或取消下载。
3. 重复 `voice play` 不重复下载，重复 `voice fetch` 行为可预期。
4. 下载/播放期间 OLED 眨眼、串口命令、Wi-Fi/HTTP 与舵机动作继续响应。
5. 真实闭环由用户讲话触发，扬声器播出对应回答；用户观察作为验收依据。

## 5. 实施记录

### 5.1 主机 TTS 适配模块

新增 `scripts/tts_client.py`，只用 Python 标准库；Edge 路径通过
`work/tts-venv/bin/python` 调用 `edge-tts 7.3.1` 生成 MP3，再交给 ffmpeg
做首尾静音裁剪、10ms 淡入淡出并转成 16kHz/16bit/单声道 PCM。CosyVoice
路径直接请求百炼 `SpeechSynthesizer` 接口，解析 SSE 中的音频 URL 或
base64 音频，按返回的 PCM 再统一校验。

- Key 只从 `DASHSCOPE_API_KEY` 或被 Git 忽略的 `work/dashscope_api_key`
  （建议权限 600）读取；不打印、不写入记录、不进入错误文本；宽松权限会
  给出警告。
- 校验：文本 1–300 字符、PCM 为偶数长度、不超过 60 秒、采样率/声道符合
  预期；错误原因包括 `missing_api_key`、`invalid_text`、`timeout`、
  `network_error`、`bad_response`、`empty_audio`、`audio_too_large` 等。
- 每次成功生成写一份 JSON，记录供应商、模型/音色、字符数、PCM 字节、
  帧数、时长、延迟、HTTP 状态、费用估算与文件路径。
- 命令行示例：

  ```bash
  env -u PYTHONPATH work/tts-venv/bin/python scripts/tts_client.py \
      "你好，我是小桌。" --provider edge --play
  env -u PYTHONPATH .venv/bin/python scripts/tts_client.py \
      "你好，我是小桌。" --provider cosyvoice
  ```

- `scripts/test_tts_client.py` 使用本地假 HTTP/SSE 服务器和假命令，覆盖
  两个供应商的请求头、PCM/WAV 写出、超时、错误响应、Key 不泄漏、费用与
  元数据；**68/68 通过**，不产生真实 TTS 调用。

### 5.2 Edge TTS 真实生成与 CosyVoice 阻塞

2026-11-10 用实验 014 的真实回答做 Edge TTS 生成，得到：

| 文本 | 字符 | 生成延迟 | PCM 字节 | 音频时长 | 费用 |
| --- | --- | --- | --- | --- | --- |
| 你好呀主人，我不是捉宠，是小桌，住在你的桌面机器人里陪你聊天的小伙伴。 | 35 | 1,627.8 ms | 218,896 | 6,840.5 ms | ¥0 |
| 你好呀主人！我不是桌宠，是小桌，住在你的桌面机器人里陪你聊天的小伙伴。 | 35 | 1,629.7 ms | 244,438 | 7,638.7 ms | ¥0 |

文件分别在 `work/tts/tts-20261110-000929-a6bc.*` 与
`work/tts/tts-20261110-000225-9236.*`。生成链路、格式、长度与记录均正常；
**2026-11-10 用户试听：** 电脑默认输出先指向无音箱的 HDMI，`aplay` 显示
播放但听不到声音；切换到已连接的蓝牙音箱“小度 A26”后，用户确认
`tts-20261110-000929-a6bc.wav`“有声音了，很清楚”。Edge 的清晰度通过
用户听感验收；语速、自然度与句尾完整性未逐项打分，也没有定量音频测量。

CosyVoice 代码、配置校验与本地假服务测试已完成，但本机没有
`work/dashscope_api_key`，环境变量也未设置，未发出任何真实付费 TTS 请求。
因此“官方 TTS 的中文自然度、延迟、音频大小与费用”目前只有价格页估算，
没有实测。2026-11-10 用户明确选择“跳过 CosyVoice，先试扬声器”，Edge
作为当前供应商；CosyVoice 的代码与测试保留，之后有 Key 时可随时对比。

### 5.3 回答存储与鉴权下载接口

新增 `scripts/reply_store.py`：接收端在 TTS 成功后把该回合的 PCM、WAV 与
元数据原子写入 `work/replies/reply-<turn>.{pcm,wav,json}`，并更新
`latest.json`；只保留最近 20 条，写入使用临时文件 + 替换，读取时重新校验
JSON、文件大小与 PCM 长度。音频固定为 16kHz/16bit/单声道，最长 60 秒。

`scripts/audio_receiver.py` 新增：

- `GET /reply/latest`：校验 `X-Auth-Token`；缺令牌 401、错令牌 403；无回答
  404；`turn` 格式非法 400。
- 成功响应为 `Content-Type: application/octet-stream`，带 `Content-Length`、
  `X-Audio-Format: s16le`、`X-Sample-Rate`、`X-Channels`、`X-Frames`、
  `X-Crc32`、`X-Reply-Id` 与 `Connection: close`。
- `POST /upload` 成功响应增加 `turn=<id>`；ASR/LLM/TTS 仍在该回合的后台
  worker 中串行执行，上传响应不等待模型或 TTS。
- TTS 默认开启，`--no-tts` 关闭；`--tts-provider edge|cosyvoice|none`、
  `--tts-voice`、`--tts-model`、`--tts-key-file`、`--tts-max-chars`、
  `--reply-dir` 等参数可调；Key 缺失时打印可见原因并禁用 TTS，不影响
  录音接收与 ASR。
- 终端新增 `[tts] status=success ...` 或 `[tts] status=error reason=...`，
  TTS 失败只记录原因，不生成回答文件。

`scripts/test_reply_store.py` 覆盖存储原子性、ID/长度校验、裁剪、TTS 成功/
失败钩子、401/403/404/400、响应头与正文、按 turn 命中/未命中、最新回答
选择以及旧 turn 仍可下载；**43/43 通过**。`scripts/test_audio_receiver.py`
仍为 **30/30 通过**，原有上传、CRC 与超时行为未回退。

### 5.4 ESP32 固件：下载、校验、播放与命令

新增 `src/voice_receiver.h/.cpp`：

- `reply::Client` 复用 `upload::Client` 最后一次成功上传的 `turn`；请求
  `GET /reply/latest?turn=<turn>`，带 `X-Auth-Token`，`Connection: close`。
- 状态机 `idle/connecting/sending/header/body/wait/done/failed`，每轮
  `loop()` 最多推进一步；connect 超时 1 秒、停滞 5 秒、单次尝试 15 秒；
  自动轮询间隔 700ms、最多 20 秒。404 时自动模式继续轮询，手动模式立即
  报 `no_reply`。
- 只接受 200；校验 `Content-Length` 不超过 60 秒、为偶数、16kHz、单声道、
  `X-Frames == bytes/2`；缓冲优先 PSRAM，失败退回内部堆；正文收满后按
  `X-Crc32` 校验，通过才替换旧缓存并包装成 `audio::Clip`。
- 播放复用 `audio_.playClip()`；再次播放只重发缓存，不重新下载。下载失败、
  超时或 CRC 不匹配会关闭 socket、释放未完成缓冲，并打印
  `VOICE_FAILED reason=...` 与 `ERR voice_failed reason=...`。
- 令牌只保存在 RAM，`VOICE_CONFIG` 与所有日志都不打印令牌。

`src/main.cpp` 新增命令：

```text
voice status
voice fetch          # 按最近一次上传的 turn 取回答
voice fetch newest   # 取最新回答（诊断用）
voice play           # 播放/重放已缓存的回答
voice stop           # 取消下载或轮询；若正在播放回答则停止播放
voice auto on|off    # 默认 on；只有显式 mic upload 成功后才自动取回
```

错误包括 `ERR voice_busy`、`ERR voice_not_configured`、`ERR voice_wifi`、
`ERR voice_bad_turn`、`ERR voice_no_clip`、`ERR voice_play_failed`、
`ERR voice_usage`、`ERR voice_failed reason=...`。配置复用
`src/secrets.h` 的 `AUDIO_UPLOAD_HOST/PORT/TOKEN`，TTS 密钥不进入固件。

启动标记改为 `[experiment 015] Wi-Fi voice reply / Arduino`。三环境构建
通过；烧录 **931,392 字节**且输出 `Hash of data verified`。

### 5.5 实机与接口链路检查

接收端先在旧 WAV 上重跑 ASR → DeepSeek → Edge TTS，发布回答
`20261110-000919-offline`，再用 `curl` 校验下载接口：HTTP 200、头字段
正确、下载正文与保存的 PCM 完全一致，CRC `d138ae25`；缺令牌/错令牌/无回答
分别返回 401/403/404。

实机串口检查（外部 5V 断开，未真正发声）：

- `voice status`：`configured=1`，`host=192.168.31.29`、`port=8080`，
  初始无缓存。
- `voice fetch newest`：下载 **218,896 字节 / 109,448 帧 / 6,840ms**，
  固件计算 CRC `d138ae25` 与接收端一致。
- `voice play`：`AUDIO state=playing source=clip clip=reply`；
  `voice stop` 返回 `OK voice=stopped download=0 playback=1`，状态回到空闲。
- 未下载时 `voice play` 返回 `ERR voice_no_clip`；无回答时手动取回返回
  `ERR voice_failed reason=no_reply`。
- 真实上传得到 `MIC_UPLOAD_DONE ... turn=20261110-003204-03`，自动模式随后
  只轮询该 turn（`VOICE_FETCH_START turn=... poll=1`）；`voice stop` 能取消
  轮询。该录音被主机判定为静音，没有 TTS 回答，因此这次只验证了“轮询与
  取消”，没有形成自动下载并播放的成功样本。
- 下载/轮询期间 OLED 眨眼、`eyes`/`motion` 命令与 Wi-Fi/HTTP 继续响应。

最终回归 `scripts/test_serial_wifi.py` **1217 项通过**（Wi-Fi 已连接、含
HTTP，外部 5V 断开；日志 `work/test_serial_015e.log`）；回归不发起真实
上传或真实 TTS。

### 5.6 完整主机链路（旧录音）

用实验 014 的旧 WAV 验证了“ASR → DeepSeek → TTS → 回答存储 → HTTP 下载”：

- ASR：`你好啊你是捉宠吗我是你的主人`
- DeepSeek：`你好呀主人，我不是捉宠，是小桌，住在你的桌面机器人里陪你聊天的小伙伴。`
  延迟 1,044.3ms，输入 89 / 输出 20 / 总 109 Token，估算 USD 0.000025。
- Edge TTS：35 字符、1,627.8ms 生成、6,840.5ms 音频、218,896 字节，¥0。
- 回答发布为 `reply-20261110-000919-offline`，下载 CRC 一致。

随后两次用主机扬声器播放录音、由 ESP32 麦克风采集的尝试都被静音门限
（`peak_pct≈27–29`、`active_ms=10–50`）拒绝，没有调用 LLM/TTS，也没有产生
费用。这条路径不能替代用户真实讲话；2026-11-10 08:30 由用户本人讲话
完成的闭环见 5.8。

### 5.7 故障与修正

1. 首次自动取回得到 `VOICE_AUTO_SKIP reason=no_turn`：上传响应缓冲只有
   256 字节，`turn=` 位于响应末尾、被截断。改为 512 字节，并等接收端关闭
   连接后再判定成功。
2. 随后 `VOICE_FAILED reason=header`：下载请求缓冲按 136 字节分配，实际
   `GET` 行加 `Host`/令牌超过该长度，请求被截断。请求缓冲改为 320 字节。
3. 失败路径未清除轮询/自动播放标记，可能在失败后继续使用旧状态；已在
   `fail()` 与 `commit()` 中清除。
4. `voice stop` 曾先打印内部取消行再打印命令结果；改为内部
   `VOICE_CANCEL poll=...`，保持命令输出只有一行。
5. `test_tts_client.py` 的假服务器在客户端提前关闭时会抛
   `BrokenPipeError/ConnectionResetError`；已捕获，测试稳定在 68/68。

### 5.8 用户试听与闭环执行

1. **Edge TTS 试听（第一阶段）：已完成（2026-11-10）。** 用户在 Ubuntu
   上通过蓝牙音箱播放 `work/tts/tts-20261110-000929-a6bc.wav`，确认
   “有声音了，很清楚”。注意第一次 `aplay` 走的是没有音箱的 HDMI 输出，
   听不到声音不代表文件损坏；换到蓝牙音箱后正常。
2. **CosyVoice 真实对比（第一阶段）：已跳过（2026-11-10 用户决定）。**
   用户选择先完成扬声器与完整闭环，Edge 作为当前供应商。代码与测试保留；
   以后如需官方 TTS，由用户在自己的终端配置 `work/dashscope_api_key`
   （权限 600，不要发到会话里），再用 `--provider cosyvoice` 生成同句对比。
3. **ESP32 播放试听（第二阶段）：已完成（2026-11-10）。** 用户接通外部
   5V（舵机保持空闲），接收端用
   `env -u PYTHONPATH .venv/bin/python -u scripts/audio_receiver.py --reply-dir work/replies`
   启动。串口 `voice fetch newest` 取回 218,896 字节、109,448 帧、
   6,840 ms、CRC `d138ae25` 的缓存回答，`voice play` 后用户确认“听到了，
   很清楚”。播放约 2.5 秒后发送 `voice stop`，返回
   `OK voice=stopped download=0 playback=1`，用户确认声音立即停住，缓存保留。
4. **真实闭环（第二阶段）：已完成（2026-11-10）。** 用户执行
   `mic record` 并说出“小桌你好，给我讲一句鼓励的话，比如说今天我很棒呀”，
   10 秒录音 CRC `78c7776c`，`mic upload` 一次成功
   （`attempts=1`，`turn=20261110-083021-02`）。接收端 ASR（200.8 ms）
   输出“小卓你好给我一句鼓励的话比如说今天我很棒呀”；DeepSeek
   `deepseek-flash` 延迟 732.2 ms、92/15/107 Token、估算
   USD 0.000023，回答“今天你已经很努力啦，记得夸夸自己，你真的很棒。”；
   Edge TTS 23 字符、延迟 1,612.9 ms、音频 4,255 ms、136,160 字节、
   CRC `f4d5fd6b`、费用 ¥0。ESP32 自动轮询到该 turn，输出
   `VOICE_READY` → `OK voice=playing`，播放完毕后
   `state=done playing=0`，用户确认听到了这句回答。
5. 补充观察：第一次闭环录音（CRC `ef76ad3d`）上传成功，但 ASR 判定
   `silent`（hp_rms_pct=0.1、active_ms=30），未生成回答，ESP32 轮询 20 秒后
   `VOICE_FAILED reason=no_reply`。随后用主机扬声器播放实验 013 的已知语音，
   `mic level` 读到 `peak_pct` 13% → 1–5%，证明麦克风链路正常；第二次
   用户及时开口后闭环成功。该现象按“录音窗口内没有人声”处理，不是固件或
   网络缺陷。另有一次开发板刚复位、Wi-Fi 刚连上时 `voice fetch newest`
   返回 `short_body`，连接稳定后重试成功；实机操作应在 `WIFI_CONNECTED`
   之后再取回。

### 5.9 验收结论

实验 015 第一、二阶段均记为**已验收**（2026-11-10）。依据：

- 软件：三环境构建通过，烧录校验通过，`test_serial_wifi.py` 1217 项、
  `test_tts_client.py` 68 项、`test_reply_store.py` 43 项、
  `test_audio_receiver.py` 30 项本地检查通过；自动测试不调用真实付费 TTS。
- 主机：Edge TTS 真实生成与试听通过；鉴权下载接口返回长度/帧数/CRC 正确。
- 硬件：ESP32 扬声器播放清楚，`voice stop` 立即停止；真实闭环中用户讲话
  得到语义对应的 DeepSeek 回答并由机器人扬声器播出，用户确认听到。
- 未做：扬声器响度、失真、功耗、端到端时延分布的定量测量；CosyVoice
  真实对比；唤醒词与流式对话。

## 6. 学习要点

- 回答音频用 `turn` 绑定到具体上传，而不是“取最新文件”，否则网络慢时
  很容易把上一条回答当成这一次的回复。
- 下载与上传一样，必须是非阻塞状态机；`WiFiClient::availableForWrite()`
  在 2.0.17 中不可用，发送侧仍应使用 `MSG_DONTWAIT`。
- 只有长度、格式、帧数和 CRC 全部通过才替换播放缓存，失败时保留旧缓存，
  避免把半截音频送进 I²S。
- TTS 与 ASR/LLM 都应放在主机侧，ESP32 只做采集、下载、播放和表情/动作，
  这样更换供应商不需要重新烧录固件，也不会把密钥放进设备。
- Edge TTS 适合开发和兜底，但不是官方长期接口；官方 CosyVoice 的真实
  效果与成本必须用实际调用确认，不能只依据价格页和代码路径。

## 7. 下一步

实验 015 已验收。后续可选工作：

1. CosyVoice 真实对比（需要用户配置 `work/dashscope_api_key`），比较音质、
   延迟与费用后再决定长期供应商。
2. 唤醒词、VAD 与流式双向语音；当前仍是“按命令录音 10 秒”的半双工流程。
3. 说话时同步 OLED 表情/舵机动作，以及回答播放期间的打断策略。
4. 扬声器响度、失真、电流与端到端时延的定量测量。
5. 固件与主机侧的回答缓存策略（掉电后缓存丢失，当前设计如此）。

Git 提交与推送在用户确认后执行。
