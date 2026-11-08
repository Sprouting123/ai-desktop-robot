#pragma once
#include <Arduino.h>
#include <WiFi.h>

#include "eyes_engine.h"
#include "mood_controller.h"
#include "motion_engine.h"
#include "servo_controller.h"
#include "wifi_manager.h"

namespace web {

// Minimal HTTP/1.1 server built on WiFiServer. It deliberately does not expose
// a generic serial bridge: only the allow-listed status, mood and motion
// entries exist, and every state change is a POST with an X-Auth-Token header.
class Server {
 public:
  Server(wifi::Manager& wifi, eyes::Engine& eyes, mood::Controller& mood,
         motion::Engine& motion, servo::Controller& servo1,
         servo::Controller& servo2);

  void begin(const char* token);  // Stores the token; socket opens with Wi-Fi.
  void update();                  // Non-blocking; call from loop().
  void printStatus() const;

 private:
  static constexpr size_t kMaxRequest = 1024;  // Request line + headers + body.
  static constexpr size_t kMaxBody = 128;
  static constexpr size_t kMaxToken = 64;
  static constexpr size_t kMaxMethod = 7;
  static constexpr size_t kMaxPath = 39;
  static constexpr uint32_t kRequestTimeoutMs = 3000;
  static constexpr uint32_t kResponseTimeoutMs = 5000;
  static constexpr uint32_t kRateWindowMs = 10000;
  static constexpr uint16_t kMaxRequestsPerWindow = 30;
  static constexpr uint16_t kMaxWritesPerWindow = 10;

  void startListening();
  void stopListening();
  void closeConnection();
  void acceptClient();
  void serviceConnection();
  int parseHeader(size_t headerEnd);
  void processRequest();
  void handleGet();
  void handlePost();
  void handleMood();
  void handleMotion();
  bool authorize();
  bool parseName(char* out, size_t outSize) const;
  bool tokenEquals() const;
  bool rateLimited();
  void sendStatus();
  void sendPage();
  void sendResponse(int code, const char* contentType, const char* body,
                    size_t length, const char* extraHeaders = nullptr);
  void sendError(int code, const char* error,
                 const char* extraHeaders = nullptr);
  void flushResponse();
  void finishResponse();
  static const char* reasonPhrase(int code);

  wifi::Manager& wifi_;
  eyes::Engine& eyes_;
  mood::Controller& mood_;
  motion::Engine& motion_;
  servo::Controller& servo1_;
  servo::Controller& servo2_;

  WiFiServer server_{80, 4};
  bool listening_ = false;
  uint32_t listenRetryAtMs_ = 0;
  WiFiClient client_;
  bool active_ = false;

  char buffer_[kMaxRequest] = {};
  size_t length_ = 0;
  size_t bodyStart_ = 0;
  size_t contentLength_ = 0;
  bool headerParsed_ = false;
  bool hasContentLength_ = false;
  char method_[kMaxMethod + 1] = {};
  char path_[kMaxPath + 1] = {};
  char requestToken_[kMaxToken + 1] = {};
  size_t requestTokenLength_ = 0;
  bool tokenSeen_ = false;
  uint32_t startedMs_ = 0;

  // Responses are sent with non-blocking sends so a client that stops reading
  // cannot stall the OLED/servo loop. The small JSON bodies are copied; the
  // page body stays in flash and is addressed directly.
  bool responding_ = false;
  char responseHeader_[384] = {};
  size_t responseHeaderLength_ = 0;
  char responseBody_[800] = {};
  const char* responseBodyPtr_ = nullptr;
  size_t responseBodyLength_ = 0;
  size_t responseSent_ = 0;
  uint32_t responseStartedMs_ = 0;

  char token_[kMaxToken + 1] = {};
  size_t tokenLength_ = 0;
  bool authConfigured_ = false;

  uint32_t requestWindowStartMs_ = 0;
  uint32_t writeWindowStartMs_ = 0;
  uint16_t requestsInWindow_ = 0;
  uint16_t writesInWindow_ = 0;
  uint32_t requests_ = 0;
  uint32_t writes_ = 0;
  uint32_t rejected_ = 0;
  uint32_t rateLimited_ = 0;
};

}  // namespace web
