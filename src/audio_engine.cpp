#include "audio_engine.h"

#include <cstring>

namespace audio {

Engine::Engine(const Config& config)
    : config_(config),
      tone_(config.sampleRate, config.toneHz, config.durationMs,
            config.amplitudePercent) {}

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
  // clip cannot loop as a buzz if loop() is briefly late.
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
  draining_ = false;
  active_ = nullptr;
  chunkBytes_ = 0;
  chunkSent_ = 0;
}

void Engine::end() {
  if (ready_) uninstall();
}

bool Engine::beep() {
  if (!ready_ && !begin()) return false;
  startSource(&tone_);
  return true;
}

bool Engine::playClip(const Clip& clip) {
  if (!ready_ && !begin()) return false;
  if (!clip_.setClip(clip, config_.sampleRate)) {
    // Invalid metadata (null pointer, odd byte count, wrong rate, bad volume)
    // is rejected before any read, so it can never index past the asset.
    ++errors_;
    return false;
  }
  startSource(&clip_);
  return true;
}

void Engine::startSource(Source* source) {
  // A new trigger owns the output immediately: forget any partially written
  // chunk, flush stale DMA data and start the source from its first frame.
  playing_ = false;
  draining_ = false;
  active_ = source;
  source->restart();
  chunkBytes_ = 0;
  chunkSent_ = 0;
  clearDma();
  playing_ = true;
  ++plays_;
}

void Engine::stop() {
  if (!playing_ && !ready_) return;
  playing_ = false;
  draining_ = false;
  active_ = nullptr;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  if (ready_) clearDma();
  ++stops_;
}

void Engine::clearDma() {
  if (ready_) i2s_zero_dma_buffer(config_.port);
}

uint32_t Engine::drainMs() const {
  if (config_.sampleRate == 0) return 100;
  // After the final write the DMA queue can still hold up to dmaBufferCount
  // chunks. Wait out that bounded tail instead of zeroing the DMA, which would
  // cut the last syllable. tx_desc_auto_clear outputs silence afterwards.
  return static_cast<uint32_t>(
             (1000ULL * config_.dmaBufferCount * kChunkFrames) /
             config_.sampleRate) +
         20;
}

void Engine::update() {
  if (!ready_ || !playing_) return;

  if (draining_) {
    // The source is exhausted and every byte is queued. Keep reporting
    // "playing" until the worst-case queue tail has reached the amplifier.
    if (static_cast<uint32_t>(millis() - drainStartMs_) >= drainMs()) {
      finishPlayback();
    }
    return;
  }

  if (chunkSent_ >= chunkBytes_) {
    if (active_ == nullptr) {
      finishPlayback();
      return;
    }
    const size_t frames = active_->fill(chunk_, kChunkFrames);
    if (frames == 0) {
      draining_ = true;
      drainStartMs_ = millis();
      return;
    }
    chunkBytes_ = frames * kChannels * sizeof(int16_t);
    chunkSent_ = 0;
  }

  size_t written = 0;
  // chunkSent_ is a byte count, so the pointer must advance in bytes. Using
  // chunk_ + chunkSent_ would advance int16_t elements (twice the intended
  // offset) after a partial write.
  const uint8_t* cursor = reinterpret_cast<const uint8_t*>(chunk_) + chunkSent_;
  // Zero ticks: if the DMA queue is full this returns immediately and the
  // remainder is retried next loop. It never waits for the amplifier.
  const esp_err_t err = i2s_write(config_.port, cursor,
                                  chunkBytes_ - chunkSent_, &written, 0);
  if (written > 0) chunkSent_ += written;
  if (err == ESP_OK || err == ESP_ERR_TIMEOUT) return;  // Timeout = queue full.
  lastErrorCode_ = err;
  ++errors_;
  playing_ = false;
  draining_ = false;
  active_ = nullptr;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  clearDma();
}

void Engine::finishPlayback() {
  playing_ = false;
  draining_ = false;
  active_ = nullptr;
  chunkBytes_ = 0;
  chunkSent_ = 0;
  // Deliberately no i2s_zero_dma_buffer(): the queued tail has been given its
  // full drain time, and tx_desc_auto_clear keeps the idle stream silent.
}

const char* Engine::state() const {
  if (playing_) return "playing";
  return ready_ ? "idle" : "unavailable";
}

const char* Engine::sourceName() const {
  if (active_ == &tone_) return "tone";
  if (active_ == &clip_) return "clip";
  return "none";
}

const char* Engine::clipName() const {
  if (active_ == &clip_ && clip_.valid()) return clip_.clip().name;
  return "-";
}

uint32_t Engine::clipBytes() const {
  if (active_ == &clip_ && clip_.valid()) return clip_.clip().bytes;
  return 0;
}

uint32_t Engine::clipFrames() const {
  if (active_ == &tone_) return tone_.totalFrames();
  if (active_ == &clip_) return clip_.totalFrames();
  return 0;
}

void Engine::printStatus() const {
  Serial.printf(
      "AUDIO state=%s ready=%u source=%s clip=%s bytes=%lu frames=%lu "
      "driver=i2s_std bclk=%u lrck=%u din=%u rate_hz=%lu bits=16 channels=2 "
      "tone_hz=%u duration_ms=%u amplitude_pct=%u plays=%lu stops=%lu "
      "errors=%lu last_error=%ld\n",
      state(), ready_ ? 1U : 0U, sourceName(), clipName(),
      static_cast<unsigned long>(clipBytes()),
      static_cast<unsigned long>(clipFrames()), config_.bclkPin,
      config_.lrckPin, config_.dataPin,
      static_cast<unsigned long>(config_.sampleRate), config_.toneHz,
      config_.durationMs, config_.amplitudePercent,
      static_cast<unsigned long>(plays_), static_cast<unsigned long>(stops_),
      static_cast<unsigned long>(errors_), static_cast<long>(lastErrorCode_));
}

}  // namespace audio
