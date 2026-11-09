# 实验 014：DeepSeek API 文本对话与 ASR 衔接

状态：第一、二阶段已验收（2026-11-09）；第三阶段仅完成接口与迁移划分的设计说明，未实施

## 1. 目标

把桌宠的“听懂之后怎么回答”接到云端大模型，同时保留以后替换供应商和迁移到
阿里云服务器的空间。原方案中的 Ollama / 本地 Qwen 不再采用：本机与计划中的
阿里云 2 核 2GB 服务器都不适合运行大语言模型。

三个阶段：

1. **第一阶段：DeepSeek 文本对话。** 主机侧独立 LLM 客户端，默认
   `deepseek-flash` 非思考模式，多轮上下文有上限，记录延迟、Token 与估算费用。
2. **第二阶段：与实验 013 自动衔接。** ASR 识别成功后，把文本交给 DeepSeek，
   在 Ubuntu 终端显示用户问题与回答，会话记录写入被 Git 忽略的目录。ASR
   失败、静音或文本无效时不调用模型；HTTP 上传响应不等待模型生成。
3. **第三阶段：为独立运行预留接口。** 只做设计说明，不在本阶段改 ESP32
   固件、舵机、GPIO 或 TTS。

## 2. 硬件与软件

- 现有 ESP32-S3 固件保持实验 013：负责录音与 `mic upload`，不保存 API Key，
  不直接访问 DeepSeek。
- 主机 Ubuntu：Python 3.10，项目 `.venv`；`scripts/llm_client.py` 只用标准库
  （`http.client`、`json`、`urllib.parse`），不新增依赖。
- 网络：DeepSeek 官方 OpenAI 兼容接口
  `POST https://api.deepseek.com/chat/completions`；本阶段不部署代理、不上传
  音频、不调用付费 API，除非用户明确授权。
- 阿里云服务器（后续）：Ubuntu、2 核 CPU、2GB 内存，不放本地大模型或当前
  Paraformer；只作为云端编排与 API 调用节点。

## 3. 设计

### 3.1 模块划分

| 模块 | 位置 | 职责 |
| --- | --- | --- |
| LLM 客户端 | `scripts/llm_client.py` | 供应商接口、DeepSeek HTTP 调用、历史裁剪、费用估算、回合记录 |
| 接收端 | `scripts/audio_receiver.py` | 接收 PCM、校验、保存 WAV、调用 ASR，再调用 LLM |
| ASR | `scripts/asr_local.py` | 本地 Paraformer，输出单行 JSON（本阶段不变） |
| 会话记录 | `work/sessions/*.json` | 每回合的 session id、耗时、Token、费用、状态；被 Git 忽略 |

`DeepSeekProvider` 只实现 `complete(messages) -> LLMResponse`，`ChatSession`
依赖这个接口而不是具体供应商；以后换供应商时保留会话、记录与费用逻辑。

### 3.2 请求参数

```json
{
  "model": "deepseek-flash",
  "messages": [
    {"role": "system", "content": "<桌宠角色设定>"}
  ],
  "max_tokens": 200,
  "temperature": 0.7,
  "stream": false,
  "thinking": {"type": "disabled"}
}
```

- 默认连接超时 5 s、读取超时 30 s；超时、连接失败、HTTP 401/402/429/5xx、
  非 JSON、空回复分别映射为可读的原因，不自动重试，避免重复计费。
- 错误信息会去掉 API Key；Key 不出现在日志、会话文件和终端输出中。
- 多轮上下文默认保留最近 6 组 user/assistant（最多 4000 字符），超出时从
  最旧的整组开始丢弃；system 角色设定始终保留。
- 角色设定：桌宠“小桌”，自然、温暖、简短，不超过两句话或约 50 个汉字，
  便于后续 TTS；不使用 Markdown、列表或表情符号。

### 3.3 Key 与费用

- Key 优先读环境变量 `DEEPSEEK_API_KEY`，否则读被 Git 忽略的
  `work/deepseek_api_key`（建议权限 600）；文件权限过宽时打印警告。
- 用户在自己的终端写入 Key，不通过聊天窗口发送。
- 费用按 2026-11-09 官方价格快照估算（每百万 Token，美元）：

| 项目 | 非高峰 | 高峰 |
| --- | --- | --- |
| 输入（缓存命中） | 0.003 | 0.006 |
| 输入（缓存未命中） | 0.15 | 0.30 |
| 输出 | 0.60 | 1.20 |

高峰时段为 UTC 工作日 01:00–04:00 与 06:00–10:00；中国法定节假日未建模，
节假日请求可能被高估。估算值只用于日常观察，不能替代官方账单。

## 4. 验收标准

### 第一阶段

1. 用用户配置的 Key 发送一次真实文本请求，模型为 `deepseek-flash`，
   非思考模式，得到简短中文回答。
2. 终端与 `work/sessions/` 记录实际延迟、输入/输出/总 Token 与估算费用。
3. 缺 Key、HTTP 错误、超时、畸形响应等路径不崩溃、不泄漏 Key（已用本地
   模拟服务器验证）。
4. 未授权时不得产生任何付费请求。

### 第二阶段

1. 真实录音 → 上传 → ASR 成功后，终端同时显示识别文本与 AI 回答。
2. 会话 JSON 写入 `work/sessions/`，包含会话 ID、耗时、Token、费用与状态。
3. 静音、ASR 失败或识别文本无效时不调用 DeepSeek。
4. ESP32 的 HTTP 上传响应在模型生成之前返回。
5. 固件不改动；音频不发给 DeepSeek，只发送识别文本。

## 5. 实施与验证记录（2026-11-09）

### 5.1 第一阶段：LLM 客户端

新增 `scripts/llm_client.py`：`LLMConfig`、`DeepSeekProvider`、`ChatSession`、
`load_api_key`、`valid_user_text`、`estimate_cost`。命令行支持单轮、交互式
与 `--json` 输出；回合记录默认写 `work/sessions/`。

自动测试 `scripts/test_llm_client.py` 使用本地假 OpenAI 兼容服务器，
**没有产生真实请求**，78 项检查全部通过，覆盖：

- 请求路径 `/chat/completions`、鉴权头、`model`、`max_tokens`、`temperature`、
  `thinking={"type":"disabled"}` 与 system 角色设定；
- 成功响应的文本、延迟、`usage` 与费用；
- `history_turns` 与字符预算裁剪（保留整组 user/assistant）；
- 缺 Key、短 Key、文件权限、环境变量优先级、`repr` 不泄漏 Key；
- HTTP 401/429（含 `Retry-After`）/5xx、读取超时、连接拒绝、非 JSON、
  空 choices、只有 `reasoning_content`；
- 高峰/非高峰费用计算与未知模型；
- 文本有效性（空、纯标点、超长拒绝）；
- 会话记录字段、失败记录与文件中不含 Key；
- 无 Key 时 CLI 返回码 2 且不输出 Key。

### 5.2 第二阶段：接到接收端

`scripts/audio_receiver.py` 新增 `--llm-*` 参数与 `--no-llm`。ASR 成功且文本
有效后，在同一个后台 worker 中调用 `ChatSession.ask()`，终端输出：

```
[chat] user=<识别文本>
[chat] ai=<AI 回答>
[chat] status=success latency_ms=... prompt_tokens=... completion_tokens=...
       total_tokens=... cost_usd=... session=... turn=...
```

HTTP 响应仍在上传校验完成后立即发送。`work/asr/*.json` 的 ASR 记录不受
LLM 失败影响；LLM 回合另写 `work/sessions/chat-<时间>-<随机>-turn-NNN.json`。

`scripts/test_asr_pipeline.py` 扩展了假 LLM 服务器测试，76 项检查通过
（原 39 项 + 新增 37 项）：

- ASR 成功后带识别文本调用一次，请求参数正确，会话记录含 wav、会话 ID、
  延迟、Token、费用；
- 静音与 ASR 失败均不调用 LLM，也不写会话记录；
- 两次成功对话的第二次请求包含上一组 user/assistant（多轮上下文）；
- LLM 延迟 1.5 s 时，上传的 HTTP 响应仍在 1 s 内返回；
- LLM 返回 500 时 ASR 仍为成功，会话记录为 `error/http_5xx`，接收端继续工作。

其余回归：`scripts/test_audio_receiver.py` 30/30 通过；接收端测试固定加
`--no-llm`，并清除子进程的 `DEEPSEEK_API_KEY`，不会误发真实请求。

### 5.3 真实文本调用（2026-11-09，用户授权一次）

用户在自己的终端配置好 `work/deepseek_api_key`（权限 600）后，明确授权一次
真实文本请求。执行命令：

```bash
env -u PYTHONPATH .venv/bin/python scripts/llm_client.py --json "你好，你是谁？"
```

实际结果：

| 项目 | 观察值 |
| --- | --- |
| HTTP 状态 | 200 |
| 模型 / 模式 | `deepseek-flash` / `thinking=disabled` |
| 回复 | “你好呀，我是小桌，住在你桌面机器人里的AI小伙伴，很高兴认识你。” |
| 端到端延迟 | 839.4 ms |
| 输入 Token | 84（缓存命中 0，未命中 84） |
| 输出 Token | 19 |
| 总 Token | 103 |
| 估算费用 | USD 0.000024（非高峰；按 2026-11-09 价格快照） |
| 请求 ID | `d8defea2-0c9f-4c94-9133-4b32db946690` |
| 会话记录 | `work/sessions/chat-20261109-234033-80ef-turn-001.json` |

请求一次成功，没有重试；终端输出与会话记录均未出现 Key。该结果只证明一次
单轮文本调用可用，不代表长期稳定性、限流或网络异常下的表现。按用户授权
范围，未发送第二次付费请求。

### 5.4 端到端真实联调（2026-11-09，用户授权一次）

用户确认开发板上电、录音设备连接后，另行授权一次真实端到端请求。接收端
以 `--once` 启动（`asr=on llm=on`），用户看到 RGB 变绿后说了一句话。实际
链路与观察值：

| 阶段 | 观察结果 |
| --- | --- |
| 录音 | `MIC_RECORD_DONE frames=160000 bytes=320000 crc32=473fcf06` |
| 上传 | `MIC_UPLOAD_DONE ... crc32=473fcf06 attempts=1`；接收端 `ok remote=192.168.31.17 bytes=320000 crc32=473fcf06`，两端 CRC 一致 |
| WAV | `work/audio/mic-20261109-234352.wav`，320,044 字节（含 44 字节 WAV 头） |
| ASR 输入 | 峰值 11.62%、高通 RMS 0.665%、活跃 2,240 ms（10 秒） |
| ASR 结果 | `你好啊你是捉宠吗我是你的主人`，`status=success` |
| ASR 耗时 | 推理 202.3 ms；模型加载 2,685.4 ms；进程总耗时 6,703.3 ms；峰值 RSS 2,241.1 MB |
| AI 回答 | `你好呀主人！我不是捉宠，是小桌，住在你的桌面机器人里陪你聊天的小伙伴。` |
| DeepSeek | HTTP 200、延迟 649.6 ms、输入 89 / 输出 20 / 总 109 Token、估算 USD 0.000025（非高峰） |
| 会话记录 | `work/sessions/chat-20261109-234334-0744-turn-001.json` |

观察到接收端先返回上传成功（`[receiver] ok`），随后才出现 ASR 与 `[chat]`
日志，符合“HTTP 上传响应不等待模型”的设计；没有做毫秒级时序测量。终端
顺序为 `[asr] text=...` → `[chat] user=...` → `[chat] ai=...`。按授权只产生
这一次真实 LLM 请求，`attempts=1`，没有重试；Key 未出现在接收端日志、
串口日志或会话记录中（已用脚本核对）。

ASR 输出中的“捉宠”应为“桌宠”的同音误识别，AI 回答沿用了该词。2026-11-09
用户确认“是这个意思”，即识别文本的语义与实际说话一致；验收依据为用户
确认，ASR 并非逐字转写。据此第二阶段标记为已验收。

另外，当前 Paraformer 峰值 RSS 为 2,241.1 MB，说明原计划中 2 核 2GB 的
阿里云服务器**不能**运行当前本地 ASR，第三阶段必须改用云端 ASR。

### 5.5 未完成 / 未验证

- 第二阶段端到端链路已跑通，用户已确认语义与实际说话一致，已验收；ASR 存在
  同音误识别（“捉宠”/“桌宠”），未要求逐字转写。
- 未接入 TTS；回答只显示在终端。
- 未在阿里云服务器部署，未改 ESP32 固件。
- 未测试 DeepSeek 侧限流、余额不足与网络中断的真实表现（模拟路径已覆盖）。
- 未做多次对话的真实多轮上下文验证；当前真实请求均为单轮。

## 6. 操作步骤

### 6.1 配置 Key（用户自己的终端）

```bash
cd /home/hy/ai-desktop-robot
umask 077
read -rsp 'DeepSeek API key: ' key; echo
printf '%s\n' "$key" > work/deepseek_api_key
unset key
chmod 600 work/deepseek_api_key
```

也可以在当前终端 `export DEEPSEEK_API_KEY=...`；环境变量优先于文件。
Key 不会出现在 Git、日志或会话记录中。

### 6.2 文本单轮 / 交互测试（真实请求，需授权）

```bash
env -u PYTHONPATH .venv/bin/python scripts/llm_client.py "你好，你是谁？"
env -u PYTHONPATH .venv/bin/python scripts/llm_client.py --interactive
```

### 6.3 与实验 013 联调（真实请求，需授权）

```bash
env -u PYTHONPATH .venv/bin/python scripts/audio_receiver.py --once
```

然后在串口发送 `mic record`，按实验 013 的流程说话并 `mic upload`。终端应
依次出现 `[asr] text=...`、`[chat] user=...`、`[chat] ai=...`，会话记录写入
`work/sessions/`。只想验证 ASR 时加 `--no-llm`。

## 7. 风险与边界

- API Key 只在本机；`work/` 被 Git 忽略。仍应避免把含 Key 的终端输出或
  会话目录截图公开。
- 明文 HTTP 音频上传只限可信局域网；DeepSeek 请求走 HTTPS。
- 只发送识别后的文本，不发送音频；文本可能包含隐私内容，调用前用户应知情。
- 费用按 Token 估算；异常重试不自动进行，重复调用需人工决定。
- 多轮上下文会带入之前的文本；默认上限 6 组、4000 字符，超出即丢弃最旧组。
- `deepseek-flash` 默认开启思考模式，本实现显式关闭；若供应商更改参数名，
  需要重新核对文档。
- 当前接收端单 worker，ASR 与 LLM 串行；多次上传会排队。

## 8. 第三阶段：迁移到阿里云的划分

目标形态：ESP32 通过 Wi-Fi 与阿里云 Ubuntu 通信，服务器负责云端 ASR、
DeepSeek 与 TTS，设备只做采集、播放和表情/动作。

| 当前本地模块 | 迁移方式 | 说明 |
| --- | --- | --- |
| `scripts/audio_receiver.py` | 直接迁移为云端入口 | 令牌、长度/CRC 校验、WAV 落盘逻辑复用；需加公网 TLS 与更强鉴权 |
| `scripts/asr_local.py` | 替换为云端 ASR 适配器 | 2GB 服务器不放 Paraformer；保留“单行 JSON + 文本/状态”的接口契约 |
| `scripts/llm_client.py` | 直接复用 | 标准库实现，无本地模型依赖；Key 改为服务器环境变量 |
| TTS（尚未实现） | 新增服务器模块 | 调用云端 TTS，返回音频或 URL；设备端播放 |
| `work/` 会话与音频 | 服务器私有存储 | 需制定保留期限、访问控制与清理策略 |

ESP32 固件本阶段不改；以后需要新增“取回答/音频”的下行通道（HTTP 轮询或
WebSocket）以及播放缓冲，届时单独开实验，不在 014 中混做。

## 9. 下一步

1. **已完成（2026-11-09）：** 用户配置 Key 并授权一次真实文本请求；实际
   HTTP 200、延迟 839.4 ms、103 Token、估算 USD 0.000024，见 5.3。
2. **已完成（2026-11-09）：** 用户单独授权后执行了一次完整的“录音 →
   ASR → DeepSeek”真实联调，终端与 `work/sessions/` 记录完整，见 5.4；
   用户已确认语义一致，第二阶段已验收。
3. 评估 TTS 方案与云端迁移，不在当前阶段实施；当前本地 ASR 峰值内存
   2.2 GB，云端迁移不能沿用。
