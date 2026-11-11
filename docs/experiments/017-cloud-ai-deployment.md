# 实验 017：云端 AI 服务部署

状态：**进行中**（2026-11-11 开始；第一至第三阶段已完成并有实测记录；唤醒反馈与免唤醒追问已由用户验收，见 7.6；最终“关机后台到端对话”验收待用户执行）

## 1. 目标

把目前依赖 Ubuntu 电脑的 AI 链路（ASR → DeepSeek → TTS → 回答存储）迁移到一台
2 核 / 2GB 内存的阿里云 Ubuntu 服务器，使开发电脑关机后，ESP32 仍能完成：

1. 离线唤醒“你好小智”；
2. VAD 变长录音并经 Wi-Fi 上传；
3. 云端 ASR、DeepSeek 对话、TTS；
4. ESP32 取回回答并在扬声器播放。

最终验收时必须真正关闭开发电脑，由用户对桌宠说话并听到回答；断开网络、错误凭据、
超时等场景也要有记录。

## 2. 分阶段与验收标准

| 阶段 | 内容 | 验收标准 | 状态 |
| --- | --- | --- | --- |
| 一 | 云端 ASR Provider，与本地 Paraformer 对比 | 真实 WAV 的识别文本、延迟、费用、错误处理有记录；同音字“小桌/桌宠”单独评估 | 已完成（改为服务器端 SenseVoice；qwen3 对比因无 Key 未执行） |
| 二 | 阿里云服务部署 | systemd 开机自启与自动恢复；协议/turn/CRC 保持；队列、限流、清理与费用控制有效 | 已完成（2026-11-11；证据见第 6 节） |
| 三 | ESP32 安全接入公网 | HTTPS 且校验证书；独立设备凭据；断网恢复；不暴露明文 8080 | 已完成（2026-11-11；证据见第 7 节；断网恢复待最终验收复测） |
| 最终 | 关机后台到端对话 | 关闭开发电脑后三轮对话、断网恢复、错误凭据与超时场景全部通过 | 未开始 |

## 3. 约束与安全规则

- API Key 只保存在服务器端或本机被 Git 忽略的 `work/` 文件中（权限 600），
  不打印、不入库、不写入日志或会话记录。
- ESP32 不持有 DeepSeek、DashScope 或服务器管理凭据；第三阶段另发独立设备令牌。
- 2GB 服务器不部署 Paraformer 等大型本地模型（实验 014 测得峰值 RSS 约 2.24 GB）。
- 明文 HTTP 只允许在可信局域网内做临时验证；不得把现有 8080 直接映射到公网。
- 自动测试只访问本地假服务器；真实付费调用需由实际 WAV 对比或用户操作触发，
  并限制并发、超时与重试。
- 构建、烧录与自动回归期间保持舵机外部 5V 断开。

## 4. 官方接口事实（2026-11-11 核对）

来源：

- <https://help.aliyun.com/zh/model-studio/qwen3-asr-flash>
- <https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference>
- <https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- <https://help.aliyun.com/zh/model-studio/model-pricing>

| 项目 | 结论 |
| --- | --- |
| 模型 | `qwen3-asr-flash`（同步，最长 5 分钟音频） |
| 接入方式 | OpenAI 兼容 `POST {base_url}/chat/completions`；DashScope 同步/异步也可，但本项目先用 OpenAI 兼容 |
| 北京 base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1`（旧域名仍可用；新域名需 WorkspaceId） |
| 鉴权 | `Authorization: Bearer $DASHSCOPE_API_KEY` |
| 音频输入 | `messages[].content[].input_audio.data`，值为 `data:audio/wav;base64,...`；不支持本地路径 |
| 请求限制 | Base64 后 ≤ 10 MB；音频 ≤ 5 分钟；输出不计费 |
| 参数 | `asr_options.language=zh`、`asr_options.enable_itn`（默认 false） |
| 上下文/词表 | 可在 `messages` 首位放 `system` 消息提供背景词表；不支持传统角色提示词 |
| 返回 | `choices[0].message.content` 为文本；`annotations` 含 language/emotion；`usage.seconds` 为计费秒数 |
| 计费（快照） | 北京 0.00022 元/秒；新加坡/美国 0.00026 元/秒；北京另有 36,000 秒免费额度（90 天，以控制台为准） |
| 限流 | 100 RPM |
| 错误码 | 官方页面未给完整表；脚本按 HTTP 401/403/429/4xx/5xx 分类并保留服务端 message |

价格与免费额度是 2026-11-11 快照，只用于估算，不替代账单。

## 5. 第一阶段设计

### 5.1 代码

- 保留 `scripts/asr_local.py` 不变。
- 新增 `scripts/cloud_asr.py`：
  - `CloudASRProvider` 单文件同步识别，输出字段与 `asr_local.py --json` 兼容
    （`status`、`text`、`inference_ms`、`duration_s`），接收端只需替换命令；
  - Key 从 `DASHSCOPE_API_KEY` 或 `work/dashscope_api_key` 读取，日志/记录/错误信息
    都不含 Key；
  - 只接受 16 kHz / 16 bit / 单声道 WAV，与现有固件录音一致；本地先校验时长与
    Base64 体积，超限不发起请求；
  - 429/5xx/网络错误最多重试 1 次（可用 `--retries 0` 关闭），401/403/400 不重试；
  - 记录请求延迟、音频时长、`usage.seconds`、请求 ID 与费用估算。
- 新增 `scripts/test_cloud_asr.py`：本地假服务器验证请求体、Data URI、system 词表、
  响应解析、费用、错误脱敏与重试上限，**不访问真实服务**。

### 5.2 对比样本

复用实验 013–016 保存在 `work/audio/` 的真实 WAV 与 `work/asr/` 的本地 ASR 结果。
重点样本：

| WAV | 本地 ASR 文本 | 关注点 |
| --- | --- | --- |
| `mic-20261109-234352.wav` | 你好啊你是捉宠吗我是你的主人 | “捉宠/桌宠”同音 |
| `mic-20261110-083021.wav` | 小卓你好给我一句鼓励的话比如说今天我很棒呀 | “小卓/小桌”同音 |
| `mic-20261111-001159.wav` | 你知道现在的时间吗 | 实验 016 实机对话 |
| `mic-20261111-001327.wav` | 给我讲个笑话 | 实验 016 实机对话 |
| `mic-20261111-001352.wav` | 你刚刚说了什么 | 实验 016 实机对话 |
| `mic-20261110-225900.wav` | 今天天气怎么样 | VAD 短录音（2.91 s） |
| `mic-20261110-230353.wav` | 我今天上班了然后下班玩游戏然后还去修车了 | 长句（7.14 s） |
| `mic-20261110-230738.wav` | 一二三四五六七八九十十一十二十三 | 数字与 ITN |
| `mic-20261108-203520.wav` | 开始记录这是一个AI测试的测试我正在说话 | 实验 013 长录音 |
| `mic-20261109-230828.wav` | 这是一个AI测试你能听到吗我正在讲话 | 实验 013 长录音 |

评估项：文本与用户确认语义的一致性、同音字（尤其“小桌/桌宠”）、请求延迟、
音频秒数与估算费用、错误处理。两组调用：不带词表；带
`--context "小桌,桌宠,小智"` 的 system 词表。

### 5.3 本地测试结果

`.venv/bin/python scripts/test_cloud_asr.py` → **PASS: 59/59 checks**（2026-11-11）。
覆盖 Key 读取/权限/缺失、WAV 校验、请求体与 Data URI、system 词表、响应解析、
北京/新加坡费用、401/403/400/429/5xx、重试上限、错误脱敏与 `--json` CLI。

真实 API 对比未执行：本机与当前环境都没有百炼 Key。用户明确没有百炼 API，并选择
先在 2GB 服务器上试用轻量 SenseVoice，而不是注册新的云端 ASR。`cloud_asr.py`
保留为以后可选方案与对比工具。

### 5.4 服务器端 SenseVoice 实测（2026-11-11）

改用 sherpa-onnx 2.0.1 + `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`
的 int8 ONNX 模型（229 MB），不部署 Paraformer。新增
`scripts/asr_sensevoice.py`，CLI 与 JSON 字段兼容 `asr_local.py --json`。

本机与服务器（Aliyun Ubuntu 22.04，2 核，1.6 GB 可用，无 swap）结果：

| 项目 | 本机 | 服务器 |
| --- | --- | --- |
| 13 段 WAV 全部成功 | 是 | 是 |
| 峰值 RSS | 372.6 MB | 371.6 MB |
| 模型加载 | 约 0.75 s | 约 1.07 s |
| 2.5–10 s 音频推理 | 100–360 ms | 184–750 ms |
| 13 段（95 s 音频）总耗时 | 4.35 s | 7.79 s |
| CPU 用户态时间（整批） | 未单独记录 | 13.79 s（2 线程） |

识别文本与本地 Paraformer 逐段一致，只多了 `AI` 写作 `ai` 的空格；服务器上一段
重复唤醒词把“小智”识别成“小志”。同音字问题复现：

- `小卓你好…`（实际应为“小桌”）
- `你好啊你是捉宠吗…`（实际应为“桌宠”）

SenseVoice 不支持 system 词表/热词，因此计划在 ASR 之后、DeepSeek 之前加一个
范围很小的领域纠错表（`小卓→小桌`、`捉宠→桌宠`），并对每次纠正留日志；该纠错
尚未实现，不能把识别准确率写成已改善。

服务器目录（不在仓库）：

```
/home/admin/robot/scripts/asr_sensevoice.py
/home/admin/robot/models/sensevoice/model.int8.onnx
/home/admin/robot/models/sensevoice/tokens.txt
/home/admin/sensevoice-venv/        # sherpa-onnx 2.0.1
```

## 6. 第二阶段：服务器部署与运行控制（2026-11-11）

### 6.1 运行环境

- 服务器是阿里云**轻量应用服务器**（不是 ECS，入站规则在控制台的“防火墙”页，
  没有“安全组”）。Ubuntu 22.04，2 核，系统可用内存约 1.6 GB，无 swap，
  公网 IP `47.97.65.217`，登录用户 `admin`。
- `/home/admin/robot/` 保存接收端脚本与 `work/` 数据；`/home/admin/sensevoice-venv`
  是独立虚拟环境（sherpa-onnx 2.0.1），模型在
  `/home/admin/robot/models/sensevoice/`（`model.int8.onnx` 229 MB + `tokens.txt`）。
  本地 Paraformer（峰值 RSS 2.24 GB）没有部署。
- 接收端协议未变：仍是 `POST /upload` + `X-Auth-Token` + 二进制 PCM + `X-Frames` +
  `X-Crc32`，成功响应带 `turn=`；`GET /reply/latest?turn=` 取回回答。ASR 通过
  `--asr-script scripts/asr_sensevoice.py` 替换为服务器端 SenseVoice，异步队列、
  回答存储与下载逻辑复用实验 013–016 的实现。
- `scripts/cloud_asr.py`（百炼 `qwen3-asr-flash`）保留为可替换 Provider，因没有
  百炼 Key，未做真实调用与文本对比，见 5.3。
- 同音字纠错：`scripts/asr_corrections.py` 在 ASR 成功后、调用 DeepSeek 前替换两条
  固定规则 `小卓→小桌`、`捉宠→桌宠`，每次纠正打印 `[asr] corrected rules=...`。
  这是领域词表，不是通用纠错；规则只在实际录到过错误时增加。本地测试 12/12。

### 6.2 systemd 服务

`robot-receiver.service`（安装到 `/etc/systemd/system/`，已 `enable`）：

- `Restart=always`、`RestartSec=5`，`StartLimitIntervalSec=60` / `StartLimitBurst=5`；
  `KillMode=mixed`、`TimeoutStopSec=20`；
- `MemoryHigh=1000M`、`MemoryMax=1200M`、`TasksMax=64`，防止 2 GB 机器被拖垮；
  `NoNewPrivileges=true`、`PrivateTmp=true`、`ProtectSystem=full`；
- 只监听 `127.0.0.1:8080`，参数含 `--asr-queue 2 --asr-timeout 60`、
  `--rate-limit-per-minute 10 --daily-upload-limit 200 --usage-file work/usage.json`。
- 已验证：服务器重启后服务自动运行；`kill -9` 后约 5 秒由 systemd 拉起并继续服务。

2026-11-11 23:20 左右实测：进程 `MemoryCurrent=300269568`（约 286 MB），
`NRestarts=0`；整机内存 1608 MB、已用 343 MB、可用 1099 MB。

### 6.3 上传限额与费用控制

`scripts/upload_limits.py` 在接收端读请求体之前执行：

- 每个来源 IP 在 60 秒滑动窗口内最多 10 次上传；
- 每日全局最多 200 次上传，计数写入 `work/usage.json`（`{"date":"...","count":N}`），
  进程重启后保持，跨日自动归零；
- 状态文件损坏或不可写时 fail-closed：返回 503 `ERR usage_state` 并记录，
  不静默放行；
- `X-Real-IP` 只在直连来源是回环地址（即 nginx）时才可信，其他来源忽略该头，
  防止伪造绕过按 IP 限流；
- 超限返回 429，且不写 WAV、不触发 ASR/LLM/TTS。

费用上限估算：200 次/天最坏情况约 USD 0.005/天（DeepSeek 单轮约 100 Token，
`deepseek-flash` 非高峰价），Edge TTS 免费。2026-11-11 当日 `usage.json` 计数为 2。

### 6.4 录音与会话清理

`scripts/cleanup_work.py` + `robot-cleanup.service/.timer`：

| 目录 | 匹配 | 保留 |
| --- | --- | --- |
| `work/audio/` | `*.wav` | 2 天 |
| `work/asr/` | `*.json` | 7 天 |
| `work/sessions/` | `*.json` | 30 天 |
| `work/replies/` | `reply-*` | 2 天 |
| `work/tts/` | `*.pcm`、`*.wav` | 2 天 |

定时器为 `OnCalendar=*-*-* 04:30:00 Asia/Shanghai`、`RandomizedDelaySec=300`、
`Persistent=true`；删除后如果 `replies/latest.json` 指向已删除文件会同步修复。
脚本只处理上述已知目录、跳过符号链接，支持 `--dry-run`。2026-11-11 22:45
定时器首次运行，下一次 2026-11-12 04:30。

## 7. 第三阶段：ESP32 经 HTTPS 接入公网（2026-11-11）

### 7.1 拓扑与端口

```
ESP32 --TLS 1.2/1.3--> 47.97.65.217:443 (nginx)
                        ├── /health        → 127.0.0.1:8080
                        ├── /upload        → 127.0.0.1:8080
                        └── /reply/latest  → 127.0.0.1:8080
                        其他路径 → 404
接收端只绑定 127.0.0.1:8080，公网不开放 8080。
```

- 阿里云轻量应用服务器在“防火墙”页添加入站 TCP 443（授权对象 `0.0.0.0/0`）；
  8080 从未放行。用户添加规则后，开发机 `curl --cacert work/tls-ca.crt
  https://47.97.65.217/health` 返回 200（0.033 s）。
- nginx 1.18 终止 TLS：`ssl_protocols TLSv1.2 TLSv1.3`、`client_max_body_size 320k`、
  代理超时 3/15/60 秒，并设置 `X-Real-IP $remote_addr`；只放行三个精确路径，
  其余 `return 404`。实测协商为 TLSv1.3 / `TLS_AES_256_GCM_SHA384`。

### 7.2 证书与 ESP32 校验证书

- 服务器上自建 ECDSA P-256 本地 CA（`/etc/robot-tls/ca.crt`，有效期至
  2036-11-08），服务器证书 `CN=robot-cloud`，SAN 同时包含
  `DNS:robot-cloud`、`DNS:localhost`、`DNS:47.97.65.217`、`IP:47.97.65.217`、
  `IP:127.0.0.1`。
- 固件用 `WiFiClientSecure::setCACert` 只信任内置 CA，**不使用 `setInsecure`**；
  CA 是公开信息，可以编进固件，私钥只在服务器。
- 两个实测踩到并修正的问题：
  1. mbedTLS 2.x 不校验 IP 类型的 SAN，而 `connect(IPAddress, port)` 把 IP 字符串
     当主机名使用，证书必须同时带 `DNS:<IP 字面量>` 与 `IP:<IP>`，否则恒为
     `X509 - Certificate verification failed, code=-9984`；
  2. ESP32 上电时钟是 1970 年，证书被判“尚未生效”。固件在 Wi-Fi 连接后启动 SNTP
     （`ntp.aliyun.com`、`ntp.ntsc.ac.cn`、`pool.ntp.org`），打印
     `TIME_SNTP_START` 与 `TIME_SYNCED epoch=...` 后再使用 HTTPS。

### 7.3 固件改动

- `src/audio_uploader.*` 与 `src/voice_receiver.*` 的 `begin()` 增加可选 CA 参数；
  CA 为空时保持原明文 HTTP 行为（仅局域网调试），非空时启用 `WiFiClientSecure`。
- TLS 连接超时 4 秒、写超时 1 秒；连接失败打印 `TLS_ERROR code=... detail=...`，
  上传失败沿用 3 次重试与 `ERR mic_upload_failed reason=...`。
- 上传/下载协议、头字段、`turn`、CRC-32 与非阻塞状态机均未改变。
- 设备令牌仍是独立的 32 位十六进制值（`AUDIO_UPLOAD_TOKEN`），与 DeepSeek、
  DashScope 的 Key 不同；服务器端 `work/audio_upload_token` 权限 600，
  只有接收端读取，日志不打印令牌。

### 7.4 实测记录

| 项目 | 结果 |
| --- | --- |
| 三环境构建 | `diagnostics`、`rgb_gpio48`、`rgb_gpio38` 全部 SUCCESS |
| 烧录 | 1,304,352 字节，`Hash of data verified` |
| 启动配置 | `UPLOAD_CONFIG ... port=443 tls=1`、`VOICE_CONFIG ... tls=1` |
| SNTP | `TIME_SYNCED epoch=1794409933` |
| 局域网 TLS 联调 | 本机 TLS 代理 8443 → 127.0.0.1:8080；上传 `attempts=1`，下载 `VOICE_READY bytes=32000 crc32=6d4fb8e9` |
| 公网 HTTPS 上传 | 320,000 字节、CRC `9a625788`、`attempts=1`、`turn=20261111-231241-02`；服务器记录来源 IP `39.180.173.62` |
| 静音处理 | 该轮 `active_ms=10`，ASR 判 `reason=silent`，未调用 LLM/TTS，无费用 |
| 公网 HTTPS 下载 | 208,280 字节、104,140 帧、6,508 ms、CRC `e3327c0a`（取回最近一条回答；本次静音上传没有对应回答） |
| 完整串口回归 | **1240 项通过**（`work/test_serial_017.log`，外部 5V 断开；含 Wi-Fi/HTTP，回归不发起真实上传、TTS 或回答下载） |

### 7.5 失败场景实测

两个场景都用临时固件完成，测试后已恢复正式配置并重新烧录（1,304,352 字节，
启动 `tls=1` 与 `TIME_SYNCED` 正常）。

| 场景 | 方法 | 结果 |
| --- | --- | --- |
| 错误设备令牌 | 把 `AUDIO_UPLOAD_TOKEN` 临时改为全零，其余配置不变，录音后 `mic upload` | 固件 `MIC_UPLOAD_FAILED reason=rejected attempts=1`，耗时 2.2 秒；服务器 `reject invalid_token remote=39.180.173.62`，未写 WAV |
| 服务器不可达 | 把 `AUDIO_UPLOAD_HOST` 临时改为 TEST-NET-1 的 `192.0.2.1`（黑洞地址） | 每次连接 4 秒超时，`TLS_ERROR code=-1` ×3、`MIC_UPLOAD_RETRY attempt=2/3`，12.1 秒后 `ERR mic_upload_failed reason=tls attempts=3`，无无限重试 |
| 无令牌 / 错令牌（主机侧） | `curl` 直接请求公网 `/upload` | `401 ERR missing_token`、`403 ERR invalid_token` |
| 非接口路径 | `curl https://47.97.65.217/` | 404；8080 端口公网不可达 |

### 7.6 唤醒反馈与免唤醒追问（固件 UX 修正，2026-11-11）

用户试用反馈：说“你好小智”后设备没有任何提示，继续说话却能触发回应；而且每句话
都要重新说唤醒词不自然。排查确认唤醒本身正常（检出后 300 ms 忽略尾音，VAD 检测到
语音即开始录音），问题在交互反馈与等待窗口：

| 问题 | 修正 |
| --- | --- |
| 唤醒后没有反馈 | 检出唤醒词后立即 RGB 蓝闪 250 ms + 眨眼一次，打印 `WAKE_CUE kind=wake`。提示只用视觉，避免提示音被麦克风录进上传音频 |
| 停顿稍久就放弃 | 唤醒后无语音等待由 5 秒延长到 **10 秒**（`kNoSpeechUs`），超时仍打印 `WAKE_RECORD_ABORT reason=no_speech` |
| 每句都要唤醒词 | 每轮回答播放结束、经过 1.2 秒半双工冷却后自动打开 **10 秒免唤醒追问窗口**；蓝闪提示后可直接说下一句 |
| 避免无限对话与费用 | 一次唤醒最多 **3 轮**追问（`wake followup <0-5>` 可调），预算按实际打开的窗口计数；只有新的唤醒词才重置 |

`src/wake_engine.*`：新增 `requestFollowUp(windowMs)`、`followUpActive()`、
`listenCount()`、`followUpCount()`。请求只接受 `idle` 且未屏蔽的状态，由 fetch
任务在 `WAKE_FOLLOWUP_LISTEN window_ms=...` 后把状态切到 `kArming` 并置
`followUpActive_`；窗口内 VAD 检测到语音立即开始录音（0.5 秒预录仍有效），
`WAKE_SPEECH_START ... followup=1`。超时使用 `followUpWindowUs_`，打印
`WAKE_FOLLOWUP_END reason=timeout`。窗口已打开时再说唤醒词会重开窗口
（`WAKE_REARM`）并重置轮数；半双工屏蔽逻辑不变。

`src/main.cpp`：`updateWakeCue()` 消费 `listenCount()` / `followUpCount()` 的变化；
`updateWakeFollowUp()` 在唤醒路径上传成功并拿到 `turn` 后置 `wakeTurnPending`，
等上传、下载、播放全部结束且 `suppressed=0` 后调用 `requestFollowUp(10000)`，
日志 `WAKE_FOLLOWUP_OPEN remaining=N`。没有 `turn` 时打印
`WAKE_SESSION_END reason=no_turn`，达到上限打印 `reason=max_followups`。
`wake status` 追加 `WAKE_SESSION max_followups= remaining= turn_pending= window_ms=`。

调试中发现并修复一个启动缺陷：开机自动启动走的是 `wakeEngine.start()`，没有经过
`resetWakeDialogState()`，追问预算保持初值 0，回答后永远不会开窗（串口实测
`wake followup` 返回 `remaining=0`）。现在 `setup()` 在自动启动前调用
`resetWakeDialogState()`，预算初值也改为 3。

验证：三环境构建通过；`rgb_gpio48` 烧录 1,306,592 字节，四次写入均
`Hash of data verified`；完整串口回归 **1242 项通过**（`work/test_serial_017e.log`，
外部 5V 断开）。

**实物验收（2026-11-11，用户观察 + 串口与服务器日志）**：用户说一次“你好小智”，
连续完成 **4 轮**对话后会话按设计结束，用户确认“符合设计”。串口
`work/wake_ux_test.log` 记录：

| 轮次 | 关键日志 | 结果 |
| --- | --- | --- |
| 1 | `WAKE_CUE kind=wake listens=1 blink=1 followups_left=3`；`WAKE_SPEECH_START after_ms=4592 followup=0` | 蓝闪 + 眨眼；录音 78,720 字节，上传 `attempts=1`，`turn=20261111-235610-06` |
| 追问 1 | `WAKE_FOLLOWUP_OPEN remaining=2`、`WAKE_CUE kind=followup blink=1`、`WAKE_SPEECH_START after_ms=7329 followup=1` | 62,400 字节，`turn=20261111-235631-07` |
| 追问 2 | `remaining=1`，`after_ms=1854 followup=1` | 64,320 字节，`turn=20261111-235645-08` |
| 追问 3 | `remaining=0`，`after_ms=1377 followup=1`，随后 `WAKE_SESSION_END reason=max_followups` | 68,800 字节，`turn=20261111-235659-09` |

四轮均在窗口内 1.4–7.3 秒开始说话，上传全部 `attempts=1`、CRC 一致，四段回答
（161,616 / 98,578 / 93,558 / 172,736 字节）均取回并播放。期间两次额外唤醒词被
正确忽略：录音中 `WAKE_IGNORED reason=record_recording`，播放冷却中
`WAKE_IGNORED reason=half_duplex`。

服务器记录：ASR `inference_ms` 157.2–200.0；DeepSeek 866.9–1445.3 ms
（Token 199/219/237/236，四轮合计约 USD 0.000161）；Edge TTS
1544.3–2312.1 ms、`cost_cny=0`。该时段服务器采样 51 点：CPU 平均 12.3%、
峰值 97%（SenseVoice 推理瞬时尖峰），内存平均 445 MB、峰值 732 MB，未触及
1000M 软限制。ASR 把“你好小智”识别为“你好小志”时未加纠错规则，DeepSeek 仍
自然回应；“你好小卓”由既有规则纠正为“你好小桌”。

## 8. 测试汇总（2026-11-11）

| 测试 | 结果 |
| --- | --- |
| `scripts/test_cloud_asr.py` | 59/59 |
| `scripts/test_asr_corrections.py` | 12/12 |
| `scripts/test_upload_limits.py` | 29/29 |
| `scripts/test_receiver_limits.py` | 27/27 |
| `scripts/test_cleanup_work.py` | 19/19 |
| `scripts/test_audio_receiver.py` | 44/44 |
| `scripts/test_asr_pipeline.py` | 76/76 |
| `scripts/test_serial_wifi.py` | 1242/1242（`work/test_serial_017e.log`；新增 `wake followup` 与 `WAKE_SESSION` 检查） |

自动测试不访问真实云端 ASR、不发起付费调用。

## 9. 验收状态与未验证项

- 第一至第三阶段已完成：服务器运行 SenseVoice + DeepSeek + Edge TTS，systemd
  自启与恢复、限额、清理、HTTPS 与证书校验均有实测记录。
- 交互层面已验收（2026-11-11）：唤醒即时蓝闪 + 眨眼、无语音等待 10 秒、回答后
  免唤醒追问最多 3 轮均已由用户观察确认，串口与服务器日志见 7.6；证据为用户
  观察与日志，未做多距离/多噪声条件下的统计。
- **最终验收尚未完成**：要求关闭开发电脑后，用户说“你好小智”并提问，连续三轮
  听到回答，并记录端到端时延、费用与服务器内存/CPU。
- 错误令牌与服务器不可达的超时表现已在设备侧实测（见 7.5），不会无限重试。
- 尚待实测：Wi-Fi/公网断线后的自动恢复；三轮对话的端到端时延统计与服务器
  CPU/内存采样。
- 仍未验证：SenseVoice 的噪声/远场识别率，AEC 与回声误唤醒，“小桌小桌”自定义
  唤醒词（需 Espressif 定制或自训练），qwen3-asr-flash 真实对比（无 Key）。

## 10. 下一步

1. 用户关闭开发电脑，在家庭 Wi-Fi 下完成三轮唤醒对话；
2. 重新开机后从服务器 `journalctl -u robot-receiver` 提取三轮的 ASR/LLM/TTS
   延迟、Token 与费用，记录服务器内存与 CPU；
3. 在验收过程中做一次断网恢复与一次错误凭据/超时场景；
4. 汇总后更新本文档、`docs/progress.md`、`README.md` 与 `AGENTS.md`，再按用户授权提交。

（唤醒反馈与免唤醒追问已于 2026-11-11 单独完成实物验收，见 7.6。）
