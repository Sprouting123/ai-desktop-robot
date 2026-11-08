#pragma once
#include <Arduino.h>
#include <driver/i2s.h>

#include "audio_source.h"

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

// Owns the ESP-IDF I2S TX driver in Arduino-ESP32 2.0.17 (legacy driver API)
// and the I2S/DMA output layer. Playback content comes from a Source: the
// built-in tone today, a flash PCM clip for `audio hello`, and eventually a
// Wi-Fi/Opus decode source without changing this class's write path.
class Engine {
 public:
  explicit Engine(const Config& config = kDefaultConfig);
  ~Engine() { end(); }

  // Installs the driver and zeroes the DMA buffers. No sound is produced and
  // the amplifier sees silence until an explicit beep() or playClip().
  bool begin();
  // Starts (or restarts) one finite tone. Retries initialization once per call
  // so a transient failure at boot does not require a reset.
  bool beep();
  // Starts (or restarts) a validated mono PCM clip. Returns false if the driver
  // is unavailable or the clip metadata is invalid; nothing is played then.
  bool playClip(const Clip& clip);
  // Stops immediately and clears the DMA buffers; safe in any state.
  void stop();
  void update();  // Non-blocking; call every loop().
  void end();     // Releases the I2S driver; used by the destructor.

  void printStatus() const;
  bool ready() const { return ready_; }
  bool playing() const { return playing_; }
  const char* state() const;
  const char* sourceName() const;
  const char* clipName() const;
  uint32_t clipBytes() const;
  uint32_t clipFrames() const;
  uint32_t plays() const { return plays_; }
  uint32_t errors() const { return errors_; }
  uint16_t toneHz() const { return config_.toneHz; }
  uint16_t durationMs() const { return config_.durationMs; }
  uint8_t amplitudePercent() const { return config_.amplitudePercent; }

 private:
  bool install();
  void uninstall();
  void clearDma();
  void startSource(Source* source);
  void finishPlayback();
  uint32_t drainMs() const;

  Config config_;
  ToneSource tone_;
  FlashClipSource clip_;
  Source* active_ = nullptr;
  int16_t chunk_[kChunkFrames * kChannels] = {};
  size_t chunkBytes_ = 0;
  size_t chunkSent_ = 0;
  uint32_t drainStartMs_ = 0;
  bool ready_ = false;
  bool playing_ = false;
  bool draining_ = false;
  uint32_t plays_ = 0;
  uint32_t stops_ = 0;
  uint32_t errors_ = 0;
  int32_t lastErrorCode_ = 0;
};

}  // namespace audio
