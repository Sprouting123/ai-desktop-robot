#pragma once
#include <Arduino.h>
#include <WiFi.h>

#include "microphone_engine.h"

namespace upload {

// Uploads a completed microphone recording to a trusted-LAN HTTP receiver.
// The recording stays in the existing PSRAM buffer; this class never copies it
// and never starts capture. Transfer is a small non-blocking state machine so
// the OLED, servos and audio continue to run. The only blocking step is the
// TCP connect, bounded by kConnectTimeoutMs.
class Client {
 public:
  enum class StartResult : uint8_t {
    Ok,
    Busy,
    NoRecording,
    DumpBusy,
    NotConfigured,
    WifiDown,
  };

  explicit Client(const mic::Engine& mic) : mic_(mic) {}

  // Copies and validates the receiver settings. Host must be an IPv4 literal;
  // the token is kept in RAM only and is never logged.
  void begin(const char* host, uint16_t port, const char* path,
             const char* token);

  // Starts an upload of the last completed recording. Returns immediately;
  // the result is reported asynchronously on the serial console.
  StartResult start();
  // Stops an active upload and closes the socket. The recording is kept.
  void cancel();
  // Advances at most one small transfer step. Never waits for the network.
  void update();

  bool configured() const { return configured_; }
  bool active() const;
  const char* stateName() const;
  void printStatus() const;

  static constexpr size_t kMaxToken = 64;

 private:
  enum class State : uint8_t {
    Idle,
    Connecting,
    Header,
    Body,
    Reading,
    RetryWait,
    Done,
    Failed,
  };

  static constexpr uint8_t kMaxAttempts = 3;
  static constexpr uint32_t kConnectTimeoutMs = 1000;
  static constexpr uint32_t kStallTimeoutMs = 5000;
  static constexpr uint32_t kResponseTimeoutMs = 5000;
  static constexpr uint32_t kRetryDelayMs = 1000;
  static constexpr size_t kChunkBytes = 1024;
  static constexpr size_t kHeaderBytes = 512;
  static constexpr size_t kResponseBytes = 256;
  static constexpr size_t kMaxHost = 63;
  static constexpr size_t kMaxPath = 47;

  bool buildHeader();
  void startAttempt(uint32_t now);
  void scheduleRetry(uint32_t now, const char* reason);
  void failFinal(const char* reason);
  void succeed();
  void evaluateResponse();
  void closeSocket();
  void logStart() const;

  const mic::Engine& mic_;

  char host_[kMaxHost + 1] = {};
  char path_[kMaxPath + 1] = {};
  char token_[kMaxToken + 1] = {};
  uint16_t port_ = 0;
  IPAddress address_;
  bool configured_ = false;

  State state_ = State::Idle;
  WiFiClient client_;
  char header_[kHeaderBytes] = {};
  size_t headerLength_ = 0;
  size_t headerSent_ = 0;
  uint32_t sent_ = 0;
  uint32_t attempts_ = 0;
  uint32_t lastProgressMs_ = 0;
  uint32_t deadlineMs_ = 0;
  char response_[kResponseBytes] = {};
  size_t responseLength_ = 0;
  char reason_[24] = {};
};

}  // namespace upload
