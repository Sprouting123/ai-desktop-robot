#pragma once
#include <Arduino.h>
#include <driver/i2s.h>

namespace audio {

// MAX98357A first-test wiring and tone parameters. The amplifier has no
// configuration bus: it derives everything from BCLK/LRC/DIN, so the safest
// first test is a standard I2S stream at a low amplitude.
struct Config {
  uint8_t bclkPin;
  uint8_t lrckPin;
  uint8_t dataPin;
  i2s_port_t port;
  uint32_t sampleRate;
  uint16_t toneHz;
  uint16_t durationMs;
  uint8_t amplitudePercent;  // Of full scale; deliberately far below maximum.
  uint8_t dmaBufferCount;
};

// GPIO6/7/15 do not overlap the OLED (8/9), servo (4/5) or RGB (48) paths.
// 16 kHz / 16 bit / stereo is a standard I2S format that the MAX98357A accepts
// without a configuration channel. Both channels carry the same sample, so the
// default left/right/(L+R) modes of the common breakout all produce the tone.
constexpr Config kDefaultConfig = {
    7,    // BCLK
    15,   // LRC
    6,    // DIN
    I2S_NUM_0,
    16000,
    880,   // A5, comfortably inside the speaker's range
    300,   // Short prompt only; no automatic playback at boot
    15,    // About -16.5 dBFS; the first test must not be loud
    4,     // DMA buffers of kChunkFrames each
};

// One chunk is 15 ms at 16 kHz. The DMA queue holds four chunks, so a busy
// loop can be late by roughly 45 ms without starving the stream.
constexpr size_t kChunkFrames = 240;
constexpr size_t kChannels = 2;

// Owns the ESP-IDF I2S TX driver in Arduino-ESP32 2.0.17 (legacy driver API).
// Playback is generated in small chunks from loop(); nothing here waits for
// the DMA to drain or for a whole tone to finish.
class Engine {
 public:
  explicit Engine(const Config& config = kDefaultConfig) : config_(config) {}
  ~Engine() { end(); }

  // Installs the driver and zeroes the DMA buffers. No tone is produced and
  // the amplifier sees silence until an explicit beep().
  bool begin();
  // Starts (or restarts) one finite tone. Retries initialization once per call
  // so a transient failure at boot does not require a reset.
  bool beep();
  // Stops immediately and clears the DMA buffers; safe in any state.
  void stop();
  void update();  // Non-blocking; call every loop().
  void end();     // Releases the I2S driver; used by the destructor.

  void printStatus() const;
  bool ready() const { return ready_; }
  bool playing() const { return playing_; }
  const char* state() const;
  uint32_t plays() const { return plays_; }
  uint32_t errors() const { return errors_; }
  uint16_t toneHz() const { return config_.toneHz; }
  uint16_t durationMs() const { return config_.durationMs; }
  uint8_t amplitudePercent() const { return config_.amplitudePercent; }

 private:
  bool install();
  void uninstall();
  void renderChunk();
  void finishTone();
  void clearDma();

  Config config_;
  int16_t chunk_[kChunkFrames * kChannels] = {};
  size_t chunkBytes_ = 0;
  size_t chunkSent_ = 0;
  uint32_t totalFrames_ = 0;
  uint32_t framesRendered_ = 0;
  float phase_ = 0.0f;
  bool ready_ = false;
  bool playing_ = false;
  uint32_t plays_ = 0;
  uint32_t stops_ = 0;
  uint32_t errors_ = 0;
  int32_t lastErrorCode_ = 0;
};

}  // namespace audio
