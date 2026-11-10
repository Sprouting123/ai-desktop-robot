// 实验 016 第二阶段：SH1106 128x64 状态提示（I²C GPIO8/9，100 kHz）。
// 只显示英文短状态，用途是验证 OLED 与 AFE/Wi-Fi/播放并发，不替代主工程表情。
#pragma once

#include <stdbool.h>

bool oled_init(void);
// 居中显示一行短文本；失败返回 false，不影响录音/上传。
bool oled_show_status(const char *text);
