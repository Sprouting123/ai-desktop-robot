#pragma once
#include <Arduino.h>

#include "audio_source.h"

// The PCM asset is linked into flash by PlatformIO's `board_build.embed_files`
// (see platformio.ini). The linker exposes its bounds as symbols named after
// the asset path; the clip length is derived from the difference, so the
// firmware never hard-codes a size that could drift from the file.
extern "C" {
extern const uint8_t helloPcmStart[]
    asm("_binary_assets_audio_hello_zh_raw_start");
extern const uint8_t helloPcmEnd[]
    asm("_binary_assets_audio_hello_zh_raw_end");
}

namespace voice {

// 16 kHz, 16-bit signed little-endian, mono. See assets/audio/README.md for
// the TTS source, voice and conversion command.
constexpr uint32_t kSampleRate = 16000;
// Conservative level for the first listening test: the amplifier and the two
// servos share one 5V supply, and loud output draws the most current.
constexpr uint8_t kHelloVolumePercent = 60;

inline const audio::Clip& helloClip() {
  static const audio::Clip clip = {
      "hello_zh",
      helloPcmStart,
      static_cast<uint32_t>(helloPcmEnd - helloPcmStart),
      kSampleRate,
      kHelloVolumePercent,
  };
  return clip;
}

}  // namespace voice
