// 实验 016 第二阶段：MAX98357A 播放实现。
// 接线与主工程实验 009 一致：BCLK GPIO7 / LRC GPIO15 / DIN GPIO6，无 MCLK。
#include "speaker.h"

#include <stdio.h>

#include "driver/i2s.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define SPK_I2S_PORT I2S_NUM_0
#define SPK_BCLK_GPIO 7
#define SPK_LRC_GPIO 15
#define SPK_DIN_GPIO 6
#define SPK_RATE_HZ 16000
#define SPK_CHUNK_FRAMES 240
#define SPK_VOLUME_PERCENT 90

static bool s_ready = false;

bool speaker_init(void) {
  if (s_ready) return true;

  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  config.sample_rate = SPK_RATE_HZ;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;  // 双声道同一样本
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = 0;
  config.dma_buf_count = 4;
  config.dma_buf_len = SPK_CHUNK_FRAMES;
  config.use_apll = false;
  config.tx_desc_auto_clear = true;
  config.fixed_mclk = 0;
  config.mclk_multiple = I2S_MCLK_MULTIPLE_256;

  esp_err_t err = i2s_driver_install(SPK_I2S_PORT, &config, 0, NULL);
  if (err != ESP_OK) {
    printf("SPEAKER_FAILED stage=install err=%d\n", (int)err);
    return false;
  }
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = SPK_BCLK_GPIO;
  pins.ws_io_num = SPK_LRC_GPIO;
  pins.data_out_num = SPK_DIN_GPIO;
  pins.data_in_num = I2S_PIN_NO_CHANGE;
  err = i2s_set_pin(SPK_I2S_PORT, &pins);
  if (err == ESP_OK) {
    err = i2s_set_clk(SPK_I2S_PORT, SPK_RATE_HZ, I2S_BITS_PER_SAMPLE_16BIT,
                      I2S_CHANNEL_STEREO);
  }
  if (err != ESP_OK) {
    printf("SPEAKER_FAILED stage=pin_clk err=%d\n", (int)err);
    return false;
  }
  s_ready = true;
  printf("SPEAKER_READY port=0 bclk=%d lrc=%d din=%d rate=%d\n",
         SPK_BCLK_GPIO, SPK_LRC_GPIO, SPK_DIN_GPIO, SPK_RATE_HZ);
  return true;
}

bool speaker_play(const int16_t *mono, size_t frames, uint8_t volume_percent) {
  if (!s_ready && !speaker_init()) return false;
  if (mono == NULL || frames == 0) return false;
  if (volume_percent == 0 || volume_percent > 100) return false;

  static int16_t stereo[SPK_CHUNK_FRAMES * 2];
  printf("SPEAKER_PLAY frames=%u duration_ms=%u volume=%u\n", (unsigned)frames,
         (unsigned)(frames * 1000u / SPK_RATE_HZ), (unsigned)volume_percent);

  size_t offset = 0;
  while (offset < frames) {
    size_t chunk = frames - offset;
    if (chunk > SPK_CHUNK_FRAMES) chunk = SPK_CHUNK_FRAMES;
    for (size_t i = 0; i < chunk; ++i) {
      int32_t scaled = (int32_t)mono[offset + i] * volume_percent / 100;
      if (scaled > 32767) scaled = 32767;
      if (scaled < -32768) scaled = -32768;
      stereo[i * 2] = (int16_t)scaled;
      stereo[i * 2 + 1] = (int16_t)scaled;
    }
    size_t bytes = chunk * 2u * sizeof(int16_t);
    size_t written = 0;
    esp_err_t err = i2s_write(SPK_I2S_PORT, stereo, bytes, &written,
                              pdMS_TO_TICKS(500));
    if (err != ESP_OK || written != bytes) {
      printf("SPEAKER_WRITE_FAILED err=%d written=%u want=%u\n", (int)err,
             (unsigned)written, (unsigned)bytes);
      return false;
    }
    offset += chunk;
  }

  // 等 DMA 队列把最后约 4 块（960 帧 ≈ 60 ms）播完；tx_desc_auto_clear
  // 会在欠载时输出静音，不需要 zero_dma_buffer 截断尾音。
  vTaskDelay(pdMS_TO_TICKS(150));
  printf("SPEAKER_DONE frames=%u\n", (unsigned)frames);
  return true;
}
