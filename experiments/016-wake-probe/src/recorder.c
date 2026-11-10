// 实验 016 第三阶段：带预录缓冲的变长录音实现。
// 缓冲只在 RAM（优先 PSRAM），复位丢失；不写 Flash。
//
// 线程约定：
//   - feed 任务（mic_feed）是唯一写录音缓冲的任务，负责维护 0.5 秒预录环、
//     追加样本和最终收尾（READY / IDLE）。
//   - fetch 任务（app_main 主循环）只设置 start_request / stop_request 或
//     rec_abort，不碰缓冲内容，避免两个任务同时写同一块内存。
#include "recorder.h"

#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"

// 标准 CRC-32（多项式 0xEDB88320，初值/末值取反），与 Python zlib.crc32 一致。
uint32_t rec_crc32_update(uint32_t crc, const void *data, size_t len) {
  const uint8_t *bytes = (const uint8_t *)data;
  for (size_t i = 0; i < len; ++i) {
    crc ^= bytes[i];
    for (int bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
    }
  }
  return crc;
}

const char *rec_reason_name(rec_reason_t reason) {
  switch (reason) {
    case REC_REASON_SILENCE: return "silence";
    case REC_REASON_MAX: return "max_duration";
    case REC_REASON_TOO_SHORT: return "too_short";
    case REC_REASON_NO_SPEECH: return "no_speech";
  }
  return "unknown";
}

bool rec_init(recorder_t *rec) {
  memset(rec, 0, sizeof(*rec));
  rec->state = REC_IDLE;
  rec->buffer = (int16_t *)heap_caps_malloc(REC_MAX_BYTES,
                                            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  const char *caps = "psram";
  if (rec->buffer == NULL) {
    rec->buffer = (int16_t *)heap_caps_malloc(
        REC_MAX_BYTES, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    caps = "internal";
  }
  if (rec->buffer == NULL) {
    printf("REC_BUFFER_FAILED bytes=%d\n", REC_MAX_BYTES);
    return false;
  }
  printf("REC_BUFFER_OK bytes=%d caps=%s preroll_bytes=%d addr=%p\n",
         REC_MAX_BYTES, caps, (int)(REC_PREROLL_SAMPLES * 2),
         (void *)rec->buffer);
  return true;
}

bool rec_arm(recorder_t *rec) {
  rec_state_t state = rec->state;
  if (state != REC_IDLE && state != REC_DONE && state != REC_FAILED) {
    return false;
  }
  rec->start_request = false;
  rec->stop_request = false;
  rec->stop_reason = REC_REASON_SILENCE;
  rec->samples = 0;
  rec->crc = 0;
  __sync_synchronize();
  rec->state = REC_ARMING;
  printf("REC_ARM preroll_ms=%d min_ms=%d max_ms=%d\n",
         REC_PREROLL_SAMPLES * 1000 / REC_SAMPLE_RATE,
         REC_MIN_SAMPLES * 1000 / REC_SAMPLE_RATE,
         REC_MAX_SAMPLES * 1000 / REC_SAMPLE_RATE);
  return true;
}

void rec_request_start(recorder_t *rec) {
  if (rec->state == REC_ARMING) {
    rec->start_request = true;
  }
}

void rec_request_stop(recorder_t *rec, rec_reason_t reason) {
  if (rec->state == REC_RECORDING) {
    rec->stop_reason = reason;
    __sync_synchronize();
    rec->stop_request = true;
  }
}

void rec_abort(recorder_t *rec, rec_reason_t reason) {
  rec_state_t state = rec->state;
  if (state != REC_ARMING && state != REC_RECORDING) return;
  __sync_synchronize();
  rec->state = REC_IDLE;
  printf("REC_ABORT reason=%s samples=%lu\n", rec_reason_name(reason),
         (unsigned long)rec->samples);
}

static void ring_write(recorder_t *rec, const int16_t *samples, uint32_t count) {
  uint32_t pos = rec->preroll_pos;
  for (uint32_t i = 0; i < count; ++i) {
    rec->preroll[pos++] = samples[i];
    if (pos == REC_PREROLL_SAMPLES) pos = 0;
  }
  rec->preroll_pos = pos;
  rec->preroll_total += count;
}

// 把预录环按时间顺序拷入正式缓冲（此块样本尚未写入环，随后再追加）。
static void begin_from_preroll(recorder_t *rec) {
  uint32_t fill = rec->preroll_total >= REC_PREROLL_SAMPLES
                      ? REC_PREROLL_SAMPLES
                      : rec->preroll_total;
  uint32_t start =
      (rec->preroll_pos + REC_PREROLL_SAMPLES - fill) % REC_PREROLL_SAMPLES;
  for (uint32_t i = 0; i < fill; ++i) {
    rec->buffer[i] = rec->preroll[(start + i) % REC_PREROLL_SAMPLES];
  }
  rec->samples = fill;
  rec->crc = rec_crc32_update(0xFFFFFFFFu, (const uint8_t *)rec->buffer,
                              fill * 2u);
  __sync_synchronize();
  rec->state = REC_RECORDING;
  printf("REC_START preroll_samples=%lu\n", (unsigned long)fill);
}

static void append(recorder_t *rec, const int16_t *samples, uint32_t count) {
  uint32_t have = rec->samples;
  uint32_t room = REC_MAX_SAMPLES - have;
  uint32_t take = count < room ? count : room;
  if (take == 0) return;
  memcpy(rec->buffer + have, samples, take * sizeof(int16_t));
  rec->crc = rec_crc32_update(rec->crc, samples, take * 2u);
  rec->samples = have + take;
}

static void finalize(recorder_t *rec, rec_reason_t reason) {
  uint32_t samples = rec->samples;
  uint32_t crc = ~rec->crc;
  rec->crc = crc;
  __sync_synchronize();
  if (samples < REC_MIN_SAMPLES) {
    rec->state = REC_IDLE;
    printf("REC_ABORT reason=%s samples=%lu bytes=%lu min_samples=%d\n",
           rec_reason_name(REC_REASON_TOO_SHORT), (unsigned long)samples,
           (unsigned long)(samples * 2u), REC_MIN_SAMPLES);
    return;
  }
  rec->state = REC_READY;
  printf("REC_DONE samples=%lu bytes=%lu ms=%lu crc32=%08lx reason=%s\n",
         (unsigned long)samples, (unsigned long)(samples * 2u),
         (unsigned long)(samples * 1000u / REC_SAMPLE_RATE),
         (unsigned long)crc, rec_reason_name(reason));
}

void rec_feed(recorder_t *rec, const int16_t *samples, int count) {
  if (count <= 0) return;
  if (rec->state == REC_ARMING && rec->start_request) {
    begin_from_preroll(rec);
  }
  if (rec->state == REC_RECORDING) {
    append(rec, samples, (uint32_t)count);
    if (rec->samples >= REC_MAX_SAMPLES) {
      finalize(rec, REC_REASON_MAX);
    } else if (rec->stop_request) {
      finalize(rec, rec->stop_reason);
    }
    return;
  }
  ring_write(rec, samples, (uint32_t)count);
}
