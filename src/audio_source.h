#pragma once
#include <Arduino.h>

namespace audio {

// One chunk is 15 ms at 16 kHz. Sources fill at most this many frames per
// loop() call, so no source can monopolize the main loop.
constexpr size_t kChunkFrames = 240;
constexpr size_t kChannels = 2;

// Immutable description of a mono 16-bit PCM clip stored in flash. `data`
// points at immutable memory (a linker-embedded asset today; a decoded buffer
// from a future network source can be wrapped the same way).
struct Clip {
  const char* name;
  const uint8_t* data;
  uint32_t bytes;
  uint32_t sampleRate;
  uint8_t volumePercent;
};

// Playback source boundary. The I2S output layer only knows this interface:
// it pulls stereo frames, never inspects where they came from, and never
// blocks. A future Wi-Fi/Opus source implements the same three methods.
class Source {
 public:
  virtual ~Source() {}
  virtual void restart() = 0;
  virtual uint32_t totalFrames() const = 0;
  // Writes up to maxFrames interleaved stereo frames and returns the frame
  // count. Returning 0 means the source has ended (or has no data yet); the
  // caller decides whether that ends playback.
  virtual size_t fill(int16_t* stereo, size_t maxFrames) = 0;
};

// Generated sine prompt. Same waveform as experiment 009 phase 1.
class ToneSource : public Source {
 public:
  ToneSource(uint32_t sampleRate, uint16_t toneHz, uint16_t durationMs,
             uint8_t amplitudePercent);
  void restart() override;
  uint32_t totalFrames() const override { return totalFrames_; }
  size_t fill(int16_t* stereo, size_t maxFrames) override;

 private:
  uint32_t sampleRate_;
  uint32_t toneHz_;
  uint32_t totalFrames_;
  uint32_t amplitude_;
  uint32_t rendered_ = 0;
  float phase_ = 0.0f;
};

// Read-only PCM clip stored in flash. Frames are copied one chunk at a time
// (never the whole clip), scaled by volumePercent, and expanded from mono to
// the stereo I2S stream.
class FlashClipSource : public Source {
 public:
  // Validates pointer, even byte count, sample rate and volume range. A
  // rejected clip never reaches the I2S layer, so a bad asset cannot cause an
  // out-of-bounds read.
  bool setClip(const Clip& clip, uint32_t expectedSampleRate);
  bool valid() const { return valid_; }
  const Clip& clip() const { return clip_; }
  void restart() override;
  uint32_t totalFrames() const override { return frames_; }
  size_t fill(int16_t* stereo, size_t maxFrames) override;

 private:
  Clip clip_ = {};
  uint32_t frames_ = 0;
  uint32_t frameOffset_ = 0;
  int16_t mono_[kChunkFrames] = {};
  bool valid_ = false;
};

}  // namespace audio
