#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <stdint.h>

#include "record_source.h"

// Experiment 016 phase 5: offline WakeNet9 ("你好小智") with AFE VAD
// variable-length recording, integrated into the Arduino main firmware through
// the Route A link. The engine owns I2S_NUM_1 while it runs; mic::Engine and
// wake::Engine are therefore mutually exclusive and main.cpp enforces that.
namespace wake {

constexpr uint32_t kSampleRate = 16000;
constexpr uint32_t kMaxFrames = 160000;   // 10.0 s including the pre-roll.
constexpr uint32_t kMinFrames = 9600;     // 0.6 s minimum uploadable clip.
constexpr uint32_t kPreRollFrames = 8000; // 0.5 s ring before VAD start.

enum class State : uint8_t {
  kStopped,    // No tasks, no I2S driver, no AFE.
  kIdle,       // Listening for the wake word.
  kArming,     // Wake word detected; ignoring its tail, waiting for speech.
  kRecording,  // VAD detected speech; feed task is filling the buffer.
  kReady,      // Complete clip waiting for the automatic upload.
};

// Owns the microphone I2S port, the AFE/WakeNet instance and two tasks. The
// feed task is the only writer of the recording buffer (pre-roll, append and
// finalize), matching the verified probe design. The fetch task only observes
// AFE results and sets request flags.
class Engine : public audio_record::Source {
 public:
  Engine();
  ~Engine();

  // Reports the plan only; no driver, model or task is installed at boot.
  void begin();

  // Installs I2S_NUM_1, loads the model list from the `model` partition,
  // creates AFE and starts both tasks. Idempotent while running. Returns false
  // with a reason printed to the serial console.
  bool start();
  // Cooperative shutdown: keeps feeding audio until the blocked fetch returns,
  // waits for both tasks to exit, then destroys AFE and uninstalls I2S.
  void stop();

  // Half-duplex guard. While true, a detected wake word is logged and ignored.
  // main.cpp sets this during upload, reply download, playback and a short
  // post-playback cooldown so the speaker cannot wake the robot.
  void setSuppressed(bool suppressed) { suppressed_ = suppressed; }
  bool suppressed() const { return suppressed_; }

  // Experiment 017 follow-up turns: after an answer, main.cpp opens a short
  // listening window in which speech starts a new recording without the wake
  // word. The request is accepted only while idle and not suppressed; the
  // fetch task performs the transition. Returns false when it was not accepted.
  bool requestFollowUp(uint32_t windowMs);
  bool followUpActive() const { return followUpActive_; }

  bool running() const { return running_; }
  State state() const { return state_; }
  const char* stateName() const;

  // audio_record::Source: only a finalized clip is visible to the uploader.
  bool hasRecording() const override { return state_ == State::kReady; }
  bool captureBusy() const override {
    return state_ == State::kArming || state_ == State::kRecording;
  }
  bool dumpActive() const override { return false; }
  const uint8_t* data() const override;
  uint32_t bytes() const override { return frames_ * sizeof(int16_t); }
  uint32_t frames() const override { return frames_; }
  uint32_t sampleRate() const override { return kSampleRate; }
  uint32_t crc32() const override { return crc_; }

  // Increments once per finalized recording. main.cpp uses it to start exactly
  // one automatic upload per clip.
  uint32_t readyCount() const { return readyCount_; }
  // Main calls this after the upload reached a final state. The clip stays in
  // RAM until the next finalized recording overwrites it.
  void releaseRecording();

  uint32_t wakeCount() const { return wakeCount_; }
  uint32_t ignoredCount() const { return ignoredCount_; }
  uint32_t errorCount() const { return micErrors_; }
  // Increments only when a detected wake word actually armed listening (not
  // when it was ignored). main.cpp uses it to drive the acknowledgement cue.
  uint32_t listenCount() const { return listenCount_; }
  uint32_t followUpCount() const { return followUpCount_; }

  void printStatus() const;

 private:
  static void feedTaskEntry(void* arg);
  static void fetchTaskEntry(void* arg);
  void feedLoop();
  void fetchLoop();

  bool installI2s();
  bool loadModels();
  bool createAfe();

  // Feed-task side of the recorder (sole writer of buffer_).
  void requestStart();
  void requestStop();
  void abortRecording(const char* reason);
  void beginFromPreRoll();
  void appendSamples(const int16_t* samples, uint32_t count);
  void finalize(const char* reason);
  void writePreRoll(const int16_t* samples, uint32_t count);

  void logMemory(const char* tag) const;

  const char* wnName_ = nullptr;
  void* models_ = nullptr;   // srmodel_list_t*, kept for the engine lifetime.
  const void* afe_ = nullptr; // esp_afe_sr_iface_t*
  void* afeData_ = nullptr;   // esp_afe_sr_data_t*
  int feedChunk_ = 0;
  int fetchChunk_ = 0;
  int16_t* feed_ = nullptr;
  int32_t* raw_ = nullptr;
  TaskHandle_t feedTask_ = nullptr;
  TaskHandle_t fetchTask_ = nullptr;
  SemaphoreHandle_t fetchDone_ = nullptr;
  SemaphoreHandle_t feedDone_ = nullptr;

  int16_t* buffer_ = nullptr;  // PSRAM preferred; kMaxFrames samples.
  int16_t preRoll_[kPreRollFrames] = {};

  volatile State state_ = State::kStopped;
  volatile bool running_ = false;
  volatile bool i2sInstalled_ = false;
  volatile bool fetchStop_ = false;
  volatile bool feedStop_ = false;
  volatile bool suppressed_ = false;
  volatile bool startRequest_ = false;
  volatile bool stopRequest_ = false;
  volatile bool releaseRequest_ = false;
  volatile bool listenActive_ = false;
  volatile bool followUpRequest_ = false;
  volatile bool followUpActive_ = false;
  volatile uint32_t followUpWindowUs_ = 0;
  volatile uint32_t listenCount_ = 0;
  volatile uint32_t followUpCount_ = 0;
  volatile uint32_t frames_ = 0;
  volatile uint32_t crc_ = 0;
  volatile uint32_t preRollPos_ = 0;
  volatile uint32_t preRollTotal_ = 0;
  volatile uint32_t readyCount_ = 0;
  volatile uint32_t wakeCount_ = 0;
  volatile uint32_t ignoredCount_ = 0;
  volatile uint32_t micErrors_ = 0;
  volatile uint32_t feedFrames_ = 0;
  volatile uint32_t feedTotalUs_ = 0;
  volatile uint32_t feedMaxUs_ = 0;
  volatile uint32_t fetchNulls_ = 0;

  int64_t startedUs_ = 0;
  int64_t armedUs_ = 0;
  int64_t lastSpeechUs_ = 0;
  int64_t lastWakeUs_ = 0;
  int64_t reportUs_ = 0;
  int64_t reportedFeedUs_ = 0;
  uint32_t reportedFrames_ = 0;
  uint32_t lastReadyCountPrinted_ = 0;
};

}  // namespace wake
