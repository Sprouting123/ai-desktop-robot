# 实验 013：ESP32-S3 Wi-Fi 无线音频传输

- 状态：**已验收**（2026-11-08：三环境构建、烧录校验、1198 项回归与接收端 30/30 本地测试通过；真实上传先后暴露并修复 `availableForWrite()` 恒为 0 与成功响应解析要求字段连续两个缺陷，最终固件一次上传成功；用户试听确认句尾清楚）
- 日期：2026-11-08（Asia/Shanghai）
- 前置实验：[012 10 秒麦克风录音](012-10s-recording.md)、[011 本地中文语音识别](011-asr.md)、[010 INMP441 麦克风采集与录音](010-microphone.md)、[008 Wi-Fi 联网与局域网控制](008-wifi-control.md)

## 1. 目标与范围

把 ESP32-S3 已录好的 10 秒、16 kHz、16 bit、单声道 PCM（160,000 帧、
320,000 字节）经家庭局域网直接上传到 Ubuntu，由接收服务校验后保存为 WAV。
第一阶段只做**安全、可靠的无线传输**；验收通过后，第二阶段再在主机侧自动
调用现有 `scripts/asr_local.py` 完成识别。

本阶段：

- 复用实验 012 的 320,000 字节 PSRAM 录音缓冲与固件 CRC-32，不重新录音、
  不复制整段音频；
- ESP32 作为 HTTP 客户端；Ubuntu 新增轻量接收服务，使用 **8080** 端口，
  不占用 ESP32 已有的 80 端口网页服务；
- 只有显式输入 `mic upload` 才发送；上电不录音、不连接接收端、不上传；
- 音频以二进制 PCM 传输，不走串口十六进制 dump，不使用 Base64；
- 不调用付费 API、不部署云服务器、不新增硬件。

## 2. 硬件与网络

接线与实验 010/012 相同，不新增模块：

| 项目 | 值 |
| --- | --- |
| 麦克风 | INMP441：VDD → 3V3、GND → GND、SCK → GPIO16、WS → GPIO17、SD → GPIO18、L/R → GND |
| 录音 | 160,000 帧 / 320,000 字节 / 16 kHz / 16 bit / 单声道 |
| ESP32 网络 | 家庭 2.4 GHz Wi-Fi，STA；本次回归时 DHCP 地址 `192.168.31.17` |
| Ubuntu 接收端 | `192.168.31.29:8080`（本次 DHCP 地址；重启或换网后可能变化） |
| 端口 | 接收服务 8080；ESP32 网页仍为 80，两者不冲突 |

开发、构建、烧录与自动回归期间外部 5V 保持断开；麦克风只用 3V3。上传过程
本身不驱动舵机或功放。

## 3. 设计

### 3.1 固件：`src/audio_uploader.*`

新增 `upload::Client`，只读取 `mic::Engine` 已完成的录音缓冲：

- 新命令 `mic upload`、`mic upload status`、`mic upload cancel`；
- 只有在 `record=ready` 时才能开始；录音中返回 `ERR mic_recording`，
  dump 中返回 `ERR mic_dump_busy`，没有录音返回 `ERR mic_no_recording`；
- 上传期间拒绝 `mic start/record/dump/upload`（`ERR mic_upload_busy`），
  `mic stop` 取消上传但保留已完成录音；
- 每轮 `loop()` 最多发送一小块（≤1024 字节），直接对 socket 用
  `MSG_DONTWAIT` 非阻塞发送，不做整段写、不等待；Arduino-ESP32 2.0.17
  的 `WiFiClient` 没有实现 `availableForWrite()`（继承版本恒为 0），
  不能用于判断发送空间；
- 唯一的阻塞步骤是 TCP connect，超时上限 **1000 ms**；其余超时与重试都在
  状态机中推进；
- 每次上传最多 **3 次尝试**，连接失败、超时、连接中断、写入失败时重试；
  每次重试都从偏移 0 重新发送当前录音，录音缓冲不被修改；
- 卡住判定：5000 ms 无进展；响应等待 5000 ms；
- 成功响应必须同时包含 HTTP 200、`OK `、`bytes=320000` 与
  `crc32=<本地 CRC>`；这些字段在响应中不要求相邻（见 5.4）；
- 日志只打印主机、端口、字节数、CRC 和状态，**不打印令牌**。

状态：`idle → connecting → header → body → response → done`，失败为
`failed`，重试等待为 `retry_wait`。`mic upload status` 输出
`UPLOAD state=... configured=... bytes=... sent=... crc32=... attempts=...
host=... port=...`。

### 3.2 上传协议

```
POST /upload HTTP/1.1
Host: 192.168.31.29:8080
X-Auth-Token: <AUDIO_UPLOAD_TOKEN>
Content-Type: application/octet-stream
Content-Length: 320000
X-Audio-Format: s16le
X-Sample-Rate: 16000
X-Channels: 1
X-Frames: 160000
X-Crc32: <8 位小写十六进制>

<320,000 字节 PCM 原始字节>
```

成功响应：

```
HTTP/1.1 200 OK
OK bytes=320000 frames=160000 crc32=<crc> file=mic-YYYYmmdd-HHMMSS.wav
```

拒绝时返回 401（缺令牌）、403（令牌错误）、400（长度/格式错误）、422（CRC
不符）、408（请求体读取超时）、413（长度过大）、404/405（路径或方法错误）。
固件把任何非 200 或 CRC 不匹配的响应视为失败，不重试已收到的明确拒绝。

### 3.3 Ubuntu 接收端：`scripts/audio_receiver.py`

- 只依赖 Python 标准库（`http.server`、`wave`、`zlib`、`hmac`）；
- 默认监听 `0.0.0.0:8080`，仅限可信家庭局域网；
- 令牌从 `work/audio_upload_token` 读取（16–64 个可打印 ASCII 字符），
  使用 `hmac.compare_digest` 比较；HTTP 头缺失返回 401，错误返回 403；
- 校验 `Content-Length` 必须为 320,000，`Content-Type`、
  `X-Audio-Format`、`X-Sample-Rate`、`X-Channels`、`X-Frames` 必须与约定
  一致，`X-Crc32` 必须为 8 位十六进制；
- 请求头解析与请求体读取都设置 10 秒超时（`--header-timeout` 可调）；
  只连接不发送的客户端会被关闭，不会占住单线程服务；读到的字节数不足即拒绝；
- 用 `zlib.crc32` 重新计算并核对；任一校验失败都**不写文件**；
- 校验通过后先写临时文件，再用 `os.replace` 原子改名；
  输出 `work/audio/mic-YYYYmmdd-HHMMSS.wav`，同名时追加序号；
- 日志不包含令牌；`--once` 或 `--max-uploads N` 可在验收后自动退出；
- `GET /health` 返回 `OK`，`GET /upload` 返回 405，便于排查。

### 3.4 配置与保密

- `src/secrets.example.h` 新增 `AUDIO_UPLOAD_HOST/PORT/PATH/TOKEN` 模板；
- 实际值只写入本机 `src/secrets.h`（`.gitignore` 已忽略）；
- 接收端令牌文件 `work/audio_upload_token` 权限 600，`work/` 被 Git 忽略；
- 令牌与 `API_TOKEN` 分开；令牌不进入 URL、串口日志或 HTTP 响应；
- WAV 输出目录 `work/audio/` 被 Git 忽略；
- 明文 HTTP 只允许在可信局域网使用，禁止公网端口映射或不受控 AP。

## 4. 验收标准

1. 三环境构建通过；GPIO48 烧录并校验通过；启动日志出现
   `[experiment 013] Wi-Fi audio upload / Arduino` 和
   `UPLOAD_CONFIG configured=1`。
2. 完整串口/HTTP 回归通过，外部 5V 断开；新增 `mic upload` 的拒绝路径
   不触发真实网络请求。
3. 接收端本地测试通过：合法上传生成 WAV；缺令牌、错令牌、长度错误、
   格式错误、CRC 错误、请求体截断都不生成 WAV。
4. 用户明确触发一次真实上传：`mic record` 完成后再 `mic upload`，
   ESP32 打印 `MIC_UPLOAD_DONE`，接收端保存 WAV，两边 CRC 一致。
5. 上传期间 OLED、动作/舵机与音频播放不被长时间阻塞。
6. 用户试听 WAV，并用现有 `asr_local.py` 识别，文本与实际说话一致。
7. 未完成第 4–6 项前，状态保持“待实物验收”。

## 5. 实施与验证记录（2026-11-08）

### 5.1 固件与构建

新增 `src/audio_uploader.h/.cpp`；`microphone_engine.h` 增加只读访问
`recordedData()` 与 `sampleRate()`；`main.cpp` 增加 `mic upload` 系列命令、
启动日志与 `loop()` 中的单步 `update()`。

| 环境 | Flash | 静态 RAM |
| --- | --- | --- |
| `diagnostics` | 920,245 字节 | 55,244 字节 |
| `rgb_gpio48` | 923,625 字节 | 55,300 字节 |
| `rgb_gpio38` | 923,617 字节 | 55,300 字节（与 GPIO48 同一代码，仅 LED 引脚不同） |

GPIO48 烧录 923,984 字节，输出 `Hash of data verified`。首次实现版本为
923,744 字节；两次缺陷修复（5.4）都改变了上传代码，以上为第二次修复后的
最终数字，固件启动标记与 `UPLOAD_CONFIG` 已在实机日志中核对。

### 5.2 串口与 HTTP 回归

外部 5V 断开，Wi-Fi 已连接（设备地址 `192.168.31.17`），运行：

```bash
env -u PYTHONPATH .venv/bin/python scripts/test_serial_wifi.py
```

结果 **1198 项通过**（实验 012 为 1188 项，新增 10 项上传相关检查）：

- 无录音时 `mic upload` → `ERR mic_no_recording`；
- `mic upload status` 为 `state=idle`，已完成录音后报告
  `bytes=320000` 与录音 CRC；
- `mic upload cancel` 空闲时返回 `OK upload=idle`；
- 录音中 `mic upload` → `ERR mic_recording`；
- 未知子命令 → `ERR mic_usage; use help`；
- 启动日志 `UPLOAD_CONFIG configured=1 host=192.168.31.29 port=8080 path=/upload`，
  未打印令牌。

回归日志在本机 `work/test_serial_013.log`（首次实现）、
`work/test_serial_013b.log`（第一次修复后）与 `work/test_serial_013c.log`
（第二次修复后，1198 项），均被 Git 忽略。回归**没有**触发真实上传，
符合“真实录音上传由用户明确触发”的约束。

### 5.3 接收端本地测试

```bash
env -u PYTHONPATH python3 scripts/test_audio_receiver.py
```

在 `127.0.0.1` 临时端口上启动接收服务，使用 320,000 字节确定性测试数据：

- **30/30 项通过**；
- 合法上传返回 200，生成 1 个 WAV（16 kHz、16 bit、单声道、160,000 帧），
  解码后的 payload 与发送数据 SHA-256 完全一致，CRC 均为 `9dbfade4`；
- 缺令牌 401、错令牌 403、长度错误 400、采样率错误 400、CRC 错误 422、
  内容被篡改 422、请求体截断 400、错误路径 404、`GET /upload` 405；
- 只连接不发送的客户端在请求头超时后被关闭，不产生 WAV，之后的服务仍能
  正常接收合法上传（对应 5.4 的修复）；
- 所有拒绝路径后输出目录中 **0 个 WAV**，也没有临时文件残留。

### 5.4 实物上传暴露的两个缺陷与修复（2026-11-08）

**第一次尝试：`stall`。** 用户执行 `mic record`（CRC `ab425206`）后发送
`mic upload`，三次尝试都在 5 秒后以 `reason=stall` 失败，没有收到 200；
接收端同时被一个“只连接、不发送”的客户端占住。

定位结果：

- Arduino-ESP32 2.0.17 的 `WiFiClient` 没有实现 `availableForWrite()`，
  继承的 `Print::availableForWrite()` **恒返回 0**；固件因此认为发送缓冲区
  永远已满，连接建立后一个字节也没有写出，接收端一直等待请求头；
- 接收端原先只在解析完请求头后才设置 socket 超时，空连接会无限等待，
  单线程服务无法处理后续重试。

修复：

- 上传端改为对 socket 直接调用 `::send(fd, ..., MSG_DONTWAIT)`，与
  `web_server.cpp` 的响应发送方式一致；部分写入按返回值推进，
  `EAGAIN/EWOULDBLOCK` 留到下一轮，其他错误进入重试；
- 接收端在 `setup()` 设置请求头超时，默认 10 秒，可用
  `--header-timeout` 调整；新增“静默连接超时后被关闭且之后仍能合法上传”
  的本地测试。

修复后三环境构建通过（`rgb_gpio48` Flash 923,617 字节、静态 RAM 55,300
字节；`diagnostics` 920,237 / 55,244），烧录 923,984 字节并输出
`Hash of data verified`，完整回归 **1198 项通过**（`work/test_serial_013b.log`）。
本次失败**没有生成 WAV**；录音仍在设备 RAM 中，修复后可直接重试上传。

**第二次尝试：`bad_response`。** 用户重新执行 `mic record`（CRC
`fdfbf19b`）后发送 `mic upload`，约 0.7 秒内传完 320,000 字节，接收端打印：

```
[receiver] ok remote=192.168.31.17 bytes=320000 crc32=fdfbf19b file=mic-20261108-202103.wav count=1
```

并保存了 320,000 字节、160,000 帧的 WAV，CRC 与固件一致；对该文件运行
`scripts/asr_local.py` 得到 `hello hello这是一个AI测试你在听吗`。但 ESP32 侧却打印
`MIC_UPLOAD_FAILED reason=bad_response attempts=1` 与
`ERR mic_upload_failed reason=bad_response attempts=1`。

定位结果：固件要求成功响应中出现连续的
`OK bytes=320000 crc32=fdfbf19b`，而接收端实际响应的正文是
`OK bytes=320000 frames=160000 crc32=fdfbf19b file=...`，中间多了
`frames=` 字段，因此 `strstr` 找不到整段字符串。传输和校验本身已经成功，
只是客户端把成功响应判成了失败（一次假阴性）。

修复：`src/audio_uploader.cpp` 新增 `responseMatches()`，分别查找
` 200 `、`OK `、`bytes=<本地字节数>` 与 `crc32=<本地 CRC>` 四个片段，
不再要求它们连续；`evaluateResponse()` 与读取中的提前成功判断共用该函数。

修复后三环境构建通过（`diagnostics` Flash 920,245 / RAM 55,244；
`rgb_gpio48` 923,625 / 55,300；`rgb_gpio38` 923,617 / 55,300），烧录
923,984 字节并输出 `Hash of data verified`，完整回归 **1198 项通过**
（`work/test_serial_013c.log`）。烧录会清空 RAM，因此需要重新录音后再上传，
才能观察修复后的 `MIC_UPLOAD_DONE`；第二次上传实际已产生有效 WAV，可用它
先做试听与本地 ASR，但“固件正确上报成功”尚未在实机重试。

### 5.5 最终验收（2026-11-08）

第二次修复烧录后，用户重新录音并上传，串口记录：

```
mic record
20:34:50.947 > OK mic=recording frames=160000 duration_ms=10000
20:35:01.490 > MIC_RECORD_DONE frames=160000 bytes=320000 sample_rate_hz=16000 sample_format=s16le channels=1 crc32=ee814fb9
mic upload
20:35:19.760 > MIC_UPLOAD_START bytes=320000 crc32=ee814fb9 host=192.168.31.29 port=8080 attempts_max=3
20:35:20.261 > MIC_UPLOAD_DONE bytes=320000 crc32=ee814fb9 attempts=1
20:35:20.261 > OK mic=uploaded bytes=320000 crc32=ee814fb9
```

同一固件在 20:31 的另一次上传也已正常上报
`MIC_UPLOAD_DONE ... crc32=66e82f60 attempts=1`，说明响应解析修复有效。
接收端保存 `work/audio/mic-20261108-203520.wav`（320,044 字节，含 44 字节
WAV 头），重新计算 PCM CRC 为 `ee814fb9`，与固件一致；峰值 28.12%，
语音覆盖整个 10 秒。`scripts/asr_local.py` 输出
`开始记录这是一个AI测试的测试我正在说话`，用户试听确认内容正确、句尾清楚。

至此第 4 节的第 1–6 项全部完成，实验 013 第一阶段记为**已验收**。证据以
用户听感和串口/接收端记录为准，未做定量音频测量。

### 5.6 第二阶段端到端验证（2026-11-09）

接收端在本阶段加入自动 ASR（改动尚未提交）：WAV 原子落盘后把文件排入
后台队列，调用 `work/asr-venv/bin/python scripts/asr_local.py --json`，
结果写入 `work/asr/<同名>.json`；本次以 `--once`、`asr=on queue=2` 启动。

流程与结果：

```
>>> mic record
>>> green                     # RGB 变绿 = 10 秒说话窗口开始
OK mic=recording frames=160000 duration_ms=10000
MIC_RECORD_DONE frames=160000 bytes=320000 sample_rate_hz=16000 sample_format=s16le channels=1 crc32=0aa5589a
>>> off
>>> mic upload
MIC_UPLOAD_START bytes=320000 crc32=0aa5589a host=192.168.31.29 port=8080 attempts_max=3
MIC_UPLOAD_DONE bytes=320000 crc32=0aa5589a attempts=1
OK mic=uploaded bytes=320000 crc32=0aa5589a
```

接收端日志：

```
[receiver] ok remote=192.168.31.17 bytes=320000 crc32=0aa5589a file=mic-20261109-230828.wav count=1
[asr] audio file=mic-20261109-230828.wav peak_pct=7.0 hp_rms_pct=0.595 active_ms=2960
[asr] text=这是一个AI测试你能听到吗我正在讲话
[asr] inference_ms=281.0 status=success file=mic-20261109-230828.wav
[asr] stopped success=1 error=0 skipped=0
```

WAV 为 320,044 字节（含 44 字节头），PCM CRC 与固件一致；主机侧
`work/asr/mic-20261109-230828.json` 记录了音频统计、文本与耗时
（模型加载 3,353.7 ms、推理 281.0 ms、RTF 0.028）。本次说话峰值 7.0%
（此前一次为 28.12%），仍能完整识别，但说明说话音量偏小时余量不大。

结论：录音 → 非阻塞上传 → 接收端校验保存 → 自动 ASR 的整条链路首次在
真实硬件上一次跑通，`attempts=1`，无重试。2026-11-09 用户确认实际所说
就是“这是一个AI测试你能听到吗我正在讲话”，识别文本逐字一致，实验 013
第二阶段记为**已验收**（证据为用户核对；未做定量音频测量）。WAV 与 JSON
仅在本机 `work/`，被 Git 忽略。

### 5.7 尚未验证

- 上传期间 OLED/舵机/音频的实际并行表现（设计上每轮只发一小块，但未在
  真实上传时同步观察）；
- 人为断网、接收端中途退出等重试场景；
- 主机防火墙是否放行 8080（未取得管理员权限检查 `ufw`；本次上传成功
  说明当前路径实际未被阻挡）。

## 6. 实物验收步骤（已完成，保留用于复现）

外部 5V 按需保持断开；麦克风只用 3V3。先确认 Ubuntu 与 ESP32 在同一
2.4 GHz 局域网，且 `src/secrets.h` 中的 `AUDIO_UPLOAD_HOST` 等于当前
Ubuntu 地址。

**终端 1（Ubuntu 接收端）**：

```bash
cd /home/hy/ai-desktop-robot
env -u PYTHONPATH .venv/bin/python scripts/audio_receiver.py --once
```

看到 `[receiver] listening host=0.0.0.0 port=8080 ...` 后保持运行。
如果之前启动过旧版接收端，先 Ctrl-C 关闭再重启。若提示端口被占用，换一个
端口并同步修改 `src/secrets.h` 后重新构建、烧录。

**终端 2（串口监视器）**：打开 `.venv/bin/pio device monitor`，等待
`WIFI_CONNECTED`，然后依次输入：

```
mic record
mic upload
```

注意：烧录或复位都会清空 RAM，若刚更新过固件，必须先重新 `mic record`，
不能沿用上一次录音。

等 `MIC_RECORD_DONE` 出现后再发 `mic upload`。预期：

- 串口先打印 `MIC_UPLOAD_START bytes=320000 crc32=...`；
- 随后 `MIC_UPLOAD_DONE bytes=320000 crc32=... attempts=1` 与
  `OK mic=uploaded ...`；
- 接收端打印 `ok ... bytes=320000 crc32=... file=mic-....wav`，两边 CRC 相同；
- 文件出现在 `work/audio/`。

若失败：`MIC_UPLOAD_RETRY` 表示正在重试；`MIC_UPLOAD_FAILED reason=...`
给出原因。依次检查接收端是否运行、`AUDIO_UPLOAD_HOST` 是否为当前 IP、
主机防火墙是否放行 8080、ESP32 是否 `WIFI_CONNECTED`。上传失败**不需要
重新录音**，录音仍在 RAM 中，可直接再次 `mic upload`；接收端 `--once`
在成功接收后退出，重试前需要重新启动。

**验证 WAV 与识别**：

```bash
ls -l work/audio
env -u PYTHONPATH work/asr-venv/bin/python scripts/asr_local.py work/audio/mic-<时间戳>.wav
```

试听该 WAV，确认内容完整、句尾清楚；ASR 文本应与实际所说一致。
可选：上传前启动 `motion wiggle` 或 `audio hello`，观察上传的 1–2 秒内
OLED 表情和动作/声音是否继续，作为非阻塞的直观检查（舵机需要外部 5V）。

## 7. 风险与边界

- 明文 HTTP 与共享令牌只适用于可信家庭局域网；不得做公网端口映射。
- 主机 IP 由 DHCP 分配，地址变化后需更新 `src/secrets.h` 并重新烧录。
- 上传只在 `record=ready` 时可用；忙时命令被拒绝，不会隐式录音或覆盖。
- 重试最多 3 次，每次从头发送；网络持续不可用时约数秒后失败，录音保留。
- TCP connect 最多阻塞约 1 秒；其余步骤每轮只推进一小块。
- 未做 TLS、设备身份证书、接收端并发多客户端与限流；本阶段只有单设备、
  单请求。
- 音频与令牌都不进入 Git；`work/` 下的 WAV 是否归档或分发需用户另行同意。

## 8. 下一步

1. 第一阶段已验收（2026-11-08，见 5.5）；第 6 节步骤保留用于复现。
2. 第二阶段在接收端保存 WAV 后自动调用现有
   `scripts/asr_local.py`，输出识别文本；不新建识别实现。2026-11-09 已首次
   端到端跑通（见 5.6），用户核对识别文本逐字一致，第二阶段已验收。
3. 再评估 VAD/能量门限、`ct-punc` 标点与命令词热词。
4. 如需跨网络使用，单独设计 TLS、身份认证与密钥管理，不复用当前明文方案。
