# 语音资源

## `hello_zh.raw`

- 内容：中文“你好，我是你的 AI 桌宠！”
- 来源：Edge TTS 7.3.1（免费，非官方 Microsoft 接口），提示音为
  `-5%` 语速；声音 `zh-CN-XiaoxiaoNeural`（女声，Warm）。
- 生成时间：2026-11-08，生成环境为本机 Ubuntu 的临时虚拟环境
  （`work/tts-venv`，不进入仓库）。
- 格式：16 kHz、16 bit 有符号小端、单声道、裸 PCM，无文件头。
- 大小：78,828 字节 = 39,414 帧，时长 2.463 s。
- 电平：峰值约 −3.5 dBFS，平均约 −18.9 dBFS。
- 处理：去掉首尾静音（保留约 20 ms），首尾各 10 ms 线性淡入淡出，
  由 ESP32 端再按 `kHelloVolumePercent` 缩放后送 I²S。

转换命令（在仓库根目录执行）：

```bash
ffmpeg -i work/tts/hello_zh-CN-XiaoxiaoNeural.mp3 \
  -af "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB,areverse,afade=t=in:st=0:d=0.01,areverse,afade=t=in:st=0:d=0.01,areverse" \
  -ar 16000 -ac 1 -sample_fmt s16 -f s16le assets/audio/hello_zh.raw
```

注意：`silenceremove=stop_periods=1` 会在句中第一个停顿处截断，
第一次转换只得到 0.44 s，已改用“去头 → 反转 → 去头 → 反转”的方式。

## 版权与再分发

该音频由 Edge TTS 合成，用于本项目的个人实验与设备演示。Edge TTS 是
非官方的 Microsoft 在线语音接口，没有面向此用法的正式再分发授权；因此
音频文件仅随本项目在私人仓库中使用，不作为独立的语音素材对外分发或商用。
如需公开分发，请改用明确许可的 TTS（如自建 CosyVoice）重新生成。

固件通过 PlatformIO 的 `board_build.embed_files` 把该文件只读链接进
flash，`src/voice_clips.h` 用链接器符号取得起止地址，不把整段音频复制到
RAM；播放时每次只读取 240 帧（15 ms）到栈外静态缓冲。
