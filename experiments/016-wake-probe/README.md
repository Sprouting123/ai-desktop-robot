# 实验 016 唤醒探针（ESP-IDF）

本目录是[实验 016](../../docs/experiments/016-voice-wakeup.md) 的独立唤醒探针源码快照，
用于复现“你好小智”离线唤醒、VAD 变长录音、Wi-Fi 上传、回答下载与播放的完整链路。
它**不是主固件**，也不参与根目录 `platformio.ini` 的构建；主工程仍是实验 015 的
Arduino 固件。

状态：第一、二、三阶段探针实测通过（2026-11-10）。实测记录、资源数据和已知限制
见[实验 016](../../docs/experiments/016-voice-wakeup.md) 第 6–7 节。

## 目录内容

| 路径 | 说明 |
| --- | --- |
| `src/main.c` | I²S 麦克风 + AFE/WakeNet、VAD 状态机、CPU/内存统计 |
| `src/recorder.c/.h` | 0.5 秒预录环、0.6–10 秒变长录音、CRC-32 |
| `src/net.c/.h` | Wi-Fi STA、`POST /upload`、`GET /reply/latest?turn=` |
| `src/speaker.c/.h` | MAX98357A 播放（I²S_NUM_0） |
| `src/oled.c/.h` | SH1106 英文状态提示（U8g2 C 库） |
| `src/probe_secrets.example.h` | 凭据模板；复制为 `probe_secrets.h` 后填写 |
| `platformio.ini`、`partitions.csv`、`sdkconfig.defaults` | 构建与 16 MB Flash 分区 |
| `scripts/serial_capture.py` | 采集串口到 stdout 的小工具（可选） |

## 第三方组件（不随仓库分发）

本目录**不包含**第三方源码、预编译库或模型镜像。复现前按以下版本放入
`components/`：

| 目录 | 版本 | 来源 | 说明 |
| --- | --- | --- | --- |
| `components/esp-sr/` | 1.9.2 | <https://github.com/espressif/esp-sr>（tag `v1.9.2`）或组件注册表 `espressif/esp-sr@1.9.2` | 含 `lib/esp32s3/*.a` 与模型打包脚本；Espressif MIT 许可 |
| `components/espressif__esp-dsp/` | 1.4.4 | <https://github.com/espressif/esp-dsp>（tag `v1.4.4`） | ESP-SR 依赖；Apache-2.0 |
| `components/u8g2/` | 2.36.17 | <https://github.com/olikraus/u8g2>（C 库） | 需要自建 IDF 组件，见下；new-BSD 许可 |

`components/u8g2/CMakeLists.txt` 只需一行（探针使用 C 库，不需要 Arduino 封装）：

```cmake
idf_component_register(SRC_DIRS "." INCLUDE_DIRS "." REQUIRES driver)
```

模型镜像由 `srmodels` 构建步骤从 `components/esp-sr/model` 生成；镜像与
`firmware.bin` 都是构建产物，不提交。

## 构建环境前提

探针使用独立的 PlatformIO Core（默认 `~/.platformio`），与主工程的 `.pio-core/`
分开。实测（2026-11-10）需要三处平台兼容处理，均只影响探针构建，不改变固件逻辑：

1. **IDF 4.4 工具链。** PlatformIO 6.12.0 的纯 `espidf` 环境默认选 GCC 14.2 的
   `toolchain-xtensa-esp-elf`，IDF 4.4.7 要求 `esp-2021r2-patch5`（GCC 8.4.0）。
   让探针核心复用主工程 `.pio-core/packages/toolchain-xtensa-esp32s3`，并在
   `~/.platformio/platforms/espressif32/builder/frameworks/espidf.py` 中让 IDF 4.x
   选择 `toolchain-xtensa-esp32s3`（该工具链的 `bin` 目录需在 SCons `PATH` 最前）。
2. **SCons action 深拷贝。** 同一文件的 `ElfToBin` 分支对 action 使用
   `copy.deepcopy`，在 SCons 4.11.1 下生成 `_Null` 命令并报
   `TypeError: unsupported operand type(s) for +: '_Null' and 'str'`；改为
   `copy.copy` 后构建通过，`--elf-sha256-offset` 保留。
3. **模型镜像大小。** ESP-SR 1.9.2 的 `movemodel.py` 输出约 3,994,697 字节，
   `partitions.csv` 已把 `model` 分区设为 4 MB（0x410000–0x810000）。

另外：本机没有 `python` 命令，构建与模型打包前需把项目 `.venv/bin` 加入 `PATH`
（其中 `python` 指向系统 Python 3.10），因为 ESP-SR 的打包脚本调用 `python`。

## 构建、烧录与运行

在仓库根目录执行（先关闭其他串口监视器）：

```bash
cd /home/hy/ai-desktop-robot
cp experiments/016-wake-probe/src/probe_secrets.example.h \
   experiments/016-wake-probe/src/probe_secrets.h
# 编辑 probe_secrets.h，填入 2.4 GHz Wi-Fi 与上传令牌

# 1) 构建应用
.venv/bin/pio run -d experiments/016-wake-probe

# 2) 生成模型镜像（PlatformIO 的普通 build 不执行该自定义目标）
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python \
  experiments/016-wake-probe/components/esp-sr/model/movemodel.py \
  -d1 experiments/016-wake-probe/.pio/build/wake_probe/sdkconfig \
  -d2 experiments/016-wake-probe/components/esp-sr \
  -d3 experiments/016-wake-probe/.pio/build/wake_probe
# 输出：experiments/016-wake-probe/.pio/build/wake_probe/srmodels/srmodels.bin

# 3) 烧录应用（bootloader + 分区表 + app）
.venv/bin/pio run -d experiments/016-wake-probe -t upload

# 4) 单独写模型分区（PlatformIO upload 不会写 model 分区）
.venv/bin/python .pio-core/packages/tool-esptoolpy/esptool.py \
  --chip esp32s3 \
  --port /dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00 \
  write_flash 0x410000 \
  experiments/016-wake-probe/.pio/build/wake_probe/srmodels/srmodels.bin
```

烧录后打开串口（115200）应看到 `AFE_READY model=wn9_nihaoxiaozhi_tts ...`，
说“你好小智”应出现 `WAKE_DETECTED`，随后进入 `REC_ARMING` / `REC_START`。
主机接收端、ASR、DeepSeek 与 TTS 的启动方式见
[实验 013](../../docs/experiments/013-wifi-audio-upload.md)、
[实验 014](../../docs/experiments/014-deepseek-api.md) 与
[实验 015](../../docs/experiments/015-ai-voice-reply.md)。

## 硬件与安全

- INMP441：VDD → 3V3、GND → GND、L/R → GND、SCK → GPIO16、WS → GPIO17、SD → GPIO18。
  不得把 VDD 接 5V。
- MAX98357A：BCLK → GPIO7、LRC → GPIO15、DIN → GPIO6；VIN 与 SD → 外部 5V 正极，
  GND 与 ESP32 共地；扬声器只接 SPK+/SPK−。开发板 `5Vin` 是输入，不能供电。
- OLED：VCC → 3V3、GND → GND、SDA → GPIO8、SCL → GPIO9。
- 外部 5V 仅用于舵机/功放；探针测试通常保持外部 5V 断开，只有需要听音时才接通。
- `probe_secrets.h` 只在本机，`.gitignore` 已忽略；日志不打印令牌。

## 已知限制

- 官方唤醒词是“你好小智”，不是“小桌小桌”；后者需要 Espressif 付费定制或自训练。
- 无 AEC：播放期间用 `g_busy` 屏蔽新唤醒，属于半双工；播放后的回声误唤醒未验证。
- 64 KB data cache 在本板启动复位，探针使用默认 32 KB / 32 B；未优化。
- 唤醒率、距离、噪声、长时间误报均未定量测量。
