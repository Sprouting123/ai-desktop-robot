# 实验 001：板载 RGB LED 红绿蓝循环

- 日期：2026-11-06（Asia/Shanghai，按用户会话日期记录）
- 项目：`/home/hy/ai-desktop-robot`
- 结果：**构建通过、烧录与写入校验通过、运行日志通过；用户确认红 → 绿 → 蓝每秒循环正常。**
- 最终环境：`rgb_gpio48`，默认构建及烧录环境。
- 照片补充：2026-11-07 用户提供开发板正反面照片，已确认可见标识 `S3-N16R8`、`ESP32-S3` 及双 USB-C 接口 `COM` / `USB`。
- 身份边界：芯片、内存与可用 RGB 引脚已验证，照片上的主要标识已核对；厂家、完整 PCB 型号/版本及正式模组型号仍未确认，不能称其为已识别的官方 DevKitC-1 某一版。

## 1. 初始项目与原有程序

开始前 `git status --short --branch` 为 `## main...origin/main`，工作区干净；最近提交为 `7a17d0b first commit`，只有原始 `README.md`。保留其原始标题与 Git 历史，增加实验代码与说明。远程为 `https://github.com/Sprouting123/ai-desktop-robot.git`。

板上已经有 MicroPython v1.19.1 演示程序，因此用户观察到“刚通电的时候就是红绿蓝循环”是正常的。通过串口读取到原 `main.py` 使用 `Pin(48, Pin.OUT)` 和 `NeoPixel(pin, 1)`，每种颜色延时 1000 ms。烧录前将原始 `boot.py`（139 字节）和 `main.py`（485 字节）备份到本项目 `work/preflash-micropython/`。这是原始脚本备份，不是整片 Flash 镜像。

本次新完成的是：用本地 PlatformIO + Arduino 工程构建固件、写入并校验、读取自己程序的标记与诊断信息、核对实物灯光。现象与预装演示类似，但当前运行程序来自本仓库的 C++ 代码。

## 2. 硬件、串口和引脚证据

| 项目 | 实测或来源 |
| --- | --- |
| 照片可见型号标识 | 正面屏蔽罩 `S3-N16R8`，背面 PCB `ESP32-S3`；双 USB-C，背面分别标记 `COM` / `USB` |
| 厂家、PCB 版本、正式模组型号 | 正反面照片未提供足以确认这些项目的清晰标识；不能将 `S3-N16R8` 直接写成 `ESP32-S3-WROOM-1` 或指定官方 PCB 版本 |
| 接线 | 用户确认：只连接 USB，无 GPIO 外设 |
| 芯片 | esptool：`ESP32-S3 (QFN56) (revision v0.2)`；40 MHz 晶振 |
| Flash | esptool：`Detected flash size: 16MB`，JEDEC manufacturer `c8` / device `4018`；eFuse 显示 quad、3.3 V；程序报告 16777216 字节 |
| PSRAM | esptool：`Embedded PSRAM 8MB (AP_3v3)`；程序读取物理容量 8388608 字节（8 MiB） |
| 可用 PSRAM 堆 | Arduino 报告 8386279 字节，扣除了分配器管理开销；不等同于物理容量 |
| `/dev/ttyACM0` | `General / 4K_USB_Camera`，VID:PID `2bdf:02b1`；摄像头，仅查询身份，未作为串口打开或烧录 |
| `/dev/ttyACM1` | 沁恒 USB 串口桥，VID:PID `1a86:55d3`，`USB_Single_Serial`，驱动 `cdc_acm`；下游由 ROM 日志及 esptool 确认是 ESP32-S3 |
| 固定串口路径 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00`，本次解析为 `/dev/ttyACM1` |
| 最终 RGB 引脚 | **GPIO48**：直接读到原板脚本使用此脚位；Arduino 烧录后用户确认实际灯光正确 |

乐鑫官方 ESP32-S3-DevKitC-1 初版 RGB 接 GPIO48，v1.1 接 GPIO38。该资料解释了为什么不能仅凭“N16R8”决定灯引脚；本板最终选择 GPIO48 的证据来自实物已有脚本与实际运行，并不能据此断言本板就是官方初版。

### 2.1 照片补充核对（2026-11-07）

用户在本会话补充了同一块开发板的正面和背面照片，可直接观察到：

- 正面金属屏蔽罩印有 `S3-N16R8`、`WIFI+BT`；其 N16R8 标识与实验读取的 16 MB Flash、8 MB PSRAM 一致。
- 正面有 `RST`、`BOOT` 两个按键；方形彩灯旁标有 `RGB`。
- 背面 PCB 印有 `ESP32-S3`；两个 USB-C 接口旁分别印有 `COM` 和 `USB`，另有 `USB_OTG` 标记。识别接口以丝印为准，正反面照片的左右位置会翻转。
- 照片未能确认厂家、PCB 修订版本或完整的正式模组型号。项目中使用描述“ESP32-S3 / S3-N16R8 双 USB-C 开发板”，不强行归为官方 DevKitC-1 的某一版。

**GPIO48 的结论仍来自此前读取到的板载脚本及 Arduino 实物灯光验收。** 照片上的 `RGB` 标记本身没有给出数据引脚编号，不能用它单独判定 GPIO48 或 GPIO38。照片与已验证配置没有发现矛盾，继续使用 `rgb_gpio48`。

本节记录的是用户所传照片的可见信息；原图在会话中，尚未作为图片文件保存进仓库。

## 3. 可复现配置

| 项目 | 最终配置 |
| --- | --- |
| 开发方式 | Ubuntu + VS Code + PlatformIO + Arduino |
| VS Code 扩展 | `platformio.platformio-ide@3.3.4` |
| PlatformIO Core | `6.2.0`，项目 `.venv`，由 `requirements-dev.txt` 固定 |
| 平台 | `platformio/espressif32@6.12.0` |
| Arduino 框架 | Arduino-ESP32 `2.0.17`；实际包 `3.20017.241212+sha.dcc1105b` |
| 烧录工具 | esptool `4.9.0`，包 `2.40900.250804` |
| 通用板定义 | `esp32-s3-devkitc-1`；它的名称含 N8，仅作为基础模板，不代表识别到实物型号 |
| CPU | 240 MHz |
| Flash | 16 MB，QIO，80 MHz；`board_upload.flash_size = 16MB`，`board_upload.maximum_size = 16777216` |
| PSRAM | OPI；`board_build.arduino.memory_type = qio_opi`，`board_build.psram_type = opi`，`BOARD_HAS_PSRAM` |
| 分区 | `default_16MB.csv`；每个 app 槽为 `0x640000`（6553600 字节），所以程序大小上限不等于整片 16 MB |
| USB 控制台 | 通过当前 COM 口的 USB 串口桥使用 UART0；`ARDUINO_USB_CDC_ON_BOOT=0` |
| 烧录 / 串口速率 | 均为 115200 baud；使用固定 by-id 路径，无端口自动选择 |
| 串口监视 | `DTR=0`、`RTS=0`；实际打开串口时仍可能因驱动行为复位，采样包含启动日志 |
| LED | `adafruit/Adafruit NeoPixel@1.15.5`；1 颗，`NEO_GRB + NEO_KHZ800` |
| 颜色 / 亮度 | 红 → 绿 → 蓝，约 1000 ms/色，亮度 `24/255` |

`platformio.ini` 保留三个环境：

- `rgb_gpio48`：本板已验证，默认。
- `diagnostics`：不驱动 RGB 引脚，每秒报告硬件信息；构建通过，本次没有单独烧录。
- `rgb_gpio38`：其他接线版本的备选；仅构建通过，本次没有烧录，不能标为本板可用。

开发工具及缓存均在项目内：`.venv/`、`.pio-core/`、`.pio/`、`work/` 不纳入 Git。本机 `.vscode/settings.json` 指向项目 CLI 并被忽略；扩展推荐与构建任务纳入项目。

## 4. 实际执行与验收结果

1. 检查现有项目和 Git，查询 USB/udev 身份，排除摄像头端口。
2. 安装 VS Code PlatformIO 扩展及项目内独立 CLI。
3. 串口首次打开报 `[Errno 13] Permission denied`。用户执行针对该 by-id 设备的 `setfacl` 后，复查出现 `user:hy:rw-`，串口打开成功。
4. 读取原板 ROM / MicroPython 日志，备份两个原始脚本，并取得 GPIO48 的直接依据。
5. esptool 读取芯片身份、16 MB Flash、8 MB PSRAM 信息，与 N16R8 配置一致。
6. 三个环境首次构建均通过；首次下载工具链耗时约 8 分 45 秒。期间一个下载镜像 SSL 失败，由工具自动换镜像恢复，未关闭证书校验。
7. 烧录 GPIO48 程序，各写入区域显示 `Hash of data verified`。没有执行整片 Flash 擦除。
8. 用户确认红绿蓝循环正常，并说明预装程序已有同样效果。
9. 初版诊断误把 PSRAM 堆容量与物理容量直接比较，产生了不必要警告。已改用 `esp_spiram_get_size()` 检查物理容量，同时单独输出 `ESP.getPsramSize()` 的堆容量；灯光逻辑未改变。
10. 最终版本重新构建三个环境均通过，合计约 9.68 秒；重新烧录成功（约 18.17 秒），再采集 10 秒运行日志，警告消失。

| 验证项 | 最终结果 |
| --- | --- |
| `diagnostics` / `rgb_gpio48` / `rgb_gpio38` 构建 | 全部 SUCCESS |
| GPIO48 固件使用量 | RAM 19108 / 327680 字节；程序 284297 / 6553600 字节 |
| 最终固件文件 | 284656 字节；与程序使用量口径不同，包含镜像结构 |
| 写入校验 | SUCCESS，各区段 hash 校验通过 |
| 内存运行验证 | Flash 16777216、物理 PSRAM 8388608 字节 |
| 程序身份 | `[experiment 001] RGB LED / Arduino` |
| 颜色日志 | 采集到连续 9 次颜色命令，即 3 个红绿蓝周期 |
| 日志时间差 | 首次 1011 ms，随后 7 次均为 1000 ms；没有观察到重启循环 |
| 肉眼验收 | 用户确认红 → 绿 → 蓝、每种约 1 秒；发生在仅修正容量提示之前，灯光代码未改变 |
| 板卡完整厂家与 PCB 版本 | 仍未确认，不妨碍本次已验证的配置使用 |
| 实验 001 首次提交范围 | 8 个实验文件；当时排除工具缓存、原板脚本备份及另两个空文件。管理文档后续按用户要求单独初始化，见下方说明 |

最终实际日志节选（不是预期输出）：

```text
[experiment 001] RGB LED / Arduino
[hardware] chip=ESP32-S3 cores=2 flash=16777216 psram_chip=8388608 psram_heap=8386279
[config] rgb_pin=48 brightness=24 interval_ms=1000 console=UART0
[rgb] ms=1104 pin=48 color=RED (command sent; visual confirmation required)
[rgb] ms=2115 pin=48 color=GREEN (command sent; visual confirmation required)
[rgb] ms=3115 pin=48 color=BLUE (command sent; visual confirmation required)
[rgb] ms=4115 pin=48 color=RED (command sent; visual confirmation required)
```

最终 `.pio/build/rgb_gpio48/firmware.bin` 的 SHA-256：

`89b1a12696298db2a897686421a03249e5e9ea0dfcf7a2c05ca148d450b11b75`

原始日志仅保存在本机的 `work/`，没有纳入 Git：`001-build.log`、`001-build-final.log`、`001-chip-flash-id.log`、`001-preflash-console.log`、`001-upload-gpio48.log`、`001-runtime-gpio48.log`。容量修正前的烧录/运行日志另有 `before-capacity-fix` 后缀保留。

旧 MicroPython 固件启动时出现过 SHA-256 comparison failed 后继续运行的提示；本项目最终固件写入校验通过，采集到的启动日志没有该提示。

实验 001 首次提交时，`AGENTS.md` 与 `docs/progress.md` 还是其他工作创建的空文件，因此当时保留原样、未纳入该次提交。2026-11-07 用户要求建立长期管理机制，现已初始化[协作规则](../../AGENTS.md)和[项目进度](../progress.md)，纳入本次管理文档的提交范围；后续交接从这两个入口继续。

## 5. 如何再次构建、烧录和查看

在项目根目录执行；本次安装已经完成：

```bash
.venv/bin/pio run
.venv/bin/pio run -t upload
.venv/bin/pio device monitor
```

监视器按 Ctrl-C 退出。默认就是已验证的 `rgb_gpio48`。如需检查所有备选环境：

```bash
.venv/bin/pio run -e diagnostics -e rgb_gpio48 -e rgb_gpio38
```

新电脑先安装 Python venv 支持与 VS Code PlatformIO 扩展，再运行 `python3 -m venv .venv` 和 `.venv/bin/python -m pip install -r requirements-dev.txt`。串口 by-id 是本块设备的标识；更换开发板或改用原生 USB 时，应重新确认端口及 CDC 配置，不能直接使用摄像头端口或假定编号不变。

当前这次插入设备的临时权限修复命令为：

```bash
sudo setfacl -m u:hy:rw /dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00
```

用户已经执行；重新插拔后可能需要再次执行。管理员密码只在本机输入。没有更改所有串口的权限或系统用户组。

本次自动复位与烧录均正常，无需按键。如果后续确实卡在 Connecting，再按住 BOOT、短按 RESET/EN、松开 BOOT，然后重试。

当前终端继承了 ROS 的 `PYTHONPATH`；排除它后项目工具的依赖检查通过。若遇到 Python 包冲突，可在上述 CLI 命令前加 `env -u PYTHONPATH`；本次没有修改系统 ROS。

## 6. 本次应掌握的原理

- `setup()` 上电或复位后执行一次，用来初始化串口和 LED；`loop()` 持续重复。
- GPIO 是芯片的可编程输入/输出引脚。可寻址 RGB LED 内含控制芯片，通过一个数据 GPIO 接收串行颜色数据，不是三个 GPIO 各控制一种颜色。
- `setPixelColor()` 修改内存中的颜色，`show()` 把数据发给 LED，`delay(1000)` 保持颜色约 1 秒。本实验用阻塞延时便于入门，后续机器人多功能并行时应采用非阻塞调度。
- Flash 存放程序和文件；PSRAM 是运行时扩展内存。物理容量、可用堆容量、应用分区大小是不同概念。
- 编译证明代码能生成固件；写入校验证明数据烧录正确；串口证明新程序运行；肉眼观察确认灯光实际符合目标。这四层证据共同完成验收。

## 7. 资料与本地依据

- [乐鑫 ESP32-S3-DevKitC-1 v1.1 指南及 RGB 引脚修订说明](https://documentation.espressif.com/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html)
- [PlatformIO 通用板定义与覆盖方法](https://docs.platformio.org/en/latest/boards/espressif32/esp32-s3-devkitc-1.html)
- [固定的 Espressif32 6.12.0 平台描述](https://github.com/platformio/platform-espressif32/blob/v6.12.0/platform.json)
- [Arduino 2.0.17 的 PSRAM 堆容量实现](https://github.com/espressif/arduino-esp32/blob/2.0.17/cores/esp32/Esp.cpp)
- [PlatformIO VS Code 自定义 CLI 配置](https://docs.platformio.org/en/latest/integration/ide/vscode.html)
- [MicroPython 控制台与 Ctrl-C](https://docs.micropython.org/en/latest/reference/repl.html)
- [Adafruit NeoPixel 1.15.5 源码](https://github.com/adafruit/Adafruit_NeoPixel/tree/1.15.5)
- 外观标识依据：用户于 2026-11-07 在本会话提供的开发板正反面原始照片，见第 2.1 节。
- 实物引脚依据：本板原有 `main.py` 的只读串口输出及用户灯光观察；正反面照片不单独证明 RGB 数据引脚。
