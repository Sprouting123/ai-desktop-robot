#pragma once
#include <Arduino.h>
#include <WiFi.h>

namespace wifi {

// Non-blocking station-mode connection manager. begin() starts the first
// attempt and returns immediately; update() advances the connection state and
// schedules retries without waiting in loop(). The password is never logged.
class Manager {
 public:
  void begin(const char* ssid, const char* password);
  void update();
  void reconnect();  // Debug command: drop the link and retry without rebooting.
  void printStatus() const;

  bool enabled() const { return state_ != State::Disabled; }
  bool connected() const { return state_ == State::Connected; }
  const char* stateName() const;
  IPAddress localIp() const;
  int32_t rssi() const;
  uint32_t attempts() const { return attempts_; }
  uint32_t connects() const { return connects_; }

 private:
  enum class State : uint8_t { Disabled, Connecting, Connected, Backoff };

  void startAttempt(uint32_t now);
  void scheduleRetry(uint32_t now, const char* reason);

  const char* ssid_ = "";
  const char* password_ = "";
  State state_ = State::Disabled;
  uint32_t deadlineMs_ = 0;
  uint32_t retryAtMs_ = 0;
  uint32_t attempts_ = 0;
  uint32_t connects_ = 0;
  uint8_t backoffIndex_ = 0;
};

}  // namespace wifi
