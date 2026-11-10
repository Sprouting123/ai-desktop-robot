// 实验 016：ESP-SR WakeNet9 唤醒词探针
//
// 第三阶段：VAD 起点/终点检测 + 0.5 秒预录缓冲 + 0.6–10 秒变长录音。
// 唤醒后先进入 REC_ARMING，忽略 300 ms 唤醒词尾音，再由 AFE VAD 检出说话起点；
// 说话后 800 ms 静音即结束，5 秒没有检测到说话则放弃本次录音。
//
// 目的：在独立工程中验证 INMP441 连续采样 + AFE + WakeNet 是否能检出官方
// 中文唤醒词“你好小智”，并测量帧耗时、内部 RAM / PSRAM 与任务 CPU 占用。
// 本文件不进入主固件；它只报告“模型检出”，不代表自定义“小桌小桌”可用。
//
// 接线（与主工程实验 010 相同）：
//   INMP441 VDD -> 3V3, GND -> GND, L/R -> GND
//   SCK -> GPIO16, WS -> GPIO17, SD -> GPIO18
// 外部 5V（舵机/功放）在本探针测试期间必须断开。

#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "driver/i2s.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "model_path.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wn_iface.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "net.h"
#include "oled.h"
#include "recorder.h"
#include "speaker.h"

#define MIC_SCK_GPIO 16
#define MIC_WS_GPIO 17
#define MIC_SD_GPIO 18

#define SAMPLE_RATE_HZ 16000
#define I2S_PORT I2S_NUM_1
#define WAKE_COOLDOWN_US (1500 * 1000)
#define REPORT_PERIOD_US (10LL * 1000 * 1000)

// 第三阶段 VAD 时间参数
#define VAD_IGNORE_US (300 * 1000)          // 唤醒后忽略尾音的窗口
#define VAD_NO_SPEECH_US (5000 * 1000)      // 5 秒没有语音则放弃
#define VAD_SILENCE_HANGOVER_US (800 * 1000)  // 说话后静音 800 ms 收尾

static const char *TAG = "WAKE016";

typedef struct {
  TaskHandle_t handle;
  uint32_t run_time;
} TaskSample;

static TaskSample g_prev[32];
static int g_prev_count = 0;

static uint32_t task_delta(const TaskSample *prev, int prev_count,
                           TaskHandle_t handle, uint32_t now) {
  for (int i = 0; i < prev_count; ++i) {
    if (prev[i].handle == handle) return now - prev[i].run_time;
  }
  return 0;
}

static void print_runtime_stats(int64_t elapsed_us) {
  static TaskStatus_t tasks[32];
  static TaskSample current[32];
  bool printed[32] = {};
  UBaseType_t count = uxTaskGetSystemState(tasks, 32, NULL);
  if (count == 0 || elapsed_us <= 0) return;
  if (count > 32) count = 32;

  printf("CPU_WINDOW elapsed_ms=%lld tasks=%u\n",
         (long long)(elapsed_us / 1000), (unsigned)count);

  // 找出本窗口 CPU 时间最多的 6 个任务。
  for (int slot = 0; slot < 6; ++slot) {
    int best = -1;
    uint32_t best_delta = 0;
    for (UBaseType_t i = 0; i < count; ++i) {
      if (printed[i]) continue;
      uint32_t delta = task_delta(g_prev, g_prev_count, tasks[i].xHandle,
                                  (uint32_t)tasks[i].ulRunTimeCounter);
      if (delta > best_delta) {
        best_delta = delta;
        best = (int)i;
      }
    }
    if (best < 0 || best_delta == 0) break;
    printed[best] = true;
    double pct = (double)best_delta * 100.0 / (double)elapsed_us;
    printf("CPU task=%s pct=%.1f run_ms=%lu\n", tasks[best].pcTaskName, pct,
           (unsigned long)(best_delta / 1000));
  }

  for (UBaseType_t i = 0; i < count; ++i) {
    current[i].handle = tasks[i].xHandle;
    current[i].run_time = (uint32_t)tasks[i].ulRunTimeCounter;
  }
  memcpy(g_prev, current, sizeof(TaskSample) * count);
  g_prev_count = (int)count;
}

static void print_memory(const char *tag) {
  size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
  size_t internal_largest =
      heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
  size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
  printf("MEM tag=%s internal_free=%u internal_largest=%u psram_free=%u "
         "min_heap=%u\n",
         tag, (unsigned)internal_free, (unsigned)internal_largest,
         (unsigned)psram_free, (unsigned)esp_get_minimum_free_heap_size());
}

static bool init_microphone(void) {
  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  config.sample_rate = SAMPLE_RATE_HZ;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = 0;
  config.dma_buf_count = 4;
  config.dma_buf_len = 256;
  config.use_apll = false;
  config.tx_desc_auto_clear = false;
  config.fixed_mclk = 0;
  config.mclk_multiple = I2S_MCLK_MULTIPLE_256;

  esp_err_t err = i2s_driver_install(I2S_PORT, &config, 0, NULL);
  if (err != ESP_OK) {
    printf("MIC_I2S_INSTALL_FAILED err=%d\n", (int)err);
    return false;
  }

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = MIC_SCK_GPIO;
  pins.ws_io_num = MIC_WS_GPIO;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = MIC_SD_GPIO;
  err = i2s_set_pin(I2S_PORT, &pins);
  if (err != ESP_OK) {
    printf("MIC_I2S_PIN_FAILED err=%d\n", (int)err);
    return false;
  }
  err = i2s_set_clk(I2S_PORT, SAMPLE_RATE_HZ, I2S_BITS_PER_SAMPLE_32BIT,
                    I2S_CHANNEL_MONO);
  if (err != ESP_OK) {
    printf("MIC_I2S_CLK_FAILED err=%d\n", (int)err);
    return false;
  }
  printf("MIC_READY port=%d sck=%d ws=%d sd=%d rate=%d format=s32_right\n",
         (int)I2S_PORT, MIC_SCK_GPIO, MIC_WS_GPIO, MIC_SD_GPIO, SAMPLE_RATE_HZ);
  return true;
}

typedef struct {
  const esp_afe_sr_iface_t *afe;
  esp_afe_sr_data_t *afe_data;
  int feed_chunk;
  recorder_t *rec;
  volatile uint32_t frames;
  volatile uint32_t mic_errors;
  volatile uint16_t window_raw_peak;
  volatile int64_t feed_total_us;
  volatile int64_t reported_feed_us;
  volatile int64_t feed_max_us;
} feed_ctx_t;

// 独立任务：只做 I²S 读取与 AFE feed，保证输入按 16 kHz 实时节奏进入 AFE。
static void feed_task(void *arg) {
  feed_ctx_t *ctx = (feed_ctx_t *)arg;
  int16_t *feed = (int16_t *)malloc(sizeof(int16_t) * ctx->feed_chunk);
  int32_t *raw = (int32_t *)malloc(sizeof(int32_t) * ctx->feed_chunk);
  if (feed == NULL || raw == NULL) {
    printf("PROBE_FAILED reason=feed_alloc\n");
    vTaskDelete(NULL);
    return;
  }

  for (;;) {
    size_t bytes_read = 0;
    esp_err_t err = i2s_read(I2S_PORT, raw, sizeof(int32_t) * ctx->feed_chunk,
                             &bytes_read, pdMS_TO_TICKS(500));
    if (err != ESP_OK || bytes_read < sizeof(int32_t) * (size_t)ctx->feed_chunk) {
      ++ctx->mic_errors;
      continue;
    }

    uint16_t peak = 0;
    for (int i = 0; i < ctx->feed_chunk; ++i) {
      int16_t sample = (int16_t)(raw[i] >> 16);
      feed[i] = sample;
      uint16_t magnitude = (uint16_t)(sample < 0 ? -sample : sample);
      if (magnitude > peak) peak = magnitude;
    }
    if (peak > ctx->window_raw_peak) ctx->window_raw_peak = peak;

    // 录音缓冲同时从原始麦克风样本写入，不依赖 AFE 输出。
    rec_feed(ctx->rec, feed, ctx->feed_chunk);

    int64_t t0 = esp_timer_get_time();
    int ret = ctx->afe->feed(ctx->afe_data, feed);
    int64_t dt = esp_timer_get_time() - t0;
    ctx->feed_total_us += dt;
    if (dt > ctx->feed_max_us) ctx->feed_max_us = dt;
    ++ctx->frames;
    if (ret < 0) {
      ++ctx->mic_errors;
    }
  }
}

static recorder_t g_rec;
static volatile bool g_busy = false;  // 上传/下载/播放期间忽略新的唤醒

static const char *rec_state_name(rec_state_t state) {
  switch (state) {
    case REC_IDLE: return "idle";
    case REC_ARMING: return "arming";
    case REC_RECORDING: return "recording";
    case REC_READY: return "ready";
    case REC_UPLOADING: return "uploading";
    case REC_DONE: return "done";
    case REC_FAILED: return "failed";
  }
  return "unknown";
}

// 对话任务：录音完成后上传，轮询主机回答（ASR→LLM→TTS 在主机后台串行），
// 下载并播放；失败时状态转 failed，下一次唤醒可重新录音。
static void dialog_task(void *arg) {
  recorder_t *rec = (recorder_t *)arg;
  for (;;) {
    if (rec->state != REC_READY) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    g_busy = true;
    rec->state = REC_UPLOADING;
    uint32_t samples = rec->samples;
    uint32_t crc = rec->crc;
    size_t bytes = (size_t)samples * 2u;
    printf("UPLOAD_START bytes=%u crc32=%08lx wifi=%d\n", (unsigned)bytes,
           (unsigned long)crc, net_wifi_connected() ? 1 : 0);

    net_upload_result_t up;
    if (!net_upload((const uint8_t *)rec->buffer, bytes, crc, &up)) {
      rec->state = REC_FAILED;
      printf("REC_UPLOAD_RESULT state=failed reason=%s\n", up.reason);
      g_busy = false;
      continue;
    }
    printf("REC_UPLOAD_RESULT state=done turn=%s\n", up.turn);
    oled_show_status("THINK");

    // 主机在后台执行 ASR → DeepSeek → Edge TTS；轮询到回答为止，最多 60 秒。
    int64_t deadline = esp_timer_get_time() + 60LL * 1000000;
    uint8_t *pcm = NULL;
    size_t pcm_len = 0;
    uint32_t pcm_crc = 0;
    net_reply_result_t rr;
    bool got_reply = false;
    while (esp_timer_get_time() < deadline) {
      int rc = net_fetch_reply(up.turn, &pcm, &pcm_len, &pcm_crc, &rr);
      if (rc == 0) {
        got_reply = true;
        break;
      }
      if (rc < 0) {
        printf("REPLY_FETCH_FAILED turn=%s reason=%s\n", up.turn, rr.reason);
        break;
      }
      vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (!got_reply && pcm == NULL) {
      printf("REPLY_TIMEOUT turn=%s\n", up.turn);
    }
    if (pcm != NULL) {
      oled_show_status("SPEAK");
      speaker_play((const int16_t *)pcm, pcm_len / 2, 90);
      heap_caps_free(pcm);
    }
    pcm = NULL;
    rec->state = REC_DONE;
    oled_show_status("READY");
    g_busy = false;
  }
}

void app_main(void) {
  printf("\n[experiment 016] WakeNet probe / ESP-IDF %s\n", esp_get_idf_version());
  print_memory("boot");

  // Wi-Fi 先启动，连接期间继续初始化 AFE；上传只在录音完成后才发生。
  if (!net_start()) {
    printf("NET_UNAVAILABLE upload_disabled\n");
  }

  if (!init_microphone()) {
    printf("PROBE_FAILED reason=mic_init\n");
    return;
  }

  // 必须先挂载 model 分区并解析模型清单，AFE 才能按名字找到模型。
  // 不调用 esp_srmodel_init 时 hufzip 只会打印
  // "Please check if there are target files in esp-sr/model/target"。
  srmodel_list_t *models = esp_srmodel_init("model");
  if (models == NULL) {
    printf("PROBE_FAILED reason=srmodel_init\n");
    return;
  }
  printf("SRMODELS num=%d\n", models->num);
  for (int i = 0; i < models->num; i++) {
    printf("SRMODEL name=%s\n", models->model_name[i]);
  }
  char *wn_name = esp_srmodel_filter(models, ESP_WN_PREFIX, "nihaoxiaozhi");
  if (wn_name == NULL) {
    printf("PROBE_FAILED reason=no_wakenet_model\n");
    return;
  }
  printf("SRMODEL_WN selected=%s\n", wn_name);

  afe_config_t afe_config = AFE_CONFIG_DEFAULT();
  // 单只 INMP441：没有参考通道，不做 AEC/回声消除；只保留 WakeNet 和 VAD。
  afe_config.aec_init = false;
  afe_config.se_init = false;
  afe_config.vad_init = true;
  afe_config.wakenet_init = true;
  afe_config.wakenet_model_name = wn_name;
  afe_config.wakenet_mode = DET_MODE_90;
  afe_config.pcm_config.total_ch_num = 1;
  afe_config.pcm_config.mic_num = 1;
  afe_config.pcm_config.ref_num = 0;
  afe_config.pcm_config.sample_rate = SAMPLE_RATE_HZ;

  const esp_afe_sr_iface_t *afe = &esp_afe_sr_v1;
  esp_afe_sr_data_t *afe_data = afe->create_from_config(&afe_config);
  if (afe_data == NULL) {
    printf("PROBE_FAILED reason=afe_create (model partition or model name?)\n");
    return;
  }
  int feed_chunk = afe->get_feed_chunksize(afe_data);
  int fetch_chunk = afe->get_fetch_chunksize(afe_data);
  printf("AFE_READY model=%s det_mode=90 total_ch=%d mic=%d "
         "ref=%d feed_chunk=%d fetch_chunk=%d\n",
         wn_name, afe->get_total_channel_num(afe_data),
         afe->get_channel_num(afe_data), 0, feed_chunk, fetch_chunk);
  print_memory("afe_created");

  // feed 与 fetch 必须分属两个任务：AFE 的 fetch 会阻塞等待输出帧，若与 feed
  // 放在同一循环里，fetch 等待期间没有新数据输入，实测每次循环被拖到约 300 ms
  // （约 3.3 帧/秒），完全跟不上 16 kHz 实时音频。
  if (!rec_init(&g_rec)) {
    printf("PROBE_FAILED reason=rec_alloc\n");
    return;
  }
  print_memory("rec_buffer");
  if (!speaker_init()) {
    printf("SPEAKER_UNAVAILABLE playback_disabled\n");
  }
  if (!oled_init()) {
    printf("OLED_UNAVAILABLE status_disabled\n");
  } else {
    oled_show_status("READY");
  }
  print_memory("speaker");

  feed_ctx_t ctx = {
      .afe = afe,
      .afe_data = afe_data,
      .feed_chunk = feed_chunk,
      .rec = &g_rec,
  };
  BaseType_t ok = xTaskCreatePinnedToCore(feed_task, "mic_feed", 4096, &ctx, 5,
                                          NULL, 1);
  if (ok != pdPASS) {
    printf("PROBE_FAILED reason=feed_task\n");
    return;
  }
  ok = xTaskCreatePinnedToCore(dialog_task, "dialog", 8192, &g_rec, 3, NULL, 0);
  if (ok != pdPASS) {
    printf("PROBE_FAILED reason=dialog_task\n");
    return;
  }

  int64_t started_us = esp_timer_get_time();
  int64_t last_report_us = started_us;
  int64_t last_wake_us = 0;
  uint32_t window_frames_at_report = 0;
  uint32_t window_fetch_null = 0;
  uint32_t fetch_null = 0;
  uint32_t wake_count = 0;

  // 第三阶段：唤醒后的 VAD 监听状态。
  bool listen_active = false;
  int64_t armed_us = 0;
  int64_t last_speech_us = 0;
  rec_state_t last_rec_state = REC_IDLE;

  printf("PROBE_LISTENING say the built-in wake word (ni hao xiao zhi)\n");

  for (;;) {
    afe_fetch_result_t *res = afe->fetch(afe_data);
    if (res == NULL) {
      ++fetch_null;
      ++window_fetch_null;
    } else if (res->wakeup_state == WAKENET_DETECTED) {
      int64_t now = esp_timer_get_time();
      if (now - last_wake_us > WAKE_COOLDOWN_US) {
        last_wake_us = now;
        ++wake_count;
        printf("WAKE_DETECTED count=%lu t_ms=%lld word_index=%d "
               "model_index=%d word_len=%d volume_db=%.1f\n",
               (unsigned long)wake_count, (long long)((now - started_us) / 1000),
               res->wake_word_index, res->wakenet_model_index,
               res->wake_word_length, res->data_volume);
        // 唤醒只进入“等待说话”状态；录多久交给 VAD 决定。
        // 上传/下载/播放期间忽略新的唤醒，避免扬声器声音被麦克风拾取后反复触发。
        if (g_busy) {
          printf("WAKE_IGNORED reason=busy\n");
        } else if (!rec_arm(&g_rec)) {
          printf("WAKE_IGNORED reason=rec_state_%s\n",
                 rec_state_name(g_rec.state));
        } else {
          listen_active = true;
          armed_us = now;
          last_speech_us = now;
          oled_show_status("LISTEN");
        }
      }
    }

    // 第三阶段：VAD 起点/终点。只在这里读 vad_state，录音缓冲仍由 feed 任务写。
    if (res != NULL && listen_active) {
      int64_t now_us = esp_timer_get_time();
      bool speech = res->vad_state == AFE_VAD_SPEECH;
      if (g_rec.state == REC_ARMING) {
        if (now_us - armed_us >= VAD_IGNORE_US && speech) {
          last_speech_us = now_us;
          rec_request_start(&g_rec);
          printf("VAD_SPEECH_START after_ms=%lld\n",
                 (long long)((now_us - armed_us) / 1000));
        } else if (now_us - armed_us >= VAD_NO_SPEECH_US) {
          rec_abort(&g_rec, REC_REASON_NO_SPEECH);
          listen_active = false;
        }
      } else if (g_rec.state == REC_RECORDING) {
        if (speech) {
          last_speech_us = now_us;
        } else if (now_us - last_speech_us >= VAD_SILENCE_HANGOVER_US) {
          rec_request_stop(&g_rec, REC_REASON_SILENCE);
          printf("VAD_SILENCE_END hangover_ms=%d samples=%lu\n",
                 (int)(VAD_SILENCE_HANGOVER_US / 1000),
                 (unsigned long)g_rec.samples);
          listen_active = false;
        }
      } else {
        listen_active = false;
      }
    }

    // 录音以“过短”结束时不会有上传任务接手，这里把 OLED 从 LISTEN 复位。
    rec_state_t rec_state = g_rec.state;
    if (rec_state != last_rec_state) {
      if (rec_state == REC_IDLE &&
          (last_rec_state == REC_ARMING || last_rec_state == REC_RECORDING)) {
        oled_show_status("READY");
      }
      last_rec_state = rec_state;
    }

    int64_t now = esp_timer_get_time();
    if (now - last_report_us >= REPORT_PERIOD_US) {
      int64_t elapsed = now - last_report_us;
      uint32_t frames = ctx.frames;
      uint32_t window_frames = frames - window_frames_at_report;
      window_frames_at_report = frames;
      double avg_ms = window_frames > 0
                          ? (double)(ctx.feed_total_us - ctx.reported_feed_us) /
                                window_frames / 1000.0
                          : 0.0;
      ctx.reported_feed_us = ctx.feed_total_us;
      printf("AFE_STAT frames=%lu window=%lu avg_feed_ms=%.2f "
             "max_feed_ms=%.2f raw_peak_pct=%.1f wakes=%lu fetch_null=%lu "
             "mic_err=%lu rec=%s rec_samples=%lu vad=%d uptime_s=%.1f\n",
             (unsigned long)frames, (unsigned long)window_frames, avg_ms,
             (double)ctx.feed_max_us / 1000.0,
             (double)ctx.window_raw_peak * 100.0 / 32768.0,
             (unsigned long)wake_count, (unsigned long)fetch_null,
             (unsigned long)ctx.mic_errors, rec_state_name(g_rec.state),
             (unsigned long)g_rec.samples, res != NULL ? (int)res->vad_state : -1,
             (double)(now - started_us) / 1000000.0);
      (void)window_fetch_null;
      ctx.window_raw_peak = 0;
      print_memory("run");
      print_runtime_stats(elapsed);
      last_report_us = now;
    }
  }
}
