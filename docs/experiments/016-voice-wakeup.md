# 实验 016：离线唤醒词与免按键语音交互

状态：第一、二阶段已验收；第三阶段探针实测通过（2026-11-10）。官方词
“你好小智”命中；探针内已完成“唤醒 → OLED 提示 → VAD 变长录音（0.6–10 秒、
0.5 秒预录）→ 上传 → ASR → DeepSeek → Edge TTS → 取回 → 播放”，并验证
无语音超时、连续说话、10 秒截断与变长上传协议。主工程固件未改动，实验
001–015 的功能与验收结论保持不变；“小桌小桌”仍未实现，主工程集成
（Arduino + ESP-SR）尚未开始。

## 1. 目标

让桌宠不依赖手机、网页按钮或串口命令，直接用离线唤醒词开始一轮对话：

```
待机监听 → 说出唤醒词 → OLED 提示 → 自动录音 → 上传 → ASR → DeepSeek
→ TTS → 扬声器回答 → 回到待机监听
```

分三阶段推进：

1. **第一阶段：ESP32-S3 本地唤醒词可行性。** 查清 ESP-SR / WakeNet / AFE
   与当前 ESP32-S3 N16R8、ESP-IDF 4.4.7 的兼容性；用官方现成中文模型验证
   INMP441 连续采样与真实唤醒检测；测量 CPU、内部 RAM、PSRAM、Flash 占用，
   以及对 OLED、Wi-Fi、I²S 扬声器的潜在影响。**不把“麦克风采到声音”当成
   “唤醒词已识别”。**
2. **第二阶段：自动对话流程。** 唤醒后自动录音、上传、等待回答并播放；
   处理超时、取消、失败恢复、重复唤醒与播放期间误触发；保留现有 `mic`、
   `voice` 命令。
3. **第三阶段：VAD 与变长录音。** 自动判断说话结束、最长录音时间、预录
   缓冲、变长 PCM 协议与 CRC，并保持对实验 015 的兼容。

三个阶段依次推进；截至 2026-11-10，前两阶段已验收，第三阶段在探针内完成。
全程**不升级、不替换主工程框架，不直接大规模重构主工程**；主工程仍是实验 015
固件，除非后续单独决定集成方案。

## 2. 当前硬件与工程约束

- 板卡：ESP32-S3 N16R8，16 MB QIO Flash、8 MB OPI PSRAM。
- 主工程：Arduino-ESP32 2.0.17（内置 ESP-IDF 4.4.7），PlatformIO
  `platformio/espressif32@6.12.0`，默认环境 `rgb_gpio48`。
- 麦克风：INMP441，I²S1 RX，SCK GPIO16 / WS GPIO17 / SD GPIO18，
  16 kHz、32 bit 槽、右声道；实测有效数据在右声道。
- 扬声器：MAX98357A，I²S0 TX，BCLK GPIO7 / LRC GPIO15 / DIN GPIO6；
  需要外部 5V。构建、烧录、自动测试期间外部 5V 保持断开。
- 现有录音固定 10 秒、320,000 字节，由用户显式 `mic record` 触发；唤醒词
  尚未实现。

## 3. 第一阶段技术可行性调查（2026-11-10）

### 3.1 主工程与 ESP-SR 的版本关系

| 项目 | 版本 / 约束 | 结论 |
| --- | --- | --- |
| 主工程 Arduino-ESP32 | 2.0.17，内置 ESP-IDF 4.4.7 | 不改动 |
| ESP-SR 1.9.2（支持 IDF 4.4 的最新版） | `idf >= 4.4`，`espressif/esp-dsp <= 1.5.0` | **可在 IDF 4.4.7 上使用** |
| ESP-SR 1.9.3 及以上 | `idf >= 5.0` | 需要升级 IDF，本阶段不采用 |
| esp-dsp | 1.4.4，`idf >= 4.2` | 与 IDF 4.4.7 兼容，满足 ESP-SR 依赖 |

ESP-SR 不是 Arduino 库，而是 ESP-IDF 组件；它需要参与 IDF 的组件构建、
模型打包和独立 `model` 分区。直接把 126 MB 的组件塞进现有 Arduino 主工程
会同时影响构建系统、分区表和烧录流程。因此第一阶段使用独立 PlatformIO
工程验证，主工程保持可回退、可继续烧录。

### 3.2 官方现成中文唤醒词

ESP-SR 1.9.2 的 `Kconfig.projbuild` 与 `model/wakenet_model/` 中可用的中文
模型包括：

- 你好小智（`wn9_nihaoxiaozhi_tts`）
- 小爱同学（`wn9_xiaoaitongxue`）
- 你好小鑫（`wn9_nihaoxiaoxin_tts`）
- 小美同学（`wn9_xiaomeitongxue_tts`）
- Hi 小星（`wn9_hixiaoxing_tts`）
- 小龙小龙（`wn9_xiaolongxiaolong_tts`）
- 小滨小滨 / 小冰小冰（`wn9_xiaobinxiaobin_tts`）
- 喵喵同学、Hi Joy、Hi Lili 等

**没有任何版本包含“小桌小桌”模型。** 因此不能声称现成模型能识别“小桌小桌”；
第一阶段的实物验证只能使用官方词（计划用“你好小智”），它证明的是
“ESP32-S3 + INMP441 + WakeNet 链路可用”，不是目标唤醒词可用。

### 3.3 官方资源占用数据

来自 Espressif ESP-SR 官方 Benchmark（ESP32-S3）：

| 模型 / 配置 | 内部 RAM | PSRAM | 每帧平均耗时 |
| --- | --- | --- | --- |
| WakeNet9，2 通道 | 16 KB | 324 KB | 3.0 ms / 32 ms 帧 |
| WakeNet9，3 通道 | 20 KB | 347 KB | 4.3 ms / 32 ms 帧 |

AFE 官方数据（含 WakeNet、VAD、NS 等组合）为内部 RAM 约 49.1–79.2 KB、
PSRAM 约 739.7–1238.5 KB；不同配置（单麦/双麦、是否参考通道、LOW_COST/
HIGH_PERF）差异明显。上述是官方参考值，**不是本板实测值**；单麦、无参考
通道的配置需要探针实测。

### 3.4 自定义“小桌小桌”的现实条件

Espressif 官方提供付费定制 WakeNet，当前公开流程为：

- 一次性定制费，按设备数量或使用时长**不再收许可费**；具体价格需邮件
  `sales@espressif.com` 商谈，官方页面未公开。
- 三种方式：仅用 TTS 样本训练；Espressif 众包录音 + TTS；客户自备语料。
- 自备语料要求至少 **20,000 条**合格录音；语料齐备后通常需 **2–3 周**训练
  和优化。
- 每个 WakeNet 模型最多 5 个唤醒词，每个词通常 3–6 个音节。
- 硬件腔体、麦克风与扬声器设计会显著影响唤醒率，官方要求做硬件录音与
  失真测试。

因此“小桌小桌”不是改一个字符串就能得到：需要定制模型或自行训练。第一
阶段只验证通用链路，**不把定制词列入本轮已完成范围**。

### 3.5 可选路线（均未实测）

| 路线 | 优点 | 限制 / 待核实 |
| --- | --- | --- |
| Espressif 定制 WakeNet | 与 ESP-SR/AFE 原生集成，误唤醒和资源有官方支持 | 付费、需语料或 TTS 方案、2–3 周；价格不公开 |
| Picovoice Porcupine 自定义词 | 控制台可自建唤醒词，提供嵌入式 SDK | 许可、免费额度、商用条款与离线要求需按当前官网核对 |
| Edge Impulse / 自训练 KWS | 可完全自定义，数据与模型可控 | 需要采集/训练/量化/部署链路，准确率与资源需自行验证 |
| microWakeWord 等开源方案 | 开源、可离线训练 | 模型质量、中文支持、工具链与许可需逐项验证 |

本阶段不选型、不付费、不下载第三方模型；先把 ESP-SR 官方链路跑通，取得
本板真实资源与唤醒数据，再决定是否为“小桌小桌”投入定制或自训练。

## 4. 第一阶段探针设计

探针位于被 Git 忽略的 `work/016-wake-probe/`，不进入主工程、不提交模型
与构建产物。结构：

| 文件 | 作用 |
| --- | --- |
| `platformio.ini` | 独立 `espidf` 环境，固定 `framework-espidf ~3.40407.0`（IDF 4.4.7） |
| `sdkconfig.defaults` | 16 MB QIO、OPI PSRAM、自定义分区、AFE v1、WakeNet9 模型、运行时间统计 |
| `partitions.csv` | `factory` 4 MB；`model` 4 MB（0x410000，打包后镜像约 3.9 MB） |
| `components/esp-sr` | ESP-SR 1.9.2 官方组件（本地放置，不提交） |
| `components/espressif__esp-dsp` | esp-dsp 1.4.4（本地放置，不提交） |
| `src/main.c` | INMP441 连续采样 → AFE feed/fetch → 打印唤醒与资源数据 |

关键配置：

- 麦克风沿用实验 010 的 I²S1、GPIO16/17/18、16 kHz、32 bit 槽、右声道；
  读取后右移 16 位得到 16 bit PCM。
- AFE 改为单麦：`total_ch_num=1`、`mic_num=1`、`ref_num=0`，关闭 AEC/SE，
  保留 VAD 与 WakeNet；`DET_MODE_90`，模型
  `wn9_nihaoxiaozhi_tts`。
- 每 10 秒打印：帧数、feed+fetch 墙钟耗时均值/最大值、原始峰值百分比、
  内部 RAM/最大连续块、PSRAM、最小空闲堆，以及按任务统计的 CPU 百分比。
- 唤醒事件打印 `WAKE_DETECTED`，带词索引、模型索引、词长、音量与时间；
  同一唤醒 1.5 秒内不重复打印。
- 探针只报告模型的唤醒检测结果；日志中的声音峰值、`data_volume` 均不能
  单独证明唤醒词被识别。

模型由 ESP-SR 的 CMake 脚本打包为 `srmodels/srmodels.bin`。PlatformIO 的
`upload` 不会自动写入 `model` 分区，需在烧录应用后单独用 esptool 写入
`0x410000`。

## 5. 第一阶段验收标准

1. 独立工程在 IDF 4.4.7 下构建通过，主工程三环境仍可构建、可烧录。
2. 串口出现 `AFE_READY`，模型从 `model` 分区成功加载。
3. 用户说出“你好小智”时出现 `WAKE_DETECTED`；不说话时不应持续误报。
4. 记录 feed+fetch 耗时、CPU 占用、内部 RAM / PSRAM / Flash 实际占用。
5. 明确区分“链路可用”与“目标词可用”；“小桌小桌”仍标记为未实现。

第 1–5 项均已在 2026-11-10 取得实物证据（见 6.3–6.5）：独立工程构建通过、
模型从 `model` 分区加载成功、四次“你好小智”全部检出、安静段无新增唤醒，
并记录了本板 CPU / RAM / PSRAM / Flash 实测值。主工程三环境构建与烧录恢复
在验证记录中另行确认。

## 6. 实施记录

### 6.1 环境与组件准备（2026-11-10）

- 确认主工程仓库干净，HEAD 为 `ab2fd9b`，与 `origin/main` 一致。
- 下载 ESP-SR 1.9.2 组件与 esp-dsp 1.4.4，放在 `work/016-wake-probe/`。
- 建立独立工程与探针源码，未修改 `platformio.ini`、`src/` 或主工程任何
  固件文件。
- 发现本机无 `python` 命令，而 ESP-SR 打包脚本调用 `python`；构建时需把
  项目 `.venv/bin` 加入 `PATH`（其中 `python` 指向系统 Python 3.10）。
- 首次构建失败：PlatformIO 6.12.0 的纯 `espidf` 环境默认选 GCC 14.2
  `toolchain-xtensa-esp-elf`，而 IDF 4.4.7 要求 8.4.0（`esp-2021r2-patch5`），
  IDF 的 CMake 版本检查直接拒绝。探针使用独立的 `~/.platformio` 核心：
  链接主工程 `.pio-core` 中已安装的 `toolchain-xtensa-esp32s3` 8.4.0，并把
  该核心 `espidf.py` 的纯 IDF 工具链选择改为“IDF 4.x 使用
  `toolchain-xtensa-esp32s3`”。主工程 `.pio-core` 与主工程构建未改动；
  这是探针的本地构建环境处理，不是固件行为。
- 串口设备在准备阶段未连接：`/dev/serial/by-id/` 下只有摄像头
  `usb-General_4K_USB_Camera_...`，没有 CH340 开发板。烧录与实物验证需用户
  重新插上开发板 USB。

### 6.2 独立工程构建（2026-11-10）

在探针自己的构建环境里解决了三处平台问题；这些都只改
`~/.platformio`（探针使用的 PlatformIO Core），主工程 `.pio-core` 未改动：

1. **IDF 4.4 工具链选择。** PlatformIO 6.12.0 的纯 `espidf` 环境默认选
   GCC 14.2 的 `toolchain-xtensa-esp-elf`，IDF 4.4.7 的 CMake 版本检查要求
   `esp-2021r2-patch5`（GCC 8.4.0）。已在探针核心的 `espidf.py` 中让 IDF 4.x
   指向 `toolchain-xtensa-esp32s3`，并把该工具链的 `bin` 目录放到 SCons 编译
   `PATH` 最前（SCons 用裸命令名调用编译器，否则仍会解析到 14.2.0）。
2. **模型镜像检查。** `--elf-sha256-offset` 的构建代码对 SCons action 做了
   `deepcopy`，在 SCons 4.11.1 下生成 `_Null` 命令并报
   `TypeError: unsupported operand type(s) for +: '_Null' and 'str'`。改为
   `copy.copy` 后构建通过，SHA256 标志保留。这是构建工具兼容性处理，
   与固件逻辑无关。
3. **模型分区大小。** ESP-SR 1.9.2 的 `movemodel.py` 打包结果为
   3,994,697 字节，并提示推荐分区 3902K；初始 2 MB 分区放不下，已把
   `model` 分区改为 4 MB（0x410000–0x810000）。PlatformIO 的普通 `build`
   不执行 `srmodels` 自定义目标，模型镜像需单独用 ninja 构建。

构建结果（2026-11-10，`.venv/bin/pio run -d work/016-wake-probe`）：

| 产物 | 大小 | 说明 |
| --- | --- | --- |
| `firmware.bin` | 459,264 字节 | 应用镜像 |
| `firmware.elf` | — | RAM 23,072 / 327,680 字节（7.0%） |
| `bootloader.bin` | 22,544 字节 | IDF 引导 |
| `partitions.bin` | 3,072 字节 | 自定义分区表 |
| `srmodels.bin` | 3,994,697 字节 | 写入 `model` 分区 0x410000 |

`firmware.elf` 的 Flash 段为 458,905 字节（4 MB 应用分区的 10.9%）。上述
RAM/Flash 是**链接时静态占用**，不是运行时峰值；PSRAM 与 CPU 占用由 6.3–6.5
的实机日志确认。

烧录流程：先 `pio run -t upload` 写入 bootloader、分区表和应用，再用
esptool 把 `srmodels.bin` 写到 0x410000。PlatformIO 的 upload 不会自动写
模型分区。

### 6.3 实物启动：PSRAM、模型加载与 AFE

2026-11-10 22:00 前后完成应用与 `model` 分区烧录（模型 3,994,700 字节；
应用随修复多次重烧，最终双任务版本 469,968 字节；每次均输出
`Hash of data verified`），随后串口暴露三个问题，均已修复：

1. **PSRAM 未启用。** IDF 4.4.7 的 ESP32-S3 开关是
   `CONFIG_ESP32S3_SPIRAM_SUPPORT`（它 `select SPIRAM`），`sdkconfig.defaults`
   里只写 `CONFIG_SPIRAM=y` 被 Kconfig 忽略，启动日志 `psram_free=0`，
   AFE 因此失败。改为正确开关并显式指定 OPI、8 MB、80 MHz 后，启动打印
   `Found 64MBit SPI RAM device`、`psram_free=8386307`。
2. **未挂载 model 分区。** 只把模型名传给 AFE 不够，应用必须先调用
   `esp_srmodel_init("model")` 让 hufzip 解析分区；否则只打印
   `Please check if there are target files in esp-sr/model/target`。调用后
   打印 `MODEL_LOADER: Successfully load srmodels`，模型清单为
   `fst`、`wn9_nihaoxiaozhi_tts`、`mn6_cn`，`AFE_READY model=wn9_nihaoxiaozhi_tts
   det_mode=90 total_ch=1 mic=1 ref=0 feed_chunk=160 fetch_chunk=512`。
3. **feed 与 fetch 同循环导致严重欠采样。** 两者放在同一个 `for(;;)` 里时，
   `fetch` 阻塞等待输出帧，期间没有新数据输入，实测每轮约 300 ms、仅
   3.3 帧/秒（每帧只喂 10 ms 音频）。拆成独立 `mic_feed` 任务（I²S 读取 +
   `feed`）与主任务（阻塞 `fetch`）后恢复 100 帧/秒，`avg_feed_ms=0.04`。

另外实测：在 IDF 4.4.7 + 本板 8 MB OPI PSRAM 上启用 64 KB data cache
（`CONFIG_ESP32S3_DATA_CACHE_64KB`）会导致应用启动阶段 RTC 看门狗复位
（`RTCWDT_RTC_RST`），未能进入 `app_main`；暂时保持默认 32 KB / 32 B，
ESP-SR 只打印性能建议警告。64 B cache line 单独启用是否可用尚未验证。
这不影响当前唤醒链路，但与官方建议的 64 KB / 64 B 不一致，性能仍有优化空间。

### 6.4 本板首次实物唤醒与对照（2026-11-10）

条件：外部 5V 断开，只连 USB；INMP441 距说话人约 20–30 cm；探针固件运行中，
串口以 pyserial 直接采集（`pio device monitor` 不接受管道输入）。

- **唤醒测试。** 用户连续说四次“你好小智”，串口出现四次 `WAKE_DETECTED`：
  `word_index=1`、`model_index=1`，时间分别为 8.8 s / 12.3 s / 16.4 s /
  19.7 s，`volume_db` 为 −21.3 / −21.6 / −16.2 / −14.1。用户确认四次说法
  与四次识别一一对应，**4/4 命中，无漏检**。
- **安静对照。** 说话结束后继续采集到 100 s，`wakes=4` 不再增加（最后一次
  统计在上电 90.2 s）；20–90 s 各 10 秒窗口的 `raw_peak_pct` 依次为
  19.8、5.3、3.4、3.5、2.1、3.2、8.6、4.8，没有新的唤醒。更早一次
  100 秒对照采集（用户未说话）中 `raw_peak_pct` 最高 32.9%，同样
  `wakes=0`，说明系统没有被环境声响触发。
- 上电前 10 秒窗口 `raw_peak_pct` 为 96.8%，来自 INMP441 启动瞬态，
  未触发唤醒；不能当作语音或识别证据。

上述结论只证明“ESP32-S3 + INMP441 + AFE + WakeNet9 链路能识别官方词
‘你好小智’”，**不证明“小桌小桌”可用**。唤醒率、距离、噪声、多人环境与
长期误唤醒率均未做定量测量。

### 6.5 本板资源实测（2026-11-10）

| 项目 | 实测值 | 说明 |
| --- | --- | --- |
| 应用镜像 | 469,968 字节 | 最终双任务版本，4 MB factory 分区 |
| 模型镜像 | 3,994,697 字节 | 占 4 MB `model` 分区 95.2% |
| 内部 RAM 空闲 | 336,663 → 331,019 字节 | AFE 创建后到运行稳定，最大连续块 286,720 |
| PSRAM 空闲 | 8,386,307 → 8,012,247 字节 | AFE 约占用 374 KB PSRAM |
| 采集节奏 | 100 帧/秒 | `feed_chunk=160`（10 ms），`mic_err=0`、`fetch_null=0` |
| feed 耗时 | 均值 0.04 ms、最大 0.07 ms | 仅测量 `feed()` 调用本身 |
| CPU（`main`/fetch） | 约 12.0–12.1% | 单核占比，含 AFE + WakeNet 计算 |
| CPU（`mic_feed`） | 约 0.8% | 单核占比 |
| CPU（两个 IDLE） | 约 88% / 99% | 说明仍有充足余量 |

注意：主工程运行 Arduino-ESP32 2.0.17（同一 IDF 4.4.7），但带 OLED、Wi-Fi、
HTTP、I²S 播放等任务；本次探针没有这些并发负载，不能直接外推主工程余量。
唤醒与 OLED、Wi-Fi、扬声器并发时的时序与内存竞争仍未验证。

### 6.6 第二阶段：探针内自动对话闭环（2026-11-10）

用户选择“继续独立 IDF 探针工程”，在 `work/016-wake-probe/`（被 Git 忽略）
里实现唤醒后的整条链路，主固件与主机脚本接口保持不变。新增文件：

| 文件 | 作用 |
| --- | --- |
| `src/net.c/.h` | Wi-Fi STA（NVS/netif/事件/2–30 s 退避重连）、`POST /upload`、`GET /reply/latest?turn=` |
| `src/recorder.c/.h` | PSRAM 录音缓冲（320,000 字节）、增量 CRC-32、状态机 |
| `src/speaker.c/.h` | I²S_NUM_0 TX（GPIO7/15/6，16 kHz/16 bit、4×240 帧 DMA、音量 90%） |
| `src/oled.c/.h` | SH1106 128×64 状态提示（I²C GPIO8/9、100 kHz、U8g2 C 库） |
| `src/probe_secrets.h` | 本地 Wi-Fi 与上传配置，由主工程 `src/secrets.h` 生成，被 Git 忽略，日志不打印 |

流程（全部在探针任务内）：

```
WAKE_DETECTED → rec_start（OLED LISTEN）→ 采样 10.000 秒 → REC_DONE
→ 上传（3 次重试，OLED THINK）→ 轮询 /reply/latest?turn=，1 秒间隔、最多 60 秒
→ REPLY_READY → OLED SPEAK → I²S 播放 → OLED READY → 回到监听
```

任务划分：`main`（AFE `fetch()` + 周期统计 + 唤醒处理，CPU0）、`mic_feed`
（I²S 读取 + `afe->feed()` + 录音写入，CPU1，优先级 5）、`dialog`（上传/下载/
播放，CPU0，优先级 3）、`wifi_reconnect`（优先级 2）。唤醒、录音与上传都在
各自任务里完成，播放期间 `g_busy` 屏蔽新唤醒，避免扬声器声音经麦克风再次
触发；没有 AEC。

#### 6.6.1 实测结果

第一次全链路（22:35，接收端 ASR/LLM/TTS 全部开启）：
`WAKE_DETECTED` → `REC_DONE crc32=49b3363e` → `UPLOAD_DONE turn=20261110-223516-01`
→ ASR“你叫什么名字” → DeepSeek“我叫小桌，是你的桌面机器人小伙伴呀。”
→ Edge TTS 3.529 秒 / 112,928 字节 → `REPLY_READY crc32=c9f2b026` →
`SPEAKER_PLAY`/`SPEAKER_DONE`。当时外部 5V 未接通，用户未听到声音。

第二次（22:43，外部 5V 已接通）：`REC_DONE crc32=ca0578a7` →
`UPLOAD_DONE turn=20261110-224334-02` → ASR“你叫什么名字你是谁呀介绍一下你自己”
→ DeepSeek“我叫小桌，是住在 ESP32 桌面机器人里的 AI 小伙伴，可以陪你聊天、
回答问题。”（延迟 813.9 ms、126 Token、估算 USD 0.000029）→ Edge TTS 7.901 秒
/ 252,862 字节（42 字符、延迟 2,055.8 ms、¥0）→ `REPLY_READY crc32=d68cb353`
→ `SPEAKER_PLAY`/`SPEAKER_DONE`；**用户确认听到回答**。OLED 串口记录为
`READY → LISTEN → THINK → SPEAK → READY`，用户确认启动后屏幕显示 `READY`，
各状态切换的光学效果未逐项确认。

并发资源（播放窗口 `CPU_WINDOW`）：`main` 12.3%、`dialog` 1.8%、`mic_feed`
0.9%、`wifi` 0.9%，两个 IDLE 84.7% / 98.5%；播放期间 `avg_feed_ms=0.04`、
`mic_err=0`，说明 AFE 采集未被上传/播放拖慢。内部 RAM 空闲 126,375 字节，
PSRAM 空闲 7,439,199 字节（播放 252,862 字节缓冲时），空闲基线 7,692,067。
带 U8g2 的 `firmware.bin` 947,729 字节（`factory` 分区 4 MB），模型镜像不变。

#### 6.6.2 过程中发现并修复的问题

1. **U8g2 的 I²C 回调必须按传输周期缓存。** U8g2 的 CAD 层把“控制字节 +
   命令/数据”拆成多次 `U8X8_MSG_BYTE_SEND`（每次 1 字节）；若逐字节各发一次
   I²C 事务，控制字节 `0x00` 会单独成帧，命令变成裸字节（日志中首次失败为
   `len=1 b0=0x10`），OLED 返回 `ESP_FAIL`。改为在 `START_TRANSFER` 到
   `END_TRANSFER` 之间缓存，再一次性 `i2c_master_write_to_device`；同时跳过
   零长度写。
2. **唤醒误触发的软件保护。** 播放期间设置 `g_busy`，新唤醒只记
   `WAKE_IGNORED reason=busy`；录音中再次唤醒记 `reason=rec_state_*`。
3. 构建问题：ESP-IDF 的 `struct addrinfo` 需显式包含 `lwip/netdb.h`。
4. 第一次播放无声是外部 5V 未接通（用户确认接上后同一条链路可听到），
   不是固件缺陷；这也再次证明“日志播放成功”不等于“出声已验收”。

#### 6.6.3 仍未验证或未实现

- 探针没有 AEC 与回声抑制；播放时麦克风仍收到扬声器声音，只是被 `g_busy`
  屏蔽。播放结束后的残余回声能否触发唤醒未测试。
- 唤醒词仍是官方“你好小智”；“小桌小桌”需要自定义模型。
- ~~录音固定 10 秒，未做 VAD/变长录音/预录缓冲。~~（第三阶段已在探针内完成，
  见 6.7；主工程仍未集成。）
- 上传失败只重试 3 次后回到待机，需要用户再次唤醒；没有串口取消命令。
- OLED 只显示英文状态；中文状态与主工程表情未接入。
- 这些结果来自纯 ESP-IDF 探针，不能直接外推 Arduino 主工程的集成成本；
  主工程未改动。
- 64 KB data cache 启动复位的原因仍未定位。

### 6.7 第三阶段：VAD 与变长录音（2026-11-10）

在探针内把固定 10 秒录音改为“VAD 起点 + 静音终点 + 预录缓冲”的变长录音，
主机接收端同步接受变长协议；主工程固件与实验 013/015 的固定 320,000 字节
上传保持兼容。改动只在 `work/016-wake-probe/`（Git 忽略）与
`scripts/audio_receiver.py`、`scripts/test_audio_receiver.py`。

#### 6.7.1 录音状态机

| 参数 | 值 | 说明 |
| --- | --- | --- |
| 预录缓冲 | 8,000 样本 / 0.5 s | 环形缓冲，始终滚动保存最近 0.5 秒 |
| 最短有效录音 | 9,600 样本 / 0.6 s | 不足则 `REC_ABORT reason=too_short`，不上传 |
| 最长录音 | 160,000 样本 / 10.0 s | 到顶自动收尾 `reason=max_duration` |
| 唤醒尾音忽略窗口 | 300 ms | 唤醒后 300 ms 内不认语音起点 |
| 无语音超时 | 5 s | 唤醒后一直没检测到说话则 `reason=no_speech` |
| 静音收尾 | 800 ms | 说话后连续静音 800 ms 结束录音 |

```
WAKE_DETECTED → REC_ARMING（OLED LISTEN）
  ├─ 300 ms 后 VAD=SPEECH → REC_START（预录 0.5 s + 当前块）
  │     └─ 静音 800 ms → REC_DONE reason=silence；满 10 s → reason=max_duration
  └─ 5 s 内无语音 → REC_ABORT reason=no_speech
```

线程约定：`mic_feed` 任务仍是唯一写缓冲的任务（维护预录环、追加样本、收尾），
`main`（fetch）任务只设置 `start_request` / `stop_request` 或调用 `rec_abort`，
不再直接写录音内存。预录环与正式缓冲同一块 PSRAM 逻辑上分开，收尾时把环按
时间顺序拷入缓冲开头，CRC-32 覆盖实际样本数。

#### 6.7.2 变长上传协议（保持兼容）

- ESP32 仍发 `POST /upload`，`Content-Length` 为实际字节数，`X-Frames` 为
  `Content-Length / 2`，CRC 覆盖实际 PCM。
- 接收端由“只接受 320,000 字节”改为 **偶数字节、16,000–320,000 字节**
  （0.5–10 秒），并校验 `X-Frames` 等于实际帧数；响应中的 `frames` 也改为
  实际值。旧固件的 320,000 字节上传、10 秒 WAV、ASR/LLM/TTS/回答下载接口
  均不变。
- `scripts/test_audio_receiver.py` 从 30 项扩展到 **44 项**：新增 1 秒变长
  上传成功、低于下限 400、超上限 413、`X-Frames` 不匹配 400，并保留原有
  令牌、格式、CRC、截断等拒绝路径（拒绝时不产生 WAV）；`test_asr_pipeline.py`
  76/76 亦通过。

#### 6.7.3 实测结果（2026-11-10 22:59–23:08，接收端 ASR/LLM/TTS 全开）

外部 5V 断开，回答只走完取回与 `SPEAKER_PLAY`，本轮没有听音验收；播放链路
已在第二阶段用 5V 验收过。

| 场景 | 录音 | ASR | 回答 |
| --- | --- | --- | --- |
| 唤醒后停顿 1.7 秒说“今天天气怎么样” | 2.910 s / 93,120 B / CRC `d370bf2c` | 今天天气怎么样 | 7.259 s，取回并播放 |
| 唤醒后保持安静 | `REC_ABORT reason=no_speech samples=0` | —（不上传） | — |
| 约 5–7 秒的较长语句 | 7.140 s / 228,480 B / CRC `141c3730` | 我今天上班了然后下班玩游戏然后还去修车了 | 6.415 s |
| 连续说“你好小智现在几点了” | 8.690 s / 278,080 B / CRC `8e035009` | 现在几点了……（含重复唤醒词） | 6.277 s |
| 连续数数超过 10 秒 | 10.000 s / 320,000 B / CRC `f021d8f5` / `reason=max_duration` | 一二三四五六七八九十十一十二十三 | 4.143 s |

- 连续说话时 `VAD_SPEECH_START after_ms=303`，说明 300 ms 忽略窗口既屏蔽了
  唤醒词尾音，也没有漏掉紧跟唤醒词的语音；停顿场景起点在 1.727 s / 1.761 s。
- 各轮录音的长度随语句变化，均由 800 ms 静音收尾（或 10 秒截断），上传
  `attempt=1` 成功，接收端保存的 WAV CRC 与固件一致。
- 录音期间重复说唤醒词只产生 `WAKE_IGNORED reason=rec_state_recording`，不会
  打断或重启录音。
- 10 秒截断轮的上传为 320,000 字节，正好覆盖实验 013/015 的固定长度路径，
  证明变长改动没有破坏旧固件协议。
- 本轮三次 DeepSeek 调用合计约 USD 0.000095（105 + 144 + 188 Token，均为
  `deepseek-flash` 非思考模式），Edge TTS 三次共 97 字符、¥0。
- 探针启动：`REC_BUFFER_OK bytes=320000 caps=psram preroll_bytes=16000`；
  带 U8g2/OLED 的固件 949,840 字节。

#### 6.7.4 已知限制与未验证

- VAD 阈值（起点灵敏度、800 ms 静音、300 ms 忽略窗口）来自 `AFE_CONFIG_DEFAULT`
  与手工调参，只在安静室内、单人、近距离验证；噪声、远场与不同语速未测。
- 最短 0.6 秒包含 0.5 秒预录，因此“起点后 0.1 秒就结束”的误检仍可能上传
  一小段；目前依赖主机 ASR 的静音门限（`active_ms`、`peak_pct`）兜底，该
  组合场景未专门构造测试。
- 10 秒上限包含 0.5 秒预录，实际说话最长约 9.5 秒；超长语句会被截断，ASR
  只得到前半段。
- 连续说话场景的录音包含唤醒词本身（预录 + 无 AEC），ASR 文本因此带“你好
  小智”重复；当前不影响对话，但后续应在主工程里考虑裁剪或 AEC。
- 无 AEC：播放期间靠 `g_busy` 屏蔽新唤醒，播放结束后残余回声是否误唤醒未测。
- 唤醒词仍是“你好小智”；“小桌小桌”需要自定义模型。
- 本轮外部 5V 断开，第三阶段的回答没有听音验收；OLED 状态只通过串口
  `OLED_SHOW` 记录，未逐项目视确认。
- 主工程固件（实验 015）未集成 VAD/变长录音；探针测试后已恢复主固件并
  确认启动、Wi-Fi 与 Web 正常。

### 6.8 现象记录：切换固件后 OLED 画面横向偏移（2026-11-10）

- 现象：第三阶段探针测试完成、恢复实验 015 主固件后，用户报告眼睛画面
  位置不对；随后换成测试图观察，用户描述“整体左偏几个像素，左边的边框
  在右边出现了”，SH1106 与 SSD1306 两张测试图都出现同样的偏移/裁切。
- 排查：`OLED_STATUS driver=SH1106 address=0x3C ... screen=eyes` 与
  `EYES_MODE expression=normal` 均正常，`eyes dump` 的 64×32 帧缓冲左右
  对称（`hash=B2BE3EF1`）；重新发送 `oled_sh1106` 与 `eyes normal` 重新
  初始化无效；MCU 复位/重新烧录也无效。
- 原因：OLED 模块没有接硬件复位脚（`U8X8_PIN_NONE`），U8g2 的 SH1106
  初始化序列不含软复位命令，面板内部寄存器（列地址/起始行等）在 MCU
  复位、重新烧录期间保持原状；探针运行留下的状态主固件不会纠正。
- 处理：USB 完全断电约 3 秒再上电（真断电，不是复位），画面恢复正常，
  用户确认“重新插上了，恢复正常了”。本轮**没有修改任何固件**，也没有
  定位探针中具体哪次写入造成的残留状态。
- 后续影响：以后在探针与主固件之间切换后若出现画面偏移，先做整板断电
  重启再排查固件；这条经验已写入 `AGENTS.md`。

## 7. 未验证与风险

- 唤醒率、误唤醒率、有效距离、噪声环境、多人环境与长时间运行均未做
  定量测量；目前只有一次 4/4 命中与两次短时安静对照。
- 唤醒与 OLED、Wi-Fi、I²S 扬声器并发已在探针内跑通一次（6.6.1，CPU 与
  内存余量充足），但只是单次、单人、安静环境；主工程（Arduino 运行环境、
  完整 OLED 表情、双舵机、Web 服务器）中的并发与内存竞争仍未验证。
- 64 KB data cache 在本板会导致启动复位，原因未定位；当前用默认 32 KB /
  32 B 运行，与 ESP-SR 官方建议（64 KB / 64 B）不一致，性能余量未优化。
  单独启用 64 B cache line 是否可行未验证。
- 未验证“小桌小桌”的任何模型；定制费用、语料与周期需与 Espressif 商谈。
- 探针使用纯 ESP-IDF，与主工程的 Arduino 运行环境不同；即使探针成功，
  也不能直接推断主工程集成成本为零。
- 模型分区占 4 MB（95% 被模型镜像占满），加入多唤醒词或自定义词会进一步
  增大 Flash 占用，需要重新规划分区。

## 8. 下一步

1. ~~完成独立工程构建，修正 IDF 4.4.7 与 ESP-SR 1.9.2 的配置问题。~~
   （2026-11-10 已完成，见 6.2。）
2. ~~烧录应用与 `model` 分区，验证 AFE 单麦配置与模型加载。~~
   （2026-11-10 已完成，见 6.3。）
3. ~~用户说“你好小智”取得 `WAKE_DETECTED`，并做安静对照。~~
   （2026-11-10 已完成，4/4 命中，见 6.4。）
4. ~~记录 CPU、内部 RAM、PSRAM、Flash 实际占用。~~（见 6.5。）
5. ~~把开发板恢复为主工程固件并确认可构建、烧录、启动。~~（2026-11-10
   已完成：三环境构建通过，`rgb_gpio48` 烧录后启动实验 015 固件，Wi-Fi
   `192.168.31.17`、Web 监听正常。）
6. ~~根据结果决定第二阶段是在独立 IDF 工程继续，还是评估把 ESP-SR 集成进
   主工程的方式。~~（2026-11-10 用户选择继续独立 IDF 探针工程；见 6.6。）
7. ~~在探针内完成“唤醒 → OLED 提示 → 自动 10 秒录音 → 上传 → 取回答 →
   播放”。~~（2026-11-10 已完成：两次完整闭环、上传 CRC 一致、ASR/DeepSeek/
   Edge TTS 成功，用户确认听到 7.901 秒回答；见 6.6。）
8. ~~在探针内实现 VAD 起点/终点、预录缓冲、0.6–10 秒变长录音与变长上传，
   并保持对实验 015 的兼容。~~（2026-11-10 已完成：五种场景实测、44 项接收端
   测试通过；见 6.7。）
9. 评估把 ESP-SR、唤醒词、VAD 变长录音集成进 Arduino 主工程的可行方案与
   内存/任务冲突（OLED 表情、双舵机、Web、音频播放）。
10. 唤醒鲁棒性：噪声、距离、播放后残余回声、长时间空闲误报，以及
    `g_busy` 之外是否需要 AEC。
11. “小桌小桌”模型：向 Espressif 咨询定制流程（语料、费用、周期），或评估
    自训练可行性与授权；未确定前不改主固件。
