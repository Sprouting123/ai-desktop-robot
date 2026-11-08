#include "microphone_engine.h"

#include <cmath>

namespace mic {
namespace {
// INMP441 full scale is 24-bit two's complement. The sample is left-justified
// in a 32-bit slot, so an arithmetic shift by 8 recovers the signed 24-bit
// value without any floating-point conversion.
constexpr int32_t kFullScale = 8388608;  // 2^23
constexpr uint32_t kIdleReportMs = 0;    // Read timeout 0: never wait for data.

uint32_t percentOfFullScale(uint32_t value) {
  if (value >= static_cast<uint32_t>(kFullScale)) return 100;
  return static_cast<uint32_t>(static_cast<uint64_t>(value) * 100 /
                               static_cast<uint64_t>(kFullScale));
}
}  // namespace

Engine::Engine(const Config& config) : config_(config) {}

void Engine::begin() {
  // Configuration is reported at boot, but the driver is deliberately not
  // installed: no clocks, no DMA, no capture until `mic start`.
  Serial.printf(
      "MIC_CONFIG installed=0 port=%d bclk=%u ws=%u din=%u "
      "sample_rate_hz=%lu bits_per_slot=%u channel=right dma=%u x %u frames\n",
      static_cast<int>(config_.port), config_.bclkPin, config_.wsPin,
      config_.dataPin, static_cast<unsigned long>(config_.sampleRate),
      config_.bitsPerSlot, static_cast<unsigned>(config_.dmaBufferCount),
      static_cast<unsigned>(config_.blockFrames));
}

bool Engine::install() {
  i2s_config_t config = {};
  config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
  config.sample_rate = static_cast<int>(config_.sampleRate);
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  // L/R is tied to GND on the module, but this specimen delivers its data in
  // the right slot (measured 2026-11-08: left was all zero, right carried the
  // signal). Read the slot that actually carries samples.
  config.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = 0;
  config.dma_buf_count = config_.dmaBufferCount;
  config.dma_buf_len = config_.blockFrames;
  config.use_apll = false;
  config.tx_desc_auto_clear = false;  // RX-only port; no TX descriptors used.
  config.fixed_mclk = 0;
  config.mclk_multiple = I2S_MCLK_MULTIPLE_256;

  esp_err_t err = i2s_driver_install(config_.port, &config, 0, nullptr);
  if (err != ESP_OK) {
    lastErrorCode_ = err;
    ++errors_;
    failed_ = true;
    installed_ = false;
    return false;
  }

  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = config_.bclkPin;
  pins.ws_io_num = config_.wsPin;
  pins.data_out_num = I2S_PIN_NO_CHANGE;  // Never drive the shared data line.
  pins.data_in_num = config_.dataPin;
  err = i2s_set_pin(config_.port, &pins);
  if (err == ESP_OK) {
    // Mono matches ONLY_RIGHT: one 32-bit word per sample.
    err = i2s_set_clk(config_.port, config_.sampleRate,
                      I2S_BITS_PER_SAMPLE_32BIT, I2S_CHANNEL_MONO);
  }
  if (err != ESP_OK) {
    lastErrorCode_ = err;
    ++errors_;
    failed_ = true;
    i2s_driver_uninstall(config_.port);
    installed_ = false;
    return false;
  }

  installed_ = true;
  failed_ = false;
  Serial.printf(
      "MIC_INIT ready=1 port=%d bclk=%u ws=%u din=%u rate_hz=%lu "
      "bits_per_slot=%u channel=right\n",
      static_cast<int>(config_.port), config_.bclkPin, config_.wsPin,
      config_.dataPin, static_cast<unsigned long>(config_.sampleRate),
      config_.bitsPerSlot);
  return true;
}

void Engine::uninstall() {
  i2s_driver_uninstall(config_.port);
  installed_ = false;
  running_ = false;
}

void Engine::end() {
  if (installed_) uninstall();
}

bool Engine::start() {
  if (!installed_ && !install()) return false;
  if (!running_) {
    // The driver starts RX when installed; i2s_start is only needed after a
    // previous stop. Calling it again is harmless.
    const esp_err_t err = i2s_start(config_.port);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
      lastErrorCode_ = err;
      ++errors_;
      failed_ = true;
      return false;
    }
  }
  resetCapture();
  running_ = true;
  failed_ = false;
  return true;
}

void Engine::stop() {
  if (running_ && installed_) i2s_stop(config_.port);
  running_ = false;
}

void Engine::resetCapture() {
  windowHead_ = 0;
  windowCount_ = 0;
  windowSumSquares_ = 0;
  windowFrames_ = 0;
  windowPeak_ = 0;
  windowZeroBlocks_ = 0;
  totalFrames_ = 0;
  blocks_ = 0;
  zeroBlocks_ = 0;
  reads_ = 0;
  timeouts_ = 0;
}

void Engine::update() {
  if (!running_ || !installed_) return;

  size_t bytesRead = 0;
  // Zero ticks: if the DMA has no block ready, return immediately and try
  // again next loop. The main loop never waits for the microphone.
  const esp_err_t err =
      i2s_read(config_.port, words_, sizeof(words_), &bytesRead, kIdleReportMs);
  if (err == ESP_ERR_TIMEOUT) {
    ++timeouts_;
    return;
  }
  if (err != ESP_OK) {
    lastErrorCode_ = err;
    ++errors_;
    return;
  }
  const size_t frames = bytesRead / sizeof(int32_t);
  if (frames == 0) return;

  uint32_t peak = 0;
  uint64_t sumSquares = 0;
  bool allZero = true;
  for (size_t i = 0; i < frames; ++i) {
    // Sign-extending arithmetic shift of the 24-bit sample in bits 31..8.
    const int32_t sample = words_[i] >> 8;
    const uint32_t magnitude =
        sample < 0 ? static_cast<uint32_t>(-static_cast<int64_t>(sample))
                   : static_cast<uint32_t>(sample);
    if (magnitude > peak) peak = magnitude;
    if (magnitude != 0) allZero = false;
    sumSquares += static_cast<uint64_t>(magnitude) * magnitude;
  }

  ++reads_;
  blocks_ += 1;
  totalFrames_ += static_cast<uint32_t>(frames);
  if (allZero) ++zeroBlocks_;
  pushBlock(static_cast<uint32_t>(frames), peak, sumSquares, allZero);
}

void Engine::pushBlock(uint32_t frames, uint32_t peak, uint64_t sumSquares,
                       bool allZero) {
  const bool evicting = windowCount_ == kWindowBlocks;
  if (evicting) {
    const BlockStat& oldest = window_[windowHead_];
    windowSumSquares_ -= oldest.sumSquares;
    windowFrames_ -= oldest.frames;
    windowZeroBlocks_ -= oldest.zero;
  } else {
    ++windowCount_;
  }

  BlockStat& slot = window_[windowHead_];
  slot.frames = frames;
  slot.peak = peak;
  slot.sumSquares = sumSquares;
  slot.zero = allZero ? 1 : 0;

  windowSumSquares_ += sumSquares;
  windowFrames_ += frames;
  windowZeroBlocks_ += slot.zero;
  windowHead_ = static_cast<uint8_t>((windowHead_ + 1) % kWindowBlocks);

  if (evicting) {
    // A full ring evicts the oldest peak, which may have been the maximum.
    // Recompute so the reported peak always describes the current window.
    uint32_t recomputed = 0;
    for (uint8_t i = 0; i < kWindowBlocks; ++i) {
      if (window_[i].peak > recomputed) recomputed = window_[i].peak;
    }
    windowPeak_ = recomputed;
  } else if (peak > windowPeak_) {
    windowPeak_ = peak;
  }
}

const char* Engine::state() const {
  if (running_) return "running";
  return failed_ ? "error" : "idle";
}

const char* Engine::signalName() const {
  if (!running_) return "idle";
  if (windowFrames_ == 0) return "no_data";
  if (windowZeroBlocks_ == windowCount_) return "zero";
  return "ok";
}

void Engine::printStatus() const {
  Serial.printf(
      "MIC state=%s ready=%u port=%d bclk=%u ws=%u din=%u "
      "sample_rate_hz=%lu bits_per_sample=32 bits_per_slot=%u channel=right "
      "frames=%lu blocks=%lu reads=%lu timeouts=%lu zero_blocks=%lu "
      "errors=%lu last_error=%ld\n",
      state(), installed_ ? 1U : 0U, static_cast<int>(config_.port),
      config_.bclkPin, config_.wsPin, config_.dataPin,
      static_cast<unsigned long>(config_.sampleRate), config_.bitsPerSlot,
      static_cast<unsigned long>(totalFrames_),
      static_cast<unsigned long>(blocks_), static_cast<unsigned long>(reads_),
      static_cast<unsigned long>(timeouts_),
      static_cast<unsigned long>(zeroBlocks_),
      static_cast<unsigned long>(errors_), static_cast<long>(lastErrorCode_));
}

void Engine::printLevel() const {
  const uint32_t rms =
      windowFrames_ == 0
          ? 0
          : static_cast<uint32_t>(
                sqrt(static_cast<double>(windowSumSquares_) /
                     static_cast<double>(windowFrames_)));
  Serial.printf(
      "MIC_LEVEL state=%s signal=%s window_frames=%lu window_blocks=%u "
      "peak=%lu rms=%lu peak_pct=%lu rms_pct=%lu total_frames=%lu "
      "zero_blocks=%lu\n",
      state(), signalName(), static_cast<unsigned long>(windowFrames_),
      static_cast<unsigned>(windowCount_), static_cast<unsigned long>(windowPeak_),
      static_cast<unsigned long>(rms),
      static_cast<unsigned long>(percentOfFullScale(windowPeak_)),
      static_cast<unsigned long>(percentOfFullScale(rms)),
      static_cast<unsigned long>(totalFrames_),
      static_cast<unsigned long>(zeroBlocks_));
}

}  // namespace mic
