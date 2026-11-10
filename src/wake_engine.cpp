// Experiment 016 phase 5: formal Route A integration of ESP-SR WakeNet9.
//
// The capture path intentionally matches the verified probe:
//   INMP441 -> I2S_NUM_1 (16 kHz, 32-bit right slot) -> AFE feed task
//   AFE fetch task performs WakeNet detection and VAD start/stop decisions.
// The feed task is the only writer of the recording buffer; the fetch task
// only sets request flags, so no locking around the PCM buffer is needed.
#include "wake_engine.h"

#include <cstring>

#include <driver/i2s.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <freertos/semphr.h>

extern "C" {
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_wn_models.h"
#include "model_path.h"
}

// Implemented in src/esp_sr/afe_default.c (C linkage by construction).
extern "C" afe_config_t wake_afe_default(void);

namespace wake {
namespace {

constexpr int kMicSck = 16;
constexpr int kMicWs = 17;
constexpr int kMicData = 18;
constexpr i2s_port_t kPort = I2S_NUM_1;

constexpr int64_t kWakeCooldownUs = 1500LL * 1000;   // 1.5 s between detections.
constexpr int64_t kVadIgnoreUs = 300LL * 1000;       // Ignore the wake-word tail.
constexpr int64_t kNoSpeechUs = 5000LL * 1000;       // Give up after 5 s.
constexpr int64_t kSilenceHangoverUs = 800LL * 1000; // 800 ms trailing silence.
constexpr int64_t kReportPeriodUs = 10LL * 1000 * 1000;

uint32_t crc32Update(uint32_t crc, const uint8_t* data, size_t length) {
  for (size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 1U) ? (crc >> 1) ^ 0xEDB88320UL : crc >> 1;
    }
  }
  return crc;
}

size_t internalFree() {
  return heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
}

size_t psramFree() {
  return heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
}

}  // namespace

Engine::Engine() {}

Engine::~Engine() { stop(); }

void Engine::begin() {
  Serial.printf(
      "WAKE_CONFIG installed=0 port=%d sck=%d ws=%d sd=%d sample_rate_hz=%lu "
      "model=nihaoxiaozhi half_duplex=1\n",
      static_cast<int>(kPort), kMicSck, kMicWs, kMicData,
      static_cast<unsigned long>(kSampleRate));
}

bool Engine::installI2s() {
  i2s_config_t config = {};
  config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
  config.sample_rate = static_cast<int>(kSampleRate);
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

  esp_err_t err = i2s_driver_install(kPort, &config, 0, nullptr);
  if (err != ESP_OK) {
    Serial.printf("WAKE_START_FAILED reason=i2s_install err=%d\n",
                  static_cast<int>(err));
    return false;
  }
  i2sInstalled_ = true;

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = kMicSck;
  pins.ws_io_num = kMicWs;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = kMicData;
  err = i2s_set_pin(kPort, &pins);
  if (err == ESP_OK) {
    err = i2s_set_clk(kPort, kSampleRate, I2S_BITS_PER_SAMPLE_32BIT,
                      I2S_CHANNEL_MONO);
  }
  if (err != ESP_OK) {
    Serial.printf("WAKE_START_FAILED reason=i2s_config err=%d\n",
                  static_cast<int>(err));
    i2s_driver_uninstall(kPort);
    i2sInstalled_ = false;
    return false;
  }
  Serial.printf("WAKE_I2S_READY port=%d sck=%d ws=%d sd=%d rate_hz=%lu\n",
                static_cast<int>(kPort), kMicSck, kMicWs, kMicData,
                static_cast<unsigned long>(kSampleRate));
  return true;
}

bool Engine::loadModels() {
  if (models_ != nullptr && wnName_ != nullptr) return true;
  srmodel_list_t* models = esp_srmodel_init("model");
  if (models == nullptr) {
    Serial.println(
        "WAKE_START_FAILED reason=srmodel_init; flash the model partition");
    return false;
  }
  models_ = models;
  Serial.printf("WAKE_MODEL_LIST num=%d\n", models->num);
  for (int i = 0; i < models->num; ++i) {
    Serial.printf("WAKE_MODEL name=%s\n", models->model_name[i]);
  }
  wnName_ = esp_srmodel_filter(models, ESP_WN_PREFIX, "nihaoxiaozhi");
  if (wnName_ == nullptr) {
    Serial.println("WAKE_START_FAILED reason=no_wakenet_model");
    return false;
  }
  Serial.printf("WAKE_MODEL selected=%s\n", wnName_);
  return true;
}

bool Engine::createAfe() {
  afe_config_t config = wake_afe_default();
  // One INMP441, no reference channel: WakeNet + VAD only, no AEC/SE.
  config.aec_init = false;
  config.se_init = false;
  config.vad_init = true;
  config.wakenet_init = true;
  config.wakenet_model_name = const_cast<char*>(wnName_);
  config.wakenet_mode = DET_MODE_90;
  config.pcm_config.total_ch_num = 1;
  config.pcm_config.mic_num = 1;
  config.pcm_config.ref_num = 0;
  config.pcm_config.sample_rate = kSampleRate;

  const esp_afe_sr_iface_t* afe = &esp_afe_sr_v1;
  esp_afe_sr_data_t* data = afe->create_from_config(&config);
  if (data == nullptr) {
    Serial.println("WAKE_START_FAILED reason=afe_create");
    return false;
  }
  afe_ = afe;
  afeData_ = data;
  feedChunk_ = afe->get_feed_chunksize(data);
  fetchChunk_ = afe->get_fetch_chunksize(data);
  if (feedChunk_ <= 0) {
    Serial.println("WAKE_START_FAILED reason=feed_chunk");
    return false;
  }
  Serial.printf("WAKE_AFE_READY model=%s det_mode=90 feed_chunk=%d "
                "fetch_chunk=%d internal_free=%u psram_free=%u\n",
                wnName_, feedChunk_, fetchChunk_,
                static_cast<unsigned>(internalFree()),
                static_cast<unsigned>(psramFree()));
  return true;
}

bool Engine::start() {
  if (running_) {
    Serial.println("WAKE_ALREADY running=1");
    return true;
  }
  if (state_ == State::kStopped) {
    // Fresh start only; never overwrite an unconsumed clip from a previous run.
    frames_ = 0;
    crc_ = 0;
    preRollPos_ = 0;
    preRollTotal_ = 0;
    readyCount_ = 0;
    wakeCount_ = 0;
    ignoredCount_ = 0;
    micErrors_ = 0;
    feedFrames_ = 0;
    feedTotalUs_ = 0;
    feedMaxUs_ = 0;
    fetchNulls_ = 0;
    lastReadyCountPrinted_ = 0;
  }
  fetchStop_ = false;
  feedStop_ = false;
  startRequest_ = false;
  stopRequest_ = false;
  releaseRequest_ = false;
  suppressed_ = false;

  if (!installI2s()) return false;
  if (!loadModels()) {
    stop();
    return false;
  }
  if (!createAfe()) {
    stop();
    return false;
  }

  feed_ = static_cast<int16_t*>(malloc(sizeof(int16_t) * feedChunk_));
  raw_ = static_cast<int32_t*>(malloc(sizeof(int32_t) * feedChunk_));
  if (feed_ == nullptr || raw_ == nullptr) {
    Serial.println("WAKE_START_FAILED reason=feed_alloc");
    stop();
    return false;
  }

  buffer_ = static_cast<int16_t*>(
      heap_caps_malloc(kMaxFrames * sizeof(int16_t),
                       MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  const char* caps = "psram";
  if (buffer_ == nullptr) {
    buffer_ = static_cast<int16_t*>(heap_caps_malloc(
        kMaxFrames * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    caps = "internal";
  }
  if (buffer_ == nullptr) {
    Serial.println("WAKE_START_FAILED reason=record_alloc");
    stop();
    return false;
  }
  Serial.printf("WAKE_RECORD_BUFFER bytes=%lu caps=%s\n",
                static_cast<unsigned long>(kMaxFrames * sizeof(int16_t)), caps);

  fetchDone_ = xSemaphoreCreateBinary();
  feedDone_ = xSemaphoreCreateBinary();
  if (fetchDone_ == nullptr || feedDone_ == nullptr) {
    Serial.println("WAKE_START_FAILED reason=semaphore");
    stop();
    return false;
  }

  state_ = State::kIdle;
  startedUs_ = esp_timer_get_time();
  reportUs_ = startedUs_;
  reportedFeedUs_ = 0;
  reportedFrames_ = 0;
  lastWakeUs_ = 0;

  if (xTaskCreatePinnedToCore(feedTaskEntry, "wake_feed", 4096, this, 5,
                              &feedTask_, 1) != pdPASS) {
    Serial.println("WAKE_START_FAILED reason=feed_task");
    stop();
    return false;
  }
  if (xTaskCreatePinnedToCore(fetchTaskEntry, "wake_fetch", 8192, this, 4,
                              &fetchTask_, 0) != pdPASS) {
    Serial.println("WAKE_START_FAILED reason=fetch_task");
    stop();
    return false;
  }

  running_ = true;
  Serial.printf("WAKE_READY model=%s state=idle internal_free=%u "
                "psram_free=%u\n",
                wnName_, static_cast<unsigned>(internalFree()),
                static_cast<unsigned>(psramFree()));
  return true;
}

void Engine::stop() {
  if (state_ == State::kStopped && !running_ && !i2sInstalled_) return;

  // Stop fetch first but keep feeding audio: a blocked afe->fetch() must be
  // able to return one more frame before the feed task is allowed to exit.
  fetchStop_ = true;
  suppressed_ = true;
  if (fetchTask_ != nullptr && fetchDone_ != nullptr) {
    if (xSemaphoreTake(fetchDone_, pdMS_TO_TICKS(3000)) != pdTRUE) {
      Serial.println("WAKE_STOP_TIMEOUT task=fetch");
    }
  }
  fetchTask_ = nullptr;

  feedStop_ = true;
  if (feedTask_ != nullptr && feedDone_ != nullptr) {
    if (xSemaphoreTake(feedDone_, pdMS_TO_TICKS(2000)) != pdTRUE) {
      Serial.println("WAKE_STOP_TIMEOUT task=feed");
    }
  }
  feedTask_ = nullptr;

  if (afeData_ != nullptr && afe_ != nullptr) {
    static_cast<const esp_afe_sr_iface_t*>(afe_)->destroy(
        static_cast<esp_afe_sr_data_t*>(afeData_));
    afeData_ = nullptr;
  }
  afe_ = nullptr;

  if (i2sInstalled_) {
    i2s_driver_uninstall(kPort);
    i2sInstalled_ = false;
  }
  if (buffer_ != nullptr) {
    heap_caps_free(buffer_);
    buffer_ = nullptr;
  }
  free(feed_);
  free(raw_);
  feed_ = nullptr;
  raw_ = nullptr;
  if (fetchDone_ != nullptr) {
    vSemaphoreDelete(fetchDone_);
    fetchDone_ = nullptr;
  }
  if (feedDone_ != nullptr) {
    vSemaphoreDelete(feedDone_);
    feedDone_ = nullptr;
  }

  frames_ = 0;
  crc_ = 0;
  preRollPos_ = 0;
  preRollTotal_ = 0;
  startRequest_ = false;
  stopRequest_ = false;
  releaseRequest_ = false;
  running_ = false;
  state_ = State::kStopped;
  suppressed_ = false;
  Serial.println("WAKE state=stopped");
}

void Engine::feedTaskEntry(void* arg) {
  static_cast<Engine*>(arg)->feedLoop();
}

void Engine::fetchTaskEntry(void* arg) {
  static_cast<Engine*>(arg)->fetchLoop();
}

void Engine::writePreRoll(const int16_t* samples, uint32_t count) {
  uint32_t pos = preRollPos_;
  for (uint32_t i = 0; i < count; ++i) {
    preRoll_[pos++] = samples[i];
    if (pos == kPreRollFrames) pos = 0;
  }
  preRollPos_ = pos;
  preRollTotal_ += count;
}

void Engine::beginFromPreRoll() {
  const uint32_t fill =
      preRollTotal_ >= kPreRollFrames ? kPreRollFrames : preRollTotal_;
  const uint32_t start =
      (preRollPos_ + kPreRollFrames - fill) % kPreRollFrames;
  for (uint32_t i = 0; i < fill; ++i) {
    buffer_[i] = preRoll_[(start + i) % kPreRollFrames];
  }
  frames_ = fill;
  crc_ = crc32Update(0xFFFFFFFFu, reinterpret_cast<const uint8_t*>(buffer_),
                     fill * sizeof(int16_t));
  __sync_synchronize();
  state_ = State::kRecording;
  Serial.printf("WAKE_RECORD_START preroll_samples=%lu\n",
                static_cast<unsigned long>(fill));
}

void Engine::appendSamples(const int16_t* samples, uint32_t count) {
  const uint32_t have = frames_;
  const uint32_t room = kMaxFrames - have;
  const uint32_t take = count < room ? count : room;
  if (take == 0) return;
  memcpy(buffer_ + have, samples, take * sizeof(int16_t));
  crc_ = crc32Update(crc_, reinterpret_cast<const uint8_t*>(samples),
                     take * sizeof(int16_t));
  frames_ = have + take;
}

void Engine::finalize(const char* reason) {
  const uint32_t samples = frames_;
  const uint32_t crc = ~crc_;
  crc_ = crc;
  __sync_synchronize();
  if (samples < kMinFrames) {
    state_ = State::kIdle;
    Serial.printf("WAKE_RECORD_ABORT reason=too_short samples=%lu bytes=%lu "
                  "min_samples=%lu\n",
                  static_cast<unsigned long>(samples),
                  static_cast<unsigned long>(samples * sizeof(int16_t)),
                  static_cast<unsigned long>(kMinFrames));
    return;
  }
  state_ = State::kReady;
  ++readyCount_;
  Serial.printf("WAKE_RECORD_DONE samples=%lu bytes=%lu ms=%lu crc32=%08lx "
                "reason=%s\n",
                static_cast<unsigned long>(samples),
                static_cast<unsigned long>(samples * sizeof(int16_t)),
                static_cast<unsigned long>(samples * 1000UL / kSampleRate),
                static_cast<unsigned long>(crc), reason);
}

void Engine::requestStart() {
  if (state_ == State::kArming) startRequest_ = true;
}

void Engine::requestStop() {
  if (state_ == State::kRecording) stopRequest_ = true;
}

void Engine::abortRecording(const char* reason) {
  if (state_ != State::kArming && state_ != State::kRecording) return;
  __sync_synchronize();
  state_ = State::kIdle;
  Serial.printf("WAKE_RECORD_ABORT reason=%s samples=%lu\n", reason,
                static_cast<unsigned long>(frames_));
}

void Engine::releaseRecording() {
  releaseRequest_ = true;
  if (!running_) state_ = State::kIdle;
}

const uint8_t* Engine::data() const {
  return state_ == State::kReady
             ? reinterpret_cast<const uint8_t*>(buffer_)
             : nullptr;
}

const char* Engine::stateName() const {
  switch (state_) {
    case State::kStopped: return "stopped";
    case State::kIdle: return "idle";
    case State::kArming: return "arming";
    case State::kRecording: return "recording";
    case State::kReady: return "ready";
  }
  return "unknown";
}

void Engine::feedLoop() {
  for (;;) {
    if (feedStop_) break;

    size_t bytesRead = 0;
    const esp_err_t err =
        i2s_read(kPort, raw_, sizeof(int32_t) * feedChunk_, &bytesRead,
                 pdMS_TO_TICKS(100));
    if (err != ESP_OK ||
        bytesRead < sizeof(int32_t) * static_cast<size_t>(feedChunk_)) {
      ++micErrors_;
      continue;
    }

    for (int i = 0; i < feedChunk_; ++i) {
      // INMP441 carries a 24-bit sample left-justified in a 32-bit slot.
      feed_[i] = static_cast<int16_t>(raw_[i] >> 16);
    }

    // Recorder first (same order as the verified probe), then AFE.
    if (state_ == State::kArming && startRequest_) {
      startRequest_ = false;
      beginFromPreRoll();
    }
    if (state_ == State::kRecording) {
      appendSamples(feed_, static_cast<uint32_t>(feedChunk_));
      if (frames_ >= kMaxFrames) {
        finalize("max_duration");
      } else if (stopRequest_) {
        stopRequest_ = false;
        finalize("silence");
      }
    } else {
      writePreRoll(feed_, static_cast<uint32_t>(feedChunk_));
    }
    if (state_ == State::kReady && releaseRequest_) {
      releaseRequest_ = false;
      state_ = State::kIdle;
    }

    const int64_t begin = esp_timer_get_time();
    const int ret = static_cast<const esp_afe_sr_iface_t*>(afe_)->feed(
        static_cast<esp_afe_sr_data_t*>(afeData_), feed_);
    const uint32_t elapsed = static_cast<uint32_t>(esp_timer_get_time() - begin);
    feedTotalUs_ += elapsed;
    if (elapsed > feedMaxUs_) feedMaxUs_ = elapsed;
    ++feedFrames_;
    if (ret < 0) ++micErrors_;
  }
  if (feedDone_ != nullptr) xSemaphoreGive(feedDone_);
  vTaskDelete(nullptr);
}

void Engine::fetchLoop() {
  const esp_afe_sr_iface_t* afe = static_cast<const esp_afe_sr_iface_t*>(afe_);
  esp_afe_sr_data_t* data = static_cast<esp_afe_sr_data_t*>(afeData_);
  bool listening = false;

  while (!fetchStop_) {
    afe_fetch_result_t* result = afe->fetch(data);
    if (fetchStop_) break;
    const int64_t now = esp_timer_get_time();

    if (result == nullptr) {
      ++fetchNulls_;
    } else if (result->wakeup_state == WAKENET_DETECTED) {
      if (now - lastWakeUs_ >= kWakeCooldownUs) {
        lastWakeUs_ = now;
        ++wakeCount_;
        Serial.printf(
            "WAKE_DETECTED count=%lu t_ms=%lld word_index=%d model_index=%d "
            "volume_db=%.1f\n",
            static_cast<unsigned long>(wakeCount_),
            static_cast<long long>((now - startedUs_) / 1000),
            result->wake_word_index, result->wakenet_model_index,
            result->data_volume);
        if (suppressed_) {
          ++ignoredCount_;
          Serial.println("WAKE_IGNORED reason=half_duplex");
        } else if (state_ != State::kIdle) {
          ++ignoredCount_;
          Serial.printf("WAKE_IGNORED reason=record_%s\n", stateName());
        } else {
          state_ = State::kArming;
          armedUs_ = now;
          lastSpeechUs_ = now;
          listening = true;
          Serial.printf("WAKE_LISTEN ignore_ms=%lld no_speech_ms=%lld\n",
                        static_cast<long long>(kVadIgnoreUs / 1000),
                        static_cast<long long>(kNoSpeechUs / 1000));
        }
      }
    }

    // VAD start/end. Only the fetch task reads vad_state; the feed task owns
    // the PCM buffer and performs the actual start/finalize transitions.
    if (result != nullptr && listening) {
      const bool speech = result->vad_state == AFE_VAD_SPEECH;
      if (state_ == State::kArming) {
        if (now - armedUs_ >= kVadIgnoreUs && speech) {
          lastSpeechUs_ = now;
          requestStart();
          Serial.printf("WAKE_SPEECH_START after_ms=%lld\n",
                        static_cast<long long>((now - armedUs_) / 1000));
        } else if (now - armedUs_ >= kNoSpeechUs) {
          abortRecording("no_speech");
          listening = false;
        }
      } else if (state_ == State::kRecording) {
        if (speech) {
          lastSpeechUs_ = now;
        } else if (now - lastSpeechUs_ >= kSilenceHangoverUs) {
          requestStop();
          Serial.printf("WAKE_SILENCE_END hangover_ms=%lld samples=%lu\n",
                        static_cast<long long>(kSilenceHangoverUs / 1000),
                        static_cast<unsigned long>(frames_));
          listening = false;
        }
      } else {
        listening = false;
      }
    }

    if (now - reportUs_ >= kReportPeriodUs) {
      const uint32_t windowFrames = feedFrames_ - reportedFrames_;
      const uint32_t windowUs = feedTotalUs_ - reportedFeedUs_;
      const float avgMs =
          windowFrames == 0 ? 0.0f
                            : static_cast<float>(windowUs) / windowFrames /
                                  1000.0f;
      reportedFrames_ = feedFrames_;
      reportedFeedUs_ = feedTotalUs_;
      Serial.printf(
          "WAKE_STAT feed_frames=%lu window=%lu avg_feed_ms=%.2f "
          "max_feed_ms=%.2f wakes=%lu ignored=%lu fetch_null=%lu mic_err=%lu "
          "record=%s samples=%lu suppressed=%u internal_free=%u psram_free=%u\n",
          static_cast<unsigned long>(feedFrames_),
          static_cast<unsigned long>(windowFrames),
          static_cast<double>(avgMs),
          static_cast<double>(feedMaxUs_) / 1000.0,
          static_cast<unsigned long>(wakeCount_),
          static_cast<unsigned long>(ignoredCount_),
          static_cast<unsigned long>(fetchNulls_),
          static_cast<unsigned long>(micErrors_), stateName(),
          static_cast<unsigned long>(frames_), suppressed_ ? 1U : 0U,
          static_cast<unsigned>(internalFree()),
          static_cast<unsigned>(psramFree()));
      reportUs_ = now;
    }
  }
  if (fetchDone_ != nullptr) xSemaphoreGive(fetchDone_);
  vTaskDelete(nullptr);
}

void Engine::printStatus() const {
  const float avgMs =
      feedFrames_ == 0
          ? 0.0f
          : static_cast<float>(feedTotalUs_) / feedFrames_ / 1000.0f;
  Serial.printf(
      "WAKE state=%s model=%s installed=%u suppressed=%u record=%s "
      "record_samples=%lu record_crc32=%08lx wakes=%lu ignored=%lu errors=%lu "
      "feed_frames=%lu avg_feed_ms=%.2f max_feed_ms=%.2f\n",
      running_ ? "running" : "stopped",
      wnName_ == nullptr ? "nihaoxiaozhi" : wnName_,
      i2sInstalled_ ? 1U : 0U, suppressed_ ? 1U : 0U, stateName(),
      static_cast<unsigned long>(frames_),
      static_cast<unsigned long>(crc_),
      static_cast<unsigned long>(wakeCount_),
      static_cast<unsigned long>(ignoredCount_),
      static_cast<unsigned long>(micErrors_),
      static_cast<unsigned long>(feedFrames_), static_cast<double>(avgMs),
      static_cast<double>(feedMaxUs_) / 1000.0);
}

}  // namespace wake
