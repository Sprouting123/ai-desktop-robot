// 实验 016 第二阶段：MAX98357A 播放（I2S_NUM_0 TX，与麦克风 I2S_NUM_1 不冲突）。
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool speaker_init(void);
// 阻塞播放单声道 16 kHz PCM；volume_percent 取 1–100。
bool speaker_play(const int16_t *mono, size_t frames, uint8_t volume_percent);
