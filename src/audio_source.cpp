#include "audio_source.h"

#include <cmath>

namespace audio {
namespace {

constexpr float kTwoPi = 6.28318530718f;
// 5 ms linear ramps remove the click that a hard start/stop would produce.
constexpr uint32_t kFadeMs = 5;

int16_t scaleSample(int16_t sample, uint8_t percent) {
  const int32_t scaled =
      static_cast<int32_t>(sample) * static_cast<int32_t>(percent) / 100;
  if (scaled > 32767) return 32767;
  if (scaled < -32768) return -32768;
  return static_cast<int16_t>(scaled);
}

}  // namespace

ToneSource::ToneSource(uint32_t sampleRate, uint16_t toneHz, uint16_t durationMs,
                       uint8_t amplitudePercent)
    : sampleRate_(sampleRate),
      toneHz_(toneHz),
      totalFrames_(static_cast<uint32_t>(
          static_cast<uint64_t>(sampleRate) * durationMs / 1000)),
      amplitude_(32767L * amplitudePercent / 100) {}

void ToneSource::restart() {
  rendered_ = 0;
  phase_ = 0.0f;
}

size_t ToneSource::fill(int16_t* stereo, size_t maxFrames) {
  if (rendered_ >= totalFrames_) return 0;
  const uint32_t remaining = totalFrames_ - rendered_;
  const size_t frames = remaining < maxFrames ? remaining : maxFrames;
  const float step = kTwoPi * static_cast<float>(toneHz_) /
                     static_cast<float>(sampleRate_);
  const uint32_t fadeFrames = sampleRate_ * kFadeMs / 1000 > 0
                                  ? sampleRate_ * kFadeMs / 1000
                                  : 1;

  for (size_t i = 0; i < frames; ++i) {
    const uint32_t index = rendered_ + static_cast<uint32_t>(i);
    float envelope = 1.0f;
    if (index < fadeFrames) {
      envelope = static_cast<float>(index) / static_cast<float>(fadeFrames);
    }
    const uint32_t tail = totalFrames_ - 1 - index;
    if (tail < fadeFrames) {
      const float fadeOut = static_cast<float>(tail) / static_cast<float>(fadeFrames);
      if (fadeOut < envelope) envelope = fadeOut;
    }
    const int16_t sample = static_cast<int16_t>(
        sinf(phase_) * static_cast<float>(amplitude_) * envelope);
    stereo[i * kChannels] = sample;
    stereo[i * kChannels + 1] = sample;
    phase_ += step;
    if (phase_ >= kTwoPi) phase_ -= kTwoPi;
  }

  rendered_ += static_cast<uint32_t>(frames);
  return frames;
}

bool FlashClipSource::setClip(const Clip& clip, uint32_t expectedSampleRate) {
  valid_ = false;
  clip_ = {};
  frames_ = 0;
  frameOffset_ = 0;
  if (clip.name == nullptr || clip.data == nullptr) return false;
  if (clip.bytes == 0 || (clip.bytes % sizeof(int16_t)) != 0) return false;
  if (clip.sampleRate != expectedSampleRate) return false;
  if (clip.volumePercent == 0 || clip.volumePercent > 100) return false;
  clip_ = clip;
  frames_ = clip.bytes / sizeof(int16_t);
  valid_ = true;
  return true;
}

void FlashClipSource::restart() { frameOffset_ = 0; }

size_t FlashClipSource::fill(int16_t* stereo, size_t maxFrames) {
  if (!valid_ || frameOffset_ >= frames_) return 0;
  const uint32_t remaining = frames_ - frameOffset_;
  const size_t frames = remaining < maxFrames ? remaining : maxFrames;
  // Advance by bytes: clip_.data is uint8_t*, so frameOffset_ * 2 is the byte
  // offset. A future source may hand back frames from a ring buffer instead.
  memcpy_P(mono_, clip_.data + frameOffset_ * sizeof(int16_t),
           frames * sizeof(int16_t));
  for (size_t i = 0; i < frames; ++i) {
    const int16_t sample = scaleSample(mono_[i], clip_.volumePercent);
    stereo[i * kChannels] = sample;
    stereo[i * kChannels + 1] = sample;
  }
  frameOffset_ += static_cast<uint32_t>(frames);
  return frames;
}

}  // namespace audio
