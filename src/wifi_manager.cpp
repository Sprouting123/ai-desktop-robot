#include "wifi_manager.h"

namespace wifi {
namespace {

constexpr uint32_t kConnectTimeoutMs = 20000;
// Retry delays grow so a missing or powered-off access point does not cause a
// busy reconnect loop. The sequence is capped at 30 s.
constexpr uint32_t kBackoffMs[] = {2000, 5000, 10000, 20000, 30000};
constexpr uint8_t kBackoffCount =
    static_cast<uint8_t>(sizeof(kBackoffMs) / sizeof(kBackoffMs[0]));

}  // namespace

void Manager::begin(const char* ssid, const char* password) {
  ssid_ = ssid != nullptr ? ssid : "";
  password_ = password != nullptr ? password : "";
  if (*ssid_ == '\0') {
    state_ = State::Disabled;
    Serial.println("WIFI_DISABLED ssid_set=0 reason=no_credentials");
    return;
  }

  // Keep reconnection under this state machine. The Arduino core otherwise
  // retries in the background and makes the reported state ambiguous.
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  WiFi.setSleep(false);
  startAttempt(millis());
}

void Manager::startAttempt(uint32_t now) {
  ++attempts_;
  state_ = State::Connecting;
  deadlineMs_ = now + kConnectTimeoutMs;
  const wl_status_t result = WiFi.begin(ssid_, password_);
  Serial.printf("WIFI_CONNECTING ssid=%s attempt=%lu timeout_ms=%lu status=%d\n",
                ssid_, static_cast<unsigned long>(attempts_),
                static_cast<unsigned long>(kConnectTimeoutMs),
                static_cast<int>(result));
}

void Manager::scheduleRetry(uint32_t now, const char* reason) {
  const uint32_t delayMs = kBackoffMs[backoffIndex_];
  if (backoffIndex_ + 1 < kBackoffCount) ++backoffIndex_;
  retryAtMs_ = now + delayMs;
  state_ = State::Backoff;
  Serial.printf("WIFI_RETRY reason=%s delay_ms=%lu attempt=%lu\n", reason,
                static_cast<unsigned long>(delayMs),
                static_cast<unsigned long>(attempts_));
}

void Manager::update() {
  if (state_ == State::Disabled) return;
  const uint32_t now = millis();

  switch (state_) {
    case State::Connecting:
      if (WiFi.status() == WL_CONNECTED) {
        state_ = State::Connected;
        ++connects_;
        backoffIndex_ = 0;
        Serial.printf("WIFI_CONNECTED ip=%s rssi=%d channel=%d connects=%lu\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI(),
                      WiFi.channel(), static_cast<unsigned long>(connects_));
        return;
      }
      if (static_cast<int32_t>(now - deadlineMs_) >= 0) {
        Serial.printf("WIFI_TIMEOUT attempt=%lu ip=0.0.0.0 status=%d\n",
                      static_cast<unsigned long>(attempts_),
                      static_cast<int>(WiFi.status()));
        WiFi.disconnect(false, false);
        scheduleRetry(now, "timeout");
      }
      return;

    case State::Connected:
      if (WiFi.status() != WL_CONNECTED) {
        Serial.printf("WIFI_LOST status=%d\n", static_cast<int>(WiFi.status()));
        WiFi.disconnect(false, false);
        scheduleRetry(now, "lost");
      }
      return;

    case State::Backoff:
      if (static_cast<int32_t>(now - retryAtMs_) >= 0) startAttempt(now);
      return;

    default:
      return;
  }
}

void Manager::reconnect() {
  if (state_ == State::Disabled) return;
  const uint32_t now = millis();
  // Give the station interface a moment to leave its current state, then let
  // update() start a fresh attempt. No wait happens here.
  WiFi.disconnect(false, false);
  backoffIndex_ = 0;
  retryAtMs_ = now + 500;
  state_ = State::Backoff;
  Serial.println("WIFI_RECONNECT requested delay_ms=500");
}

const char* Manager::stateName() const {
  switch (state_) {
    case State::Connecting: return "connecting";
    case State::Connected: return "connected";
    case State::Backoff: return "backoff";
    default: return "disabled";
  }
}

IPAddress Manager::localIp() const {
  return state_ == State::Connected ? WiFi.localIP() : IPAddress(0, 0, 0, 0);
}

int32_t Manager::rssi() const {
  return state_ == State::Connected ? static_cast<int32_t>(WiFi.RSSI()) : 0;
}

void Manager::printStatus() const {
  int32_t retryInMs = 0;
  if (state_ == State::Backoff) {
    const int32_t remaining =
        static_cast<int32_t>(retryAtMs_ - static_cast<uint32_t>(millis()));
    retryInMs = remaining > 0 ? remaining : 0;
  }
  const IPAddress ip = localIp();
  Serial.printf(
      "WIFI state=%s ssid_set=%u ip=%s rssi=%d attempts=%lu connects=%lu "
      "retry_in_ms=%ld\n",
      stateName(), *ssid_ != '\0' ? 1U : 0U, ip.toString().c_str(),
      static_cast<int>(rssi()), static_cast<unsigned long>(attempts_),
      static_cast<unsigned long>(connects_), static_cast<long>(retryInMs));
}

}  // namespace wifi
