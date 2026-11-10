#pragma once
#include <stdint.h>

// A completed PCM recording that the HTTP uploader can send without copying.
// mic::Engine (manual `mic record`) and wake::Engine (VAD recording after a
// wake word) both implement this view. The uploader only reads through this
// interface, so wake-initiated uploads reuse the exact same HTTP state machine
// and response validation as the experiment 013/015 path.
namespace audio_record {

class Source {
 public:
  virtual ~Source() {}

  // True only while a complete recording is available and stable.
  virtual bool hasRecording() const = 0;
  // True while capture is actively writing the buffer (arming or recording).
  virtual bool captureBusy() const = 0;
  // Only the manual microphone engine has the ASCII dump mode.
  virtual bool dumpActive() const = 0;

  virtual const uint8_t* data() const = 0;
  virtual uint32_t bytes() const = 0;
  virtual uint32_t frames() const = 0;
  virtual uint32_t sampleRate() const = 0;
  virtual uint32_t crc32() const = 0;
};

}  // namespace audio_record
