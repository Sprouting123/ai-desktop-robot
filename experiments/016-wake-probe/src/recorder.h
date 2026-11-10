// 实验 016 第三阶段：带预录缓冲的变长录音（只存在 RAM，复位丢失）
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define REC_SAMPLE_RATE 16000
#define REC_CHANNELS 1
#define REC_PREROLL_SAMPLES 8000   // 0.5 秒预录环形缓冲
#define REC_MIN_SAMPLES 9600       // 0.6 秒最短有效录音
#define REC_MAX_SAMPLES 160000     // 10.0 秒上限（含预录）
#define REC_MAX_BYTES (REC_MAX_SAMPLES * 2)

typedef enum {
  REC_IDLE = 0,
  REC_ARMING,     // 已唤醒、等待 VAD 检出说话起点
  REC_RECORDING,
  REC_READY,
  REC_UPLOADING,
  REC_DONE,
  REC_FAILED,
} rec_state_t;

typedef enum {
  REC_REASON_SILENCE = 0,
  REC_REASON_MAX,
  REC_REASON_TOO_SHORT,
  REC_REASON_NO_SPEECH,
} rec_reason_t;

typedef struct {
  volatile rec_state_t state;
  volatile uint32_t samples;
  volatile uint32_t crc;
  volatile bool start_request;
  volatile bool stop_request;
  volatile rec_reason_t stop_reason;
  int16_t *buffer;                  // PSRAM 优先，容量 REC_MAX_SAMPLES
  int16_t preroll[REC_PREROLL_SAMPLES];
  uint32_t preroll_pos;
  uint32_t preroll_total;
} recorder_t;

bool rec_init(recorder_t *rec);
// fetch 任务：唤醒后进入 REC_ARMING，开始等待 VAD 说话起点。
bool rec_arm(recorder_t *rec);
// fetch 任务：VAD 检出说话，由 feed 任务在下一块把预录缓冲写入正式录音。
void rec_request_start(recorder_t *rec);
// fetch 任务：请求结束（静音挂起）；实际收尾在 feed 任务中完成。
void rec_request_stop(recorder_t *rec, rec_reason_t reason);
// fetch 任务：放弃本次录音（如 5 秒内没有检测到说话）。
void rec_abort(recorder_t *rec, rec_reason_t reason);
// feed 任务每块调用：维护预录环、追加录音、收尾。
void rec_feed(recorder_t *rec, const int16_t *samples, int count);
const char *rec_reason_name(rec_reason_t reason);
// 标准 CRC-32（0xEDB88320）。初值传 0xFFFFFFFF，结果再取反才等于 zlib.crc32。
uint32_t rec_crc32_update(uint32_t crc, const void *data, size_t len);
