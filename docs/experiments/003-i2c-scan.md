# 实验 003：I²C 扫描与 OLED 首次显示

以下至第二阶段标题前为第一阶段历史记录，保留当时结论；当前状态见文末。

- 日期：2026-11-07（Asia/Shanghai）。
- 状态：**已验收（第一阶段 I²C 通信）**；三个环境构建、GPIO48 烧录及校验、52 项实机串口检查通过。两次扫描均发现 0x3C；屏幕显示未开始、未验证。
- 目标：保留实验 002 的六个命令，增加 `i2cscan`，仅确认地址应答，不识别显示控制器。

## 硬件与验收标准

用户报告四针 I²C OLED 已接线并通过开发板 USB 供电：VCC → 3V3、GND → GND、SDA → GPIO8、SCL → GPIO9。OLED 控制器、分辨率、板载上拉参数尚未确认；本阶段不加载显示驱动。

沿用 `rgb_gpio48`、GPIO48 RGB、UART0 / 115200 和原有内存配置。Wire 总线频率 100000 Hz。

验收标准：三个现有环境可构建；GPIO48 固件烧录并校验通过；原六命令回归通过；连续两次扫描报告相同应答地址，扫描前后 LED 命令状态保持且后续命令可执行。地址 ACK 仅证明该地址有设备应答，不能据此断定 SSD1306 / SH1106，也不代表屏幕已经显示。

## 实现与执行记录

- 原有 `red` / `green` / `blue` / `off` / `status` / `help` 保留；help 增加新命令，启动标记为 `[experiment 003] Serial RGB LED + I2C scan / Arduino`。原行接收器未改动。
- `Wire.begin(8, 9, 100000)` 初始化，失败时命令返回 `ERR i2c_not_ready`；复位可重新尝试。启动打印 `I2C_INIT`。
- 扫描常规 7 位地址 0x08–0x77，跳过保留地址；仅发送地址探测与 STOP，不发送屏幕初始化或像素数据。返回 0 计为应答，2 视为普通 NACK，其余输出 `I2C_ERROR` 并计入错误数（5 为超时）。
- 每次事务超时 25ms；扫描为同步操作，故障时所有地址超时的累计等待约 2.8 秒，另有驱动调度和串口输出开销。扫描期间不要连续发送大量命令，等 `I2C_SCAN done` 后再操作；原有每轮 64 字节读取预算不等于整个扫描非阻塞。
- `scripts/test_serial_led.py` 保留原 38 项检查，更新启动和 help 预期，增加初始化、两次扫描、大小写/空白/CRLF、状态保持、错误输入丢弃检查。脚本不预设 0x3C/0x3D，要求至少一个应答地址并连续一致；会复位设备，结束熄灯。
- 已执行 `.venv/bin/pio run -e diagnostics -e rgb_gpio48 -e rgb_gpio38`，三环境 SUCCESS，合计约 6.04 秒。GPIO48 程序 300817 字节，静态 RAM 19484 字节；未更改 PlatformIO 配置或依赖版本。
- 沙箱不暴露 USB 设备；获准在沙箱外查询后，确认目标 VID:PID 为 `1a86:55d3`、序列号 `5D4D001473`、by-id 映射 `/dev/ttyACM1`。摄像头仍是另一个 by-id 设备。占用查询未报告进程。
- 实际尝试烧录，打开串口返回 `Permission denied`，没有写入新固件。设备权限为 root:dialout、0660，没有之前的用户 ACL。已请用户在本机为固定 by-id 执行 `sudo setfacl -m u:hy:rw /dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00`，不索取密码。
- 权限处理补充：用户最初输入缺少 `:rw` 的命令报错；改为完整的 `sudo setfacl --modify=user:hy:rw /dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00` 后，用户确认成功。随后烧录成功，阻塞解除。
- GPIO48 重新烧录约 18.95 秒，各写入区域 hash 校验通过；固件镜像 301184 字节，SHA-256 为 `77e8cf8467516cfa4f5a1316b53d98a9dcf575d8200a02b2d2caa854c750db06`。
- `.venv/bin/python scripts/test_serial_led.py` **52 项实机检查全部通过**，包含原 38 项回归与 14 项新增检查。启动身份、内存、off、六命令、长行与非法输入保护、I²C 初始化均通过。
- 两次实际扫描分别使用 `i2cscan` + LF 和带首尾空白的大写命令 + CRLF，均只发现 **0x3C**，`devices=1 errors=0 result=ok`。两次扫描后 status 都保持 red；最后 off 和 status 通过，脚本正常退出并关闭串口。
- 本次未重新进行 RGB 光学观察；实验 002 的既有实物验收保留。OLED 控制器型号和屏幕显示仍未验证；没有进行断线、短路或初始化失败的硬件故障注入测试。

实验 001 / 002 的历史验收记录保留。原始日志在本机 `work/003-build.log`、`work/003-upload.log`（首次失败）、`work/003-upload-retry.log`、`work/003-serial-test.log`，被 Git 忽略，未入库。当前改动未提交、未推送；推送前按用户要求确认。

## VS Code 操作与结果解读

完成烧录后：

1. 在本项目按 Ctrl+Shift+P，选择 **PlatformIO: Serial Monitor**（或 Project Tasks → rgb_gpio48 → General → Monitor）。确认 115200 baud。
2. 点击下方监视器终端，英文输入 `i2cscan`，按 Enter；已配置本地回显、LF 和 `send_on_enter`。不要在普通 shell 中执行这条命令。
3. 等待 `I2C_SCAN done`，查看中间的 `I2C_FOUND address=0xNN` 行和末行的 `devices` / `errors`。
4. `result=ok` 表示至少一个地址应答且没有总线错误；`result=no_devices` 表示无应答；`result=bus_error` 表示存在异常，即使同时发现设备也应排查。无应答不能单独证明模块损坏。
5. 再次输入 `i2cscan` 可复测；`status`、`help` 及原颜色命令仍可使用。Ctrl+C 关闭监视器并释放串口后，才能运行烧录或回归脚本。

两次实机扫描输出相同，实际输出如下：

```text
I2C_SCAN begin sda=8 scl=9 frequency_hz=100000 range=0x08-0x77
I2C_FOUND address=0x3C
I2C_SCAN done devices=1 errors=0 result=ok
```

## 学习要点与下一步

I²C 使用 SDA 数据线和 SCL 时钟线，共地并采用这里指定的 3.3V 供电。扫描确认的是地址 ACK；地址不是控制器身份证明。屏幕保持空白不影响本阶段的通信验收。

当前下一步：获取 OLED 商品资料或模块标识，确认控制器与分辨率后再规划显示阶段；屏幕显示状态为未开始、未验证。用户可先按上述 Monitor 步骤自行复现 0x3C 扫描结果。


## 第二阶段：OLED 首次显示（2026-11-07 补充）

状态：已验收（SH1106 首次显示）；SSD1306 对比已完成但显示未通过；软件与用户观察结果见本节末尾。保留上文第一阶段历史结果；不改变接线、地址或 100kHz 频率。

目标：使用 U8g2，启动默认 SH1106 128×64，串口可切换 SSD1306 128×64，不反复烧录。显示三行指定文字、全屏边框、四角标记和当前驱动名。

验收标准：三环境构建与 GPIO48 烧录通过；原有命令及两种驱动切换串口检查通过；用户分别观察文字完整、边框四边可见、四角无裁切、无偏移/乱码。软件日志不代表显示成功，控制器身份仍不据显示推断为已确认。

### 实现与操作方法

- 只新增固定版本 `olikraus/U8g2@2.36.17`；现有 PlatformIO、Arduino 和 NeoPixel 版本不变。
- 使用 `U8G2_SH1106_128X64_NONAME_F_HW_I2C` 与 `U8G2_SSD1306_128X64_NONAME_F_HW_I2C`，硬件 Wire、全帧缓冲、U8G2_R0、无独立 reset 引脚。两种对象常驻，串口选择其一初始化并发送测试图。
- GPIO8/9 统一由 `Wire.begin(8, 9, 100000)` 管理；U8g2 构造函数不重复传入 clock/data 引脚，复用已初始化的 Wire 总线，避免其 GPIO 初始化改写引脚模式；`setI2CAddress(0x3C << 1)` 使用库要求的移位地址，`setBusClock(100000)` 固定频率。相关接口核对了 [U8g2 官方参考](https://github.com/olikraus/u8g2/wiki/u8g2reference) 和本次安装的源码。
- 原六命令、`i2cscan`、行缓冲保护保留。`off` 仍只关闭 RGB，不关闭屏幕；`status` 格式保持原样，OLED 另用 `oled_status` 查询。
- 新命令 `oled_sh1106` / `oled_ssd1306` 分别重新初始化并画图，`oled_status` 报告最后选择的驱动、绘图调用状态和实际 Wire 时钟。不保存驱动选择到 Flash，复位恢复 SH1106。
- 初始化前探测 0x3C，失败输出 `ERR oled_no_ack`；绘图后再探测并打印 `probe_after`。`draw_called=1` 只表示绘图调用结束；U8g2 的 Arduino 硬件 I²C 回调忽略每次 `Wire.endTransmission()` 的返回码，因此不把库 begin 返回值或绘图日志当作完整传输或光学成功证明。`visual=unverified` 始终提醒人工确认。
- 屏幕采用 6×10 字体，三行文字左边 x=10，基线 y=18/31/44；底部显示当前驱动名。边框覆盖 x=0..127、y=0..63，左上实心方块、右上空心方框、左下十字、右下叉号，四角标记均留在边框内。
- 显示初始化和发送是同步操作，只在启动或显示命令时执行，不连续刷新；等待回复后再发下一条命令。RGB 状态不随切换改变。

### 肉眼验收步骤

1. 烧录后先看默认 SH1106 画面：应有 `HELLO ESP32!`、`OLED TEST 003`、`I2C: 0x3C`，底部 `SH1106`。
2. 在 VS Code 按 Ctrl+Shift+P → **PlatformIO: Serial Monitor**，确认 115200，点击监视器终端，以英文输入 `oled_sh1106` 并回车，明确重画默认方案。
3. 检查三行文字与底部标签清晰完整，四条边框均可见，四角标记齐全；无整体平移、裁切、重复、乱码或闪烁。
4. 输入 `oled_ssd1306` 并回车，用相同标准检查，底部标签应变为 `SSD1306`；记录哪一种正常、哪一种有偏移/裁切/空白。可随时输入 `oled_sh1106` 切回，无需烧录。
5. 如果切换后画面异常，可按板卡复位恢复 SH1106，再只测试目标驱动；如需断电重新上电，应关闭监视器并在重连后核对串口权限。软件切换不等同于四针模块的硬件复位。

两种方案画面都正常时，只能记录“两个驱动均能显示当前测试图”，不能据此认定芯片型号。屏幕验收必须来自用户观察，串口返回不能代替。

### 第二阶段软件验证与故障处理

- 目标桥 VID:PID `1a86:55d3`、序列号 `5D4D001473`、固定 by-id → `/dev/ttyACM1` 已重新核对；现有 hy 读写 ACL 有效，访问前未发现占用。
- 初版三个环境编译通过，但实机启动只输出到 help，原回归的初始 status 检查失败。调试标记确认停在 `display.begin()`。源码中 U8g2 GPIO 初始化会对传入的 I²C 引脚调用 `pinMode(OUTPUT)`，而 Arduino Wire 对已初始化总线的再次 begin 直接返回；这是结合源码与现象定位的冲突原因。
- 修正为 GPIO 仅由 Wire 管理，U8g2 构造时不传 clock/data，保持使用现有硬件总线；同样方式适用于反复切换。修正后无调试标记的最终固件通过下列验证，未变更实际引脚或频率。
- 最终 `rgb_gpio48` 在烧录命令中重新构建成功；`diagnostics` / `rgb_gpio38` 也重新构建成功（约 7.35 秒）。GPIO48 静态 RAM 20924 字节、程序 313541 字节。
- 最终 GPIO48 烧录成功约 22.47 秒，各写入区域 hash 校验通过。最终固件 SHA-256：`abfd294d41f209f6279d4eb9860fe5357fe3138a1e82b83e3971b5d10a569291`。
- 最终回归 **65 项全部通过**：保留第一阶段的 52 项，新增 13 项启动默认显示、两种驱动切换、状态查询、扫描、RGB 状态保持和错误输入保护检查。最终 RGB 为 off、OLED 方案为 SH1106，脚本退出并释放串口。

| 驱动方案 | 编译 / 烧录与串口证据 | 肉眼效果 | 结论 |
| --- | --- | --- | --- |
| SH1106 128×64 NONAME | 默认启动绘图调用完成；从 SSD1306 切回成功；`probe_after=0`、Wire 100000Hz、扫描仍为 0x3C；RGB 状态保持 | 用户确认画面完整、没有任何问题（2026-11-07） | 已验收（此测试图显示），不认定控制器型号 |
| SSD1306 128×64 NONAME | 同一固件切换并绘图调用完成；`probe_after=0`、Wire 100000Hz、扫描仍为 0x3C；RGB 状态保持 | 用户选择“SSD1306 有错位、裁切或乱码”异常项（2026-11-07），未进一步区分具体症状 | 对比已完成，显示验收未通过；不采用为默认方案 |

实际回复示例：

```text
OLED_DRAW driver=SSD1306 address=0x3C probe_after=0 visual=unverified
OLED_STATUS driver=SSD1306 address=0x3C draw_called=1 visual=unverified frequency_hz=100000
OLED_DRAW driver=SH1106 address=0x3C probe_after=0 visual=unverified
OLED_STATUS driver=SH1106 address=0x3C draw_called=1 visual=unverified frequency_hz=100000
PASS: 65 checks; physical LED colors and OLED display still require user confirmation.
```

日志保存在本机 `work/003-oled-deps.log`、`work/003-oled-build.log`、`work/003-oled-upload.log`、`work/003-oled-serial-test.log`（首次回归失败）、`work/003-oled-debug-upload.log`、`work/003-oled-debug-serial.log`、`work/003-oled-fixed-build.log`、`work/003-oled-fixed-upload.log`、`work/003-oled-fixed-serial-test.log`。全部被 Git 忽略，未入库；第一阶段原日志未覆盖。本阶段未执行断线/总线故障注入，也没有代替用户进行光学观察。

第二阶段当前状态：**已验收（SH1106 首次显示）**。用户原话：“现在看到的是SH一一零六，画面完整，没有任何问题。”随后用户对 SSD1306 选择“有错位、裁切或乱码”选项，未进一步区分具体症状；SSD1306 显示未通过，保留为对比命令，不采用为默认方案。上述观察来自用户，未取得或归档照片；没有验证用户是否已经切回 SH1106。已提示输入 `oled_sh1106` 恢复正常画面，复位也会恢复默认方案。

下一步：完成本次实验 003 两阶段改动的 Git 同步，再由用户决定 OLED 表情实验目标。用户于 2026-11-07 已确认提交与推送，执行结果待核验；控制器实际型号仍未确认，不能把兼容性结果写成芯片鉴定。
