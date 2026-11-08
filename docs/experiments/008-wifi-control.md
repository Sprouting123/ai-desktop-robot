# 实验 008：ESP32-S3 Wi-Fi 联网与局域网远程控制

- 状态：**已验收**（2026-11-08 用户报告测试通过；构建、串口回归、真实家庭 Wi-Fi 联网与含 HTTP 的自动回归 1038 项均通过）
- 日期：2026-11-08（Asia/Shanghai）
- 前置实验：[007 纸板机械原型](007-cardboard-prototype.md)、[006 双舵机与动作/情绪联动](006-dual-servo.md)

## 1. 目标

1. ESP32-S3 以 STA 模式连接家庭 2.4GHz Wi-Fi，不阻塞已有的 OLED、双舵机、动作/情绪和串口功能。
2. 在局域网提供最小 HTTP API：读取状态、触发情绪、触发动作；写操作只用 POST，并复用已有的 `MoodController` / `MotionEngine`，不复制状态。
3. 提供手机可用的单页控制界面，不依赖公网 CDN，不把令牌写进页面源码。
4. 明确安全边界：仅供可信局域网、明文 HTTP、独立令牌保护写操作、限制请求大小与频率。

本实验不做云端 AI、语音或视觉；那些是后续实验。

## 2. 硬件与接线

沿用实验 007 已验收的状态，没有新增模块或改动接线：

- OLED：VCC → 3V3、GND → GND、SDA → GPIO8、SCL → GPIO9，SH1106 128×64，0x3C，100kHz。
- 舵机 1：信号 GPIO4 / LEDC 通道 0；舵机 2：信号 GPIO5 / LEDC 通道 1；两只共用外部 5V 5A，ESP32 与外部电源共地。
- 开发板仍由 COM 口 USB 供电，通过 UART0 / 115200 烧录和监视。
- 软件测试和烧录期间外部 5V 保持断开；只有用户确认后才会接通并观察舵机。

## 3. 实现摘要

### 3.1 模块划分

| 文件 | 作用 |
| --- | --- |
| `src/wifi_manager.h/.cpp` | 非阻塞 Wi-Fi STA 状态机、超时、退避重连、状态查询 |
| `src/web_server.h/.cpp` | 基于 `WiFiServer` 的最小 HTTP/1.1 服务器、令牌校验、限流、JSON 接口 |
| `src/web_ui.h` | 存放在 PROGMEM 中的单页控制界面（HTML/CSS/JS） |
| `src/secrets.example.h` | 本地配置模板，已跟踪 |
| `src/secrets.h` | 实际 SSID/密码/令牌，本机文件，已被 `.gitignore` 忽略 |
| `src/main.cpp` | 初始化与 `loop()` 调度，新增 `wifi` / `web` 串口命令 |

`main.cpp` 每轮 `loop()` 依次调用 `wifiManager.update()`、`webServer.update()`、`eyesEngine.update()`、动作/情绪调度；网络处理没有整体等待循环。

### 3.2 Wi-Fi 状态机

- 仅 STA 模式；`WiFi.persistent(false)`、`WiFi.setAutoReconnect(false)`、`WiFi.setSleep(false)`，重连完全由本状态机控制，避免库后台重连导致状态含糊。
- 状态：`disabled` / `connecting` / `connected` / `backoff`。
- SSID 为空时进入 `disabled`，打印 `WIFI_DISABLED ssid_set=0 reason=no_credentials`，不启动 Wi-Fi。
- 单次连接超时 20s；超时或已连接后掉线都会断开并进入退避，延迟序列 2s → 5s → 10s → 20s → 30s（封顶 30s），连接成功后重置退避。
- `wifi reconnect` 不阻塞，先断开并安排 500ms 后重新尝试。
- 串口日志：`WIFI_CONNECTING ssid=... attempt=... timeout_ms=20000 status=...`、`WIFI_CONNECTED ip=... rssi=... channel=... connects=...`、`WIFI_TIMEOUT ...`、`WIFI_RETRY reason=timeout|lost delay_ms=...`、`WIFI_LOST status=...`、`WIFI_RECONNECT requested delay_ms=500`。
- `wifi status` 输出 `WIFI state=... ssid_set=... ip=... rssi=... attempts=... connects=... retry_in_ms=...`。日志不包含密码。

### 3.3 HTTP 服务器

没有使用 Arduino 内置 `WebServer`：它在调用处理函数前会把请求头声明的整个 `Content-Length` 请求体读入堆，无法满足“请求体上限”的要求。本实验实现了一个基于 `WiFiServer` 的最小 HTTP/1.1 服务器：

- 监听 80 端口，同一时刻只处理一个连接；`Connection: close`，不做 keep-alive。
- 每轮 `loop()` 最多读取 64 字节，OLED 与舵机调度在数据包之间继续运行。
- 请求缓冲区 1024 字节；请求体上限 128 字节；请求头/请求体等待上限 3s；超时返回 408。
- 响应使用 `send(..., MSG_DONTWAIT)` 分多轮发送，单轮把 socket 当前可接受的数据写完即返回；客户端停止读取时不会把 `loop()` 卡住，5s 内未发完则关闭连接。
- 只支持 `GET` 和 `POST`；方法错误返回 405 并带 `Allow` 头。
- 路径不允许 `?` 或 `#`，令牌不能放在 URL 中。
- 请求日志只记录状态码、错误名和来源 IP，不记录原始路径或请求头，避免客户端误放令牌时泄漏到串口。

### 3.4 接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/`、`/index.html` | 返回控制页面 |
| GET | `/api/status` | 返回设备状态 JSON |
| GET | `/favicon.ico` | 204，无内容 |
| POST | `/api/mood` | `{"name":"happy|sad|angry|normal|stop"}` |
| POST | `/api/motion` | `{"name":"neutral|wiggle|together|alternate|stop"}` |

- 名称必须在允许列表内，直接调用已有 `mood::Controller` / `motion::Engine`；没有串口透传，也不能绕过 60–120° 限位。
- `POST /api/mood` 的 `stop` 与串口 `mood stop` 一致：停止动作、关闭两路脉冲、保留当前表情，返回 `screen:"kept"`。
- `POST /api/motion` 清除 mood 标签，与串口 `motion` 命令一致。
- `/api/status` 返回 `uptime_ms`、`wifi{state,ip,rssi}`、`expression`、`mood`、`motion{name,state,step,total}`、`servo1/servo2{angle,target,moving,output,channel,ready}`。
- 认证：写操作必须带 `X-Auth-Token` 请求头。缺失返回 401，错误返回 403，服务端未配置有效令牌返回 503。令牌长度 16–64 个可打印 ASCII 字符，比较使用固定时间循环。
- 限流：每 10s 最多 30 个请求、10 个写请求，超出返回 429；写请求计数包含认证失败的 POST。
- 其他错误：400（请求行/头/JSON 体/名称非法）、411（POST 缺少 `Content-Length`）、413（请求体或整个请求过大）、431（请求头过大）、404（未知路径）、408（超时）。
- 所有响应带 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`；HTML 另带 CSP：`default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'`。

### 3.5 控制页面

- 单文件，存放在设备 Flash，无 CDN、外部字体、统计或其他外网请求；断网但局域网可用时仍能打开。
- 显示 Wi-Fi 状态、IP/RSSI、表情、mood、动作、两只舵机、运行时间；每 2s 轮询 `/api/status`。
- 按钮：开心/难过/生气/平静；摆动/同步/交替；醒目的“立即停止动作（保留表情）”。
- 令牌由用户粘贴到密码框，点击“保存到本页”后只保存在当前页面的 JavaScript 变量中；不写入 URL、`localStorage`、`sessionStorage` 或 Cookie。刷新页面需重新输入。
- 停止按钮只调用 `/api/mood` 的 `stop`，即关闭软件 PWM 输出；**不是物理断电，也不是机械制动**。

### 3.6 凭据管理

- `src/secrets.example.h` 是模板，说明复制为 `src/secrets.h`、家庭网络需为 2.4GHz、用 `openssl rand -hex 16` 生成令牌。
- `.gitignore` 增加 `src/secrets.h`；已用 `git check-ignore` 验证该文件被忽略。
- 固件通过 `__has_include("secrets.h")` 读取；缺省时 SSID/密码/令牌为空，Wi-Fi 进入 `disabled`，网页写操作返回 503。
- Wi-Fi 密码、令牌均不打印到串口、测试输出或 Git。

## 4. 验收标准

按顺序分阶段验收，前一步通过后再做下一步：

1. **软件**：三环境构建通过；原有实验 002–006 的串口回归通过；Wi-Fi 不可用时串口、OLED、动作和情绪不受影响，无复位循环。
2. **联网**：设备连接家庭 2.4GHz Wi-Fi，串口打印 `WIFI_CONNECTED`、局域网 IP 与 RSSI；断开路由器后能进入退避并自动重连。
3. **页面（电脑）**：Ubuntu 浏览器打开 `http://<设备IP>/`，能看到状态并刷新。
4. **页面（手机）**：同一局域网手机打开页面，按钮可操作。
5. **远程控制实物**：用户确认后再接通舵机外部 5V，验证远程情绪/动作与停止；在此之前自动化测试不驱动真实舵机运动。

## 5. 已完成的验证（2026-11-08）

### 5.1 构建

- `.venv/bin/pio run -e diagnostics -e rgb_gpio48 -e rgb_gpio38`：三个环境全部 SUCCESS。
- 默认 `rgb_gpio48`：Flash 812681 字节（12.4%），静态 RAM 50672 字节（15.5%）；填入真实凭据的构建为 Flash 812717 字节，烧录写入 813088 字节（含镜像头/校验），RAM 不变。

### 5.2 Wi-Fi 凭据为空的固件（Wi-Fi 关闭路径）

- 烧录默认环境，启动标记为 `[experiment 008] Wi-Fi LAN control / Arduino`；上电仍直接进入 SH1106 normal 眼睛，两只舵机 `output=off`，RGB 熄灭。
- 本机 `src/secrets.h` 已配置有效令牌、SSID 为空，因此 `WEB_AUTH state=enabled`，Wi-Fi 不启动。
- `scripts/test_serial_wifi.py` **910 项检查全部通过**（约 2.5 分钟）。覆盖实验 002/003/004 串口回归、十种表情、双舵机、动作序列/情绪联动，并新增：启动 Wi-Fi `disabled`、`web listening=0`、`WEB_AUTH state=enabled`、`wifi`/`web` 子命令用法、无 Wi-Fi 凭据时 `wifi reconnect` 被拒绝，以及串口日志不含令牌。
- HTTP 检查按预期跳过：`SKIP HTTP checks (no-credentials)`。

### 5.3 不可达 SSID 固件（超时/退避/非阻塞）

为验证 Wi-Fi 失败路径，临时把本地 `src/secrets.h` 的 SSID 改为不存在的 `ESP32-Test-NoSuchAP`（原文件先备份到忽略目录 `work/`，测试后恢复并重新烧录）：

- 50 秒串口捕获（`work/008-wifi-fail-capture.py`，本机日志，未入库）显示：
  - 0.9s `WIFI_CONNECTING ... attempt=1 timeout_ms=20000 status=6`；
  - 20.9s `WIFI_TIMEOUT attempt=1`，随后 `WIFI_RETRY reason=timeout delay_ms=2000`；
  - 22.9s `attempt=2`；
  - 连接期间 28s `motion neutral`、34s `motion status`、38s `motion stop` 均正常应答；
  - 42s `wifi reconnect` 返回 `OK wifi=reconnect`，42.5s 开始 `attempt=3`；
  - 全程 `WEB listening=0`，串口、动作与 OLED 调度没有被 20s 连接等待卡住。
- 该不可达 SSID 固件运行完整 `scripts/test_serial_wifi.py`：**903 项检查全部通过**，HTTP 跳过。测试跨越多次连接超时与退避，没有出现复位、卡死或原有命令失效。此后固件只改了 HTTP 响应发送路径，Wi-Fi 状态机与串口代码未变；最终构建又以 910 项回归确认了串口行为。
- 为适配异步 Wi-Fi 日志，测试脚本会过滤 `WIFI_*`、`WEB_LISTEN`、`WEB_AUTH` 等主动日志行；i2c 扫描和 `eyes dump` 也按行类型解析，避免日志插入导致误判。

### 5.4 HTTP 接口与页面

2026-11-08 用户填入家庭 2.4GHz 凭据后，以下测试已在真实 Wi-Fi 下运行：

- 联网：串口打印 `WIFI_CONNECTING ssid=... attempt=1` → `WIFI_CONNECTED ip=192.168.31.17 rssi=-40 channel=3 connects=1` → `WEB_LISTEN state=listening port=80`；电脑（有线 `192.168.31.29/24`）`ping` 3/3 收到，`curl http://192.168.31.17/` 返回 200、8980 字节 `text/html`，`/api/status` 返回合法 JSON（`uptime_ms`、`wifi`、`expression=normal`、`mood=none`、`motion` 全零、两只舵机 `angle=90 output=off`）。
- 完整回归 `scripts/test_serial_wifi.py`：**1038 项检查全部通过**，结束时设备 `uptime_ms=187245`（约 3 分钟），末尾 `web status` 为 `requests=39 writes=20 rejected=12 rate_limited=2`。覆盖：
  - 页面 200、内容类型、CSP、无外网资源、无内嵌令牌、停止按钮与全部按钮；
  - `/api/status` 字段与舵机范围；
  - 缺失/错误令牌返回 401/403 且不改变状态；
  - 合法 mood/motion 调用现有控制器；
  - 非法名称、畸形 JSON、超大请求体、GET 写接口、POST 读接口、未知路径、favicon；
  - 令牌误放 URL 返回 400 且串口日志不出现令牌；
  - 动作期间 HTTP 轮询与串口/OLED 并行；
  - 写限流 429 与窗口恢复（10 写放行、后续拒绝、10.3s 后恢复）；
  - 显式 `wifi reconnect` 后 HTTP 恢复到同一地址；
  - 固件计数器 `web status` 与“所有响应不含令牌”；
  - 响应分多轮非阻塞发送的完整性（页面约 9KB，跨多轮发送后客户端收到完整内容）。
- 测试期间舵机外部 5V 保持接通，用户明确授权自动测试驱动舵机；测试结束时两路脉宽为 0、RGB 熄灭、屏幕回到眼睛画面。舵机的实际运动效果仍需用户通过网页操作观察确认。
- 设备 IP 由 DHCP 分配（当前 `192.168.31.17`），重启或租约变化后可能改变，以串口 `wifi status` 为准。

### 5.5 用户验收（2026-11-08）

用户报告“测试通过了”，据此把实验 008 记为已验收。证据为用户观察，未细分到浏览器、手机、具体按钮或舵机动作项目；未做定量测量。仍未验证：拔掉路由器或关闭 Wi-Fi 后的自动重连、长时间联网稳定性、RSSI 波动、令牌渗透测试。

## 6. 未验证与待办

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 真实家庭 Wi-Fi 连接 | 已验证（自动） | `ip=192.168.31.17 rssi=-40 channel=3`，电脑同网段 ping 通 |
| HTTP API / 页面自动测试 | 已验证（自动） | 1038 项回归全部通过 |
| Ubuntu 浏览器查看页面 | 用户报告通过 | 2026-11-08 用户报告测试通过，未细分到具体页面项；证据为用户观察 |
| 手机局域网访问 | 用户报告通过 | 同上；证据为用户观察 |
| 远程情绪/动作实物验收 | 用户报告通过 | 自动测试在用户授权、5V 接通下驱动过舵机；网页按钮与停止按钮的实物效果由用户报告确认 |
| 断路由器后的自动重连 | 未验证 | 可用拔路由器电源或关闭 Wi-Fi 复现 |
| 令牌安全 | 已实现，未做渗透测试 | 明文 HTTP，仅适用于可信局域网 |
| 长时间联网稳定性 | 未验证 | 目前只验证了无凭据与不可达 SSID 的软件路径 |

## 7. 用户操作步骤（联网与页面）

已完成（2026-11-08）：`src/secrets.h` 已填入家庭 2.4GHz 凭据；重新构建烧录后串口确认 `WIFI_CONNECTED ip=192.168.31.17 rssi=-40`，`WEB listening=1`。

剩余步骤：

1. 在 Ubuntu 浏览器访问 `http://192.168.31.17/`，确认状态每 2s 更新；在页面密码框粘贴本机 `src/secrets.h` 中的 `API_TOKEN`，点“保存到本页”，再试情绪/动作按钮。
2. 手机连接同一局域网，打开同一地址重复第 1 步。
3. 通过网页执行 `mood happy`、`motion wiggle` 和停止按钮，观察 OLED 表情与舵机实际运动（外部 5V 已接通）。
4. 若页面提示 401/403，检查令牌是否粘贴正确；若无法连接，先看串口 `WIFI state=` 和 `WEB listening=`，或用 `wifi status` 确认当前 IP。
5. 后续每次重启板卡后，DHCP 可能分配新 IP，先 `wifi status` 查询再用新地址访问。

**安全提醒：** 只在可信家庭局域网使用；不要在路由器上做公网端口映射；HTTP 是明文传输，令牌和状态可能被同网段窃听，不能用于公网或不可信网络。

## 8. 故障处理记录

- 烧录时端口被占用：VS Code 中残留的 `pio device monitor` 持有 `/dev/ttyACM1`，关闭该监视器后烧录成功。设备身份按 by-id 路径核对，未误用摄像头对应的 `/dev/ttyACM0`。
- 内置 `WebServer` 会先读完整请求体，改为自实现的受限 HTTP 解析。
- 初版解析把原始路径直接写入成员并记录到日志，存在令牌误放 URL 时泄漏的风险；已改为先校验再复制，并且拒绝路径完全不记录。
- 测试期间发现 Wi-Fi 异步日志会插入 `i2cscan` 输出，已让测试按行前缀解析；固件本身没有该问题。

## 9. 学习要点

- Wi-Fi 连接必须由 `millis()` 状态机驱动；Arduino 的 `WiFi.begin()` 只发起连接，不能在 `while` 里等结果。
- 关掉库的自动重连，自己控制退避，状态和日志才可解释；`setSleep(false)` 降低响应延迟。
- 网页写操作必须 POST + 独立令牌；令牌只走请求头，不能进 URL，也不能出现在日志和响应里。
- 明文 HTTP 的能力边界是“可信局域网”；真正的公网方案需要 TLS 和更完整的鉴权。
- 复用已有控制器（而不是在 HTTP 层复制状态）能让串口、网页和动作引擎始终一致。
