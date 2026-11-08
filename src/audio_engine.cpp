#include "audio_engine.h"

#include <cmath>
#include <cstring>

namespace audio {
namespace {

constexpr float kTwoPi = 6.28318530718f;
// 5 ms linear ramps remove the click that a hard start/stop would produce.
constexpr uint32_t kFadeMs = 5;

}  // namespace

bool Engine::begin() {
  if (ready_) return true;
  const bool ok = install();
  Serial.printf(
      "AUDIO_INIT ready=%u driver=i2s_std port=%d bclk=%u lrck=%u din=%u "
      "rate_hz=%lu bits=16 channels=2 dma=%u x %u frames tone_hz=%u "
      "duration_ms=%u amplitude_pct=%u\n",
      ok ? 1U : 0U, static_cast<int>(config_.port), config_.bclkPin,
      config_.lrckPin, config_.dataPin,
      static_cast<unsigned long>(config_.sampleRate),
      static_cast<unsigned>(config_.dmaBufferCount),
      static_cast<unsigned>(kChunkFrames), config_.toneHz, config_.durationMs,
      config_.amplitudePercent);
  if (!ok) {
    Serial.printf("AUDIO_ERROR stage=init code=%ld\n",
                  static_cast<long>(lastErrorCode_));
  }
  return ok;
}

bool Engine::install() {
  i2s_config_t config = {};
  config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX);
  config.sample_rate = static_cast<int>(config_.sampleRate);
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;  // Stereo, duplicated data.
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = 0;  // No dedicated ISR priority requirement.
  config.dma_buf_count = config_.dmaBufferCount;
  config.dma_buf_len = kChunkFrames;
  config.use_apll = false;
  // Underrun outputs zeros instead of repeating the last buffer, so a finished
  // tone cannot loop as a buzz if loop() is briefly late.
  config.tx_desc_auto_clear = true;
  config.fixed_mclk = 0;
  config.mclk_multiple = I2S_MCLK_MULTIPLE_256;

  esp_err_t err = i2s_driver_install(config_.port, &config, 0, nullptr);
  if (err != ESP_OK) {
    lastErrorCode_ = err;
    ++errors_;
    ready_ = false;
    return false;
  }

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;  // MAX98357A needs only BCLK/LRC/DIN.
  pins.bck_io_num = config_.bclkPin;
  pins.ws_io_num = config_.lrckPin;
  pins.data_out_num = config_.dataPin;
  pins.data_in_num = I2S_PIN_NO_CHANGE;
  err = i2s_set_pin(config_.port, &pins);
  if (err == ESP_OK) err = i2s_set_clk(config_.port, config_.sampleRate,
                                       I2S_BITS_PER_SAMPLE_16BIT,
                                       I2S_CHANNEL_STEREO);
  if (err != ESP_OK) {
    lastErrorCode_ = err;
    ++errors_;
    uninstall();
    return false;
  }

  clearDma();
  ready_ = true;
  return true;
}

void Engine::uninstall() {
  i2s_driver_uninstall(config_.port);
  ready_ = false;
  playing_ = false;
  chunkBytes_ = 0;
  chunkSent_ = 0;
}

void Engine::end() {
  if (ready_) uninstall();
}

bool Engine::beep() {
  if (!ready_ && !begin()) return false;
  // Restarting an active tone is allowed: forget the old chunk and phase.
  playing_ = false;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  framesRendered_ = 0;
  phase_ = 0.0f;
  totalFrames_ = static_cast<uint32_t>(
      static_cast<uint64_t>(config_.sampleRate) * config_.durationMs / 1000);
  if (totalFrames_ == 0) return false;
  clearDma();
  renderChunk();
  playing_ = true;
  ++plays_;
  return true;
}

void Engine::stop() {
  if (!playing_ && !ready_) return;
  playing_ = false;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  if (ready_) clearDma();
  ++stops_;
}

void Engine::clearDma() {
  if (ready_) i2s_zero_dma_buffer(config_.port);
}

void Engine::renderChunk() {
  const uint32_t remaining = totalFrames_ - framesRendered_;
  const size_t frames = remaining < kChunkFrames ? remaining : kChunkFrames;
  const float step = kTwoPi * config_.toneHz / config_.sampleRate;
  const int32_t amplitude = 32767L * config_.amplitudePercent / 100;
  const uint32_t fadeFrames = config_.sampleRate * kFadeMs / 1000 > 0
                                  ? config_.sampleRate * kFadeMs / 1000
                                  : 1;

  for (size_t i = 0; i < frames; ++i) {
    const uint32_t index = framesRendered_ + static_cast<uint32_t>(i);
    float envelope = 1.0f;
    if (index < fadeFrames) {
      envelope = static_cast<float>(index) / static_cast<float>(fadeFrames);
    }
    const uint32_t tail = totalFrames_ - 1 - index;
    if (tail < fadeFrames) {
      const float fadeOut = static_cast<float>(tail) / static_cast<float>(fadeFrames);
      if (fadeOut < envelope) envelope = fadeOut;
    }
    const int16_t sample =
        static_cast<int16_t>(sinf(phase_) * static_cast<float>(amplitude) * envelope);
    chunk_[i * 2] = sample;
    chunk_[i * 2 + 1] = sample;
    phase_ += step;
    if (phase_ >= kTwoPi) phase_ -= kTwoPi;
  }

  framesRendered_ += static_cast<uint32_t>(frames);
  chunkBytes_ = frames * kChannels * sizeof(int16_t);
  chunkSent_ = 0;
}

void Engine::update() {
  if (!ready_ || !playing_) return;
  if (chunkSent_ >= chunkBytes_) {
    if (framesRendered_ >= totalFrames_) {
      finishTone();
      return;
    }
    renderChunk();
  }

  size_t written = 0;
  // Zero ticks: if the DMA queue is full this returns immediately and the
  // remainder is retried next loop. It never waits for the amplifier.
  const esp_err_t err = i2s_write(config_.port, chunk_ + chunkSent_,
                                  chunkBytes_ - chunkSent_, &written, 0);
  if (written > 0) chunkSent_ += written;
  if (err == ESP_OK || err == ESP_ERR_TIMEOUT) return;  // Timeout = queue full.
  lastErrorCode_ = err;
  ++errors_;
  playing_ = false;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  clearDma();
}

void Engine::finishTone() {
  playing_ = false;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  // The tone already ends in a fade-out, but clearing the DMA guarantees that
  // the idle state is true silence.
  clearDma();
}

const char* Engine::state() const {
  if (playing_) return "playing";
  return ready_ ? "idle" : "unavailable";
}

void Engine::printStatus() const {
  Serial.printf(
      "AUDIO state=%s ready=%u driver=i2s_std bclk=%u lrck=%u din=%u "
      "rate_hz=%lu bits=16 channels=2 tone_hz=%u duration_ms=%u "
      "amplitude_pct=%u plays=%lu stops=%lu errors=%lu last_error=%ld\n",
      state(), ready_ ? 1U : 0U, config_.bclkPin, config_.lrckPin,
      config_.dataPin, static_cast<unsigned long>(config_.sampleRate),
      config_.toneHz, config_.durationMs, config_.amplitudePercent,
      static_cast<unsigned long>(plays_), static_cast<unsigned long>(stops_),
      static_cast<unsigned long>(errors_), static_cast<long>(lastErrorCode_));
}

}  // namespace audio
