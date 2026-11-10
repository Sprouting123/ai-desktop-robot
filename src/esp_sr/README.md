# ESP-SR 1.9.2 构建补齐源码

本目录的三个 `.c` 文件直接取自
[Espressif ESP-SR v1.9.2](https://github.com/espressif/esp-sr/tree/v1.9.2)：

| 文件 | 上游路径 |
| --- | --- |
| `model_path.c` | `esp-sr/src/model_path.c` |
| `esp_process_sdkconfig.c` | `esp-sr/src/esp_process_sdkconfig.c` |
| `esp_mn_speech_commands.c` | `esp-sr/src/esp_mn_speech_commands.c` |

ESP-SR 使用 Espressif MIT 许可。Arduino-ESP32 2.0.17 的 PlatformIO 工程只编译
`src/` 下的源码，不能像 ESP-IDF 组件那样自动编译第三方组件的 C 文件；
路线 A 的全量链接验证（实验 016 第四阶段）表明缺少它们会出现
`get_model_base_path` / `get_static_srmodels` 等未定义符号，因此在此保留副本。

预编译库、头文件和模型镜像**不入库**，按
[`experiments/016-wake-probe/README.md`](../../experiments/016-wake-probe/README.md)
把 ESP-SR 1.9.2 放到 `experiments/016-wake-probe/components/esp-sr/` 后，
根目录 `platformio.ini` 会自动引用；如上游版本升级，应同步替换这三个文件。

`afe_default.c` 是本项目自写的 C99 包装，用于在 C++ 主程序中调用
`AFE_CONFIG_DEFAULT()` 宏；它不是上游文件。
