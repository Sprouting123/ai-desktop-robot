#pragma once
#include <Arduino.h>
#include <WiFi.h>

#include "audio_engine.h"
#include "audio_uploader.h"

// Experiment 015: download the latest TTS reply from the trusted-LAN receiver
// and play it through the existing AudioEngine. The PCM buffer lives in PSRAM
// and is wrapped in an audio::Clip, so no new I2S path is introduced.
namespace reply {

// Matches scripts/reply_store.py (60 s at 16 kHz, 16-bit mono). A larger
// Content-Length is rejected before allocating anything.
constexpr uint32_t kMaxPcmBytes = 16000 * 2 * 60;
constexpr uint32_t kSampleRate = 16000;
constexpr uint8_t kVolumePercent = 90;

class Client {
 public:
  enum class StartResult : uint8_t {
    Ok,
    Busy,
    NotConfigured,
    WifiDown,
    NoTurn,
  };

  Client(audio::Engine& audio, const upload::Client& uploader);
  ~Client();

  // Copies and validates the receiver settings. The token is kept in RAM only
  // and is never logged. A non-empty caCert enables HTTPS with verification
  // against that pinned CA; an empty/NULL caCert keeps plain HTTP.
  void begin(const char* host, uint16_t port, const char* token,
             const char* caCert = nullptr);

  // Manual download. Uses the turn reported by the last upload when available,
  // so a reply to an older recording cannot be mistaken for the new answer.
  StartResult fetchLatest();
  // Always requests the newest published reply (diagnostics only).
  StartResult fetchNewest();
  // Cancels a download or a pending poll; playback is not stopped.
  void cancel();

  // Plays (or replays) the cached reply without downloading again.
  bool play();
  // One bounded step per loop; never waits for the network or the DMA queue.
  void update();

  bool autoMode() const { return auto_; }
  void setAuto(bool enabled) { auto_ = enabled; }
  bool active() const;
  bool configured() const { return configured_; }
  bool hasClip() const { return buffer_ != nullptr; }
  bool playing() const;
  const char* stateName() const;
  void printStatus() const;

  static constexpr size_t kMaxToken = 64;

 private:
  enum class State : uint8_t {
    Idle,
    Connecting,
    Sending,
    Header,
    Body,
    Wait,
    Done,
    Failed,
  };

  static constexpr uint32_t kConnectTimeoutMs = 1000;
  static constexpr uint32_t kTlsConnectTimeoutMs = 4000;
  static constexpr uint32_t kTlsWriteTimeoutMs = 1000;
  static constexpr uint32_t kStallTimeoutMs = 5000;
  static constexpr uint32_t kAttemptTimeoutMs = 15000;
  static constexpr uint32_t kPollIntervalMs = 700;
  static constexpr uint32_t kPollTimeoutMs = 20000;
  static constexpr size_t kMaxHeaderBytes = 640;
  static constexpr size_t kReadChunkBytes = 2048;
  static constexpr size_t kMaxHost = 63;
  static constexpr size_t kMaxTurn = 40;

  StartResult start(const char* turn, bool polling, bool autoPlay);
  bool buildRequest();
  void startAttempt(uint32_t now);
  void parseHeader(uint32_t now);
  void readHeader(uint32_t now);
  void readBody(uint32_t now);
  void commit(uint32_t now);
  void fail(const char* reason);
  void closeSocket();
  void freePending();
  void pollAgain(uint32_t now);
  int transportWrite(const uint8_t* data, size_t length);

  audio::Engine& audio_;
  const upload::Client& uploader_;

  char host_[kMaxHost + 1] = {};
  char token_[kMaxToken + 1] = {};
  uint16_t port_ = 0;
  IPAddress address_;
  bool configured_ = false;
  bool https_ = false;
  bool auto_ = true;
  uint32_t seenUploads_ = 0;

  State state_ = State::Idle;
  WiFiClient plainClient_;
  WiFiClientSecure secureClient_;
  WiFiClient* client_ = &plainClient_;
  const char* caCert_ = nullptr;
  char request_[320] = {};
  size_t requestLength_ = 0;
  size_t requestSent_ = 0;
  char header_[kMaxHeaderBytes + 1] = {};
  size_t headerLength_ = 0;
  char turn_[kMaxTurn + 1] = {};
  bool hasTurn_ = false;
  bool polling_ = false;
  bool autoPlay_ = false;
  uint32_t pollDeadlineMs_ = 0;
  uint32_t waitUntilMs_ = 0;
  uint32_t lastProgressMs_ = 0;
  uint32_t attemptDeadlineMs_ = 0;
  char reason_[24] = {};

  uint8_t* pending_ = nullptr;
  uint32_t pendingBytes_ = 0;
  uint32_t expectedBytes_ = 0;
  uint32_t receivedBytes_ = 0;
  uint32_t headerFrames_ = 0;
  uint32_t headerRate_ = 0;
  uint32_t headerChannels_ = 0;
  uint32_t headerCrc_ = 0;

  uint8_t* buffer_ = nullptr;
  uint32_t replyBytes_ = 0;
  uint32_t replyFrames_ = 0;
  uint32_t replyCrc_ = 0;
  uint32_t replyDurationMs_ = 0;
  char pendingId_[kMaxTurn + 1] = {};
  char replyId_[kMaxTurn + 1] = {};
  audio::Clip clip_ = {};
  uint32_t fetches_ = 0;
  uint32_t plays_ = 0;
  uint32_t failures_ = 0;
};

}  // namespace reply
