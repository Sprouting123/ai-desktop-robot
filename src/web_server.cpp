#include "web_server.h"

#include <cctype>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <strings.h>

#include <lwip/sockets.h>

#include "web_ui.h"

namespace web {
namespace {

constexpr const char* kJsonType = "application/json";
constexpr const char* kHtmlType = "text/html; charset=utf-8";
constexpr const char* kCsp =
    "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "base-uri 'none'; frame-ancestors 'none'\r\n";
constexpr const char* kTokenChallenge =
    "WWW-Authenticate: Token realm=\"esp32-robot\"\r\n";

void formatIp(const IPAddress& address, char* out, size_t size) {
  snprintf(out, size, "%u.%u.%u.%u", address[0], address[1], address[2],
           address[3]);
}

const char* errorNameForCode(int code) {
  switch (code) {
    case 411: return "length_required";
    case 413: return "request_too_large";
    case 431: return "request_header_too_large";
    case 405: return "method_not_allowed";
    default: return "bad_request";
  }
}

}  // namespace

Server::Server(wifi::Manager& wifi, eyes::Engine& eyes,
               mood::Controller& mood, motion::Engine& motion,
               servo::Controller& servo1, servo::Controller& servo2)
    : wifi_(wifi),
      eyes_(eyes),
      mood_(mood),
      motion_(motion),
      servo1_(servo1),
      servo2_(servo2) {}

void Server::begin(const char* token) {
  tokenLength_ = 0;
  token_[0] = '\0';
  authConfigured_ = false;
  if (token != nullptr) {
    const size_t length = strlen(token);
    bool valid = length >= 16 && length <= kMaxToken;
    for (size_t i = 0; valid && i < length; ++i) {
      const unsigned char value = static_cast<unsigned char>(token[i]);
      if (value <= 0x20 || value >= 0x7f) valid = false;
    }
    if (valid) {
      memcpy(token_, token, length);
      token_[length] = '\0';
      tokenLength_ = length;
      authConfigured_ = true;
    }
  }
  // Never print the token or its length.
  Serial.printf("WEB_AUTH state=%s\n",
                authConfigured_ ? "enabled" : "disabled");
}

void Server::update() {
  const bool connected = wifi_.connected();
  if (connected && !listening_) {
    const uint32_t now = millis();
    if (static_cast<int32_t>(now - listenRetryAtMs_) >= 0) startListening();
  }
  if (!connected && listening_) {
    stopListening();
    return;
  }
  if (!listening_) return;

  if (responding_) {
    flushResponse();
    return;
  }
  if (!active_) acceptClient();
  if (active_) serviceConnection();
}

void Server::startListening() {
  server_.begin(80);
  server_.setNoDelay(true);
  listening_ = server_ ? true : false;
  if (listening_) {
    Serial.println("WEB_LISTEN state=listening port=80");
  } else {
    listenRetryAtMs_ = millis() + 5000;
    Serial.println("WEB_LISTEN state=failed retry_ms=5000");
  }
}

void Server::stopListening() {
  closeConnection();
  if (listening_) server_.end();
  listening_ = false;
  Serial.println("WEB_LISTEN state=stopped reason=wifi_down");
}

void Server::closeConnection() {
  if (active_) {
    client_.stop();
    active_ = false;
  }
  length_ = 0;
  bodyStart_ = 0;
  contentLength_ = 0;
  headerParsed_ = false;
  hasContentLength_ = false;
  method_[0] = '\0';
  path_[0] = '\0';
  requestToken_[0] = '\0';
  requestTokenLength_ = 0;
  tokenSeen_ = false;
  responding_ = false;
  responseHeaderLength_ = 0;
  responseBodyPtr_ = nullptr;
  responseBodyLength_ = 0;
  responseSent_ = 0;
}

void Server::acceptClient() {
  WiFiClient candidate = server_.available();
  if (!candidate) return;
  client_ = candidate;
  client_.setNoDelay(true);
  active_ = true;
  length_ = 0;
  bodyStart_ = 0;
  contentLength_ = 0;
  headerParsed_ = false;
  hasContentLength_ = false;
  method_[0] = '\0';
  path_[0] = '\0';
  requestToken_[0] = '\0';
  requestTokenLength_ = 0;
  tokenSeen_ = false;
  startedMs_ = millis();
}

void Server::serviceConnection() {
  // Bounded read: the OLED and servo schedules keep running between packets.
  size_t budget = 64;
  while (budget > 0 && client_.available() > 0) {
    const int value = client_.read();
    if (value < 0) break;
    --budget;
    if (value == 0) {  // Embedded NUL is never valid in our request format.
      sendError(400, "bad_request");
      return;
    }
    if (length_ >= kMaxRequest) {
      if (headerParsed_) {
        sendError(413, "request_too_large");
      } else {
        sendError(431, "request_header_too_large");
      }
      return;
    }
    buffer_[length_++] = static_cast<char>(value);
  }

  if (!headerParsed_) {
    size_t headerEnd = kMaxRequest;
    for (size_t i = 0; i + 3 < length_; ++i) {
      if (buffer_[i] == '\r' && buffer_[i + 1] == '\n' &&
          buffer_[i + 2] == '\r' && buffer_[i + 3] == '\n') {
        headerEnd = i;
        break;
      }
    }
    if (headerEnd != kMaxRequest) {
      bodyStart_ = headerEnd + 4;
      const int code = parseHeader(headerEnd);
      if (code != 0) {
        sendError(code, errorNameForCode(code));
        return;
      }
      headerParsed_ = true;
      const bool isPost = strcmp(method_, "POST") == 0;
      if (isPost && !hasContentLength_) {
        sendError(411, "length_required");
        return;
      }
      if (contentLength_ > kMaxBody || bodyStart_ + contentLength_ > kMaxRequest) {
        sendError(413, "request_too_large");
        return;
      }
      if (!isPost && contentLength_ > 0) {
        sendError(400, "unexpected_body");
        return;
      }
    } else if (length_ >= kMaxRequest) {
      sendError(431, "request_header_too_large");
      return;
    }
  }

  if (headerParsed_ && length_ >= bodyStart_ &&
      length_ - bodyStart_ >= contentLength_) {
    processRequest();
    return;
  }

  if (!client_.connected() && client_.available() == 0) {
    closeConnection();
    return;
  }
  if (static_cast<int32_t>(millis() - startedMs_) >=
      static_cast<int32_t>(kRequestTimeoutMs)) {
    sendError(408, "request_timeout");
  }
}

int Server::parseHeader(size_t headerEnd) {
  // The final CR of the blank line becomes a terminator. The body starts four
  // bytes later and is left untouched for parseName().
  buffer_[headerEnd] = '\0';
  char* save = nullptr;
  char* line = strtok_r(buffer_, "\r\n", &save);
  if (line == nullptr) return 400;

  char parsedMethod[kMaxMethod + 1] = {};
  char parsedPath[kMaxPath + 1] = {};
  char version[9] = {};
  int consumed = 0;
  if (sscanf(line, "%7s %39s %8s %n", parsedMethod, parsedPath, version,
             &consumed) != 3) {
    return 400;
  }
  if (strncmp(version, "HTTP/1.", 7) != 0 ||
      (version[7] != '0' && version[7] != '1') || version[8] != '\0') {
    return 400;
  }
  if (parsedPath[0] != '/' || strchr(parsedPath, '?') != nullptr ||
      strchr(parsedPath, '#') != nullptr) {
    // Tokens are accepted only in the header, never in the URL. The rejected
    // path is deliberately not copied to path_ or logged: it may contain a
    // secret typed into the wrong place.
    return 400;
  }
  const char* rest = line + consumed;
  while (*rest == ' ' || *rest == '\t') ++rest;
  if (*rest != '\0') return 400;
  memcpy(method_, parsedMethod, sizeof(method_));
  memcpy(path_, parsedPath, sizeof(path_));
  method_[kMaxMethod] = '\0';
  path_[kMaxPath] = '\0';

  while ((line = strtok_r(nullptr, "\r\n", &save)) != nullptr) {
    char* colon = strchr(line, ':');
    if (colon == nullptr) return 400;
    *colon = '\0';
    char* value = colon + 1;
    while (*value == ' ' || *value == '\t') ++value;
    size_t valueLength = strlen(value);
    while (valueLength > 0 &&
           (value[valueLength - 1] == ' ' || value[valueLength - 1] == '\t')) {
      value[--valueLength] = '\0';
    }

    if (strcasecmp(line, "Content-Length") == 0) {
      if (hasContentLength_) return 400;
      if (*value == '\0') return 400;
      unsigned long parsed = 0;
      for (const char* p = value; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9') return 400;
        parsed = parsed * 10 + static_cast<unsigned long>(*p - '0');
        if (parsed > 65535UL) return 413;
      }
      contentLength_ = static_cast<size_t>(parsed);
      hasContentLength_ = true;
    } else if (strcasecmp(line, "X-Auth-Token") == 0) {
      if (tokenSeen_) return 400;
      if (valueLength > kMaxToken) return 431;
      memcpy(requestToken_, value, valueLength);
      requestToken_[valueLength] = '\0';
      requestTokenLength_ = valueLength;
      tokenSeen_ = true;
    }
  }
  return 0;
}

void Server::processRequest() {
  ++requests_;
  if (rateLimited()) return;
  if (strcmp(method_, "GET") == 0) {
    handleGet();
    return;
  }
  if (strcmp(method_, "POST") == 0) {
    handlePost();
    return;
  }
  sendError(405, "method_not_allowed", "Allow: GET, POST\r\n");
}

bool Server::rateLimited() {
  const uint32_t now = millis();
  if (static_cast<int32_t>(now - requestWindowStartMs_) >=
      static_cast<int32_t>(kRateWindowMs)) {
    requestWindowStartMs_ = now;
    requestsInWindow_ = 0;
  }
  if (static_cast<int32_t>(now - writeWindowStartMs_) >=
      static_cast<int32_t>(kRateWindowMs)) {
    writeWindowStartMs_ = now;
    writesInWindow_ = 0;
  }

  ++requestsInWindow_;
  if (requestsInWindow_ > kMaxRequestsPerWindow) {
    ++rateLimited_;
    sendError(429, "rate_limited");
    return true;
  }
  if (strcmp(method_, "POST") == 0) {
    ++writesInWindow_;
    if (writesInWindow_ > kMaxWritesPerWindow) {
      ++rateLimited_;
      sendError(429, "write_rate_limited");
      return true;
    }
  }
  return false;
}

void Server::handleGet() {
  if (strcmp(path_, "/api/status") == 0) {
    sendStatus();
    return;
  }
  if (strcmp(path_, "/") == 0 || strcmp(path_, "/index.html") == 0) {
    sendPage();
    return;
  }
  if (strcmp(path_, "/favicon.ico") == 0) {
    sendResponse(204, "text/plain", nullptr, 0);
    return;
  }
  if (strcmp(path_, "/api/mood") == 0 || strcmp(path_, "/api/motion") == 0) {
    sendError(405, "method_not_allowed", "Allow: POST\r\n");
    return;
  }
  sendError(404, "not_found");
}

void Server::handlePost() {
  if (strcmp(path_, "/api/status") == 0 || strcmp(path_, "/") == 0 ||
      strcmp(path_, "/index.html") == 0) {
    sendError(405, "method_not_allowed", "Allow: GET\r\n");
    return;
  }
  if (strcmp(path_, "/api/mood") == 0) {
    handleMood();
    return;
  }
  if (strcmp(path_, "/api/motion") == 0) {
    handleMotion();
    return;
  }
  sendError(404, "not_found");
}

bool Server::authorize() {
  if (!authConfigured_) {
    sendError(503, "auth_not_configured");
    return false;
  }
  if (!tokenSeen_ || requestTokenLength_ == 0) {
    sendError(401, "missing_token", kTokenChallenge);
    return false;
  }
  if (!tokenEquals()) {
    sendError(403, "invalid_token");
    return false;
  }
  return true;
}

bool Server::tokenEquals() const {
  if (!tokenSeen_ || requestTokenLength_ != tokenLength_) return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < tokenLength_; ++i) {
    difference |= static_cast<uint8_t>(token_[i] ^ requestToken_[i]);
  }
  return difference == 0;
}

bool Server::parseName(char* out, size_t outSize) const {
  const char* body = buffer_ + bodyStart_;
  const size_t length = contentLength_;
  size_t index = 0;

  auto skipSpace = [&]() {
    while (index < length &&
           (body[index] == ' ' || body[index] == '\t' ||
            body[index] == '\r' || body[index] == '\n')) {
      ++index;
    }
  };

  skipSpace();
  if (index >= length || body[index++] != '{') return false;
  skipSpace();
  if (length - index < 6 || strncmp(body + index, "\"name\"", 6) != 0) {
    return false;
  }
  index += 6;
  skipSpace();
  if (index >= length || body[index++] != ':') return false;
  skipSpace();
  if (index >= length || body[index++] != '"') return false;

  size_t nameLength = 0;
  while (index < length && body[index] != '"') {
    char value = body[index++];
    if (value >= 'A' && value <= 'Z') value = static_cast<char>(value + 32);
    if (value < 'a' || value > 'z') return false;
    if (nameLength + 1 >= outSize) return false;
    out[nameLength++] = value;
  }
  if (index >= length || body[index++] != '"') return false;
  out[nameLength] = '\0';
  skipSpace();
  if (index >= length || body[index++] != '}') return false;
  skipSpace();
  return index == length && nameLength > 0;
}

void Server::handleMood() {
  if (!authorize()) return;
  char name[17] = {};
  if (!parseName(name, sizeof(name))) {
    sendError(400, "invalid_body");
    return;
  }

  char ip[16];
  formatIp(client_.remoteIP(), ip, sizeof(ip));

  if (strcmp(name, "stop") == 0) {
    mood_.stop();
    ++writes_;
    char body[160];
    const int length = snprintf(
        body, sizeof(body),
        "{\"ok\":true,\"mood\":\"stop\",\"expression\":\"%s\","
        "\"motion\":\"%s\",\"screen\":\"kept\"}",
        eyes::name(eyes_.expression()), motion::name(motion_.kind()));
    Serial.printf("WEB_MOOD name=stop code=200 ip=%s\n", ip);
    sendResponse(200, kJsonType, body,
                 length > 0 ? static_cast<size_t>(length) : 0);
    return;
  }

  mood::Kind kind;
  if (!mood::parse(name, kind)) {
    sendError(400, "invalid_name");
    return;
  }
  if (!mood_.start(kind)) {
    sendError(503, "servo_not_ready");
    return;
  }
  ++writes_;
  char body[192];
  const int length = snprintf(
      body, sizeof(body),
      "{\"ok\":true,\"mood\":\"%s\",\"expression\":\"%s\","
      "\"motion\":\"%s\"}",
      mood::name(mood_.kind()), eyes::name(eyes_.expression()),
      motion::name(motion_.kind()));
  Serial.printf("WEB_MOOD name=%s code=200 ip=%s\n", mood::name(mood_.kind()),
                ip);
  sendResponse(200, kJsonType, body,
               length > 0 ? static_cast<size_t>(length) : 0);
}

void Server::handleMotion() {
  if (!authorize()) return;
  char name[17] = {};
  if (!parseName(name, sizeof(name))) {
    sendError(400, "invalid_body");
    return;
  }

  char ip[16];
  formatIp(client_.remoteIP(), ip, sizeof(ip));

  if (strcmp(name, "stop") == 0) {
    motion_.stop();
    mood_.clear();
    ++writes_;
    const char body[] =
        "{\"ok\":true,\"motion\":\"stop\",\"state\":\"stopped\","
        "\"output\":\"off\"}";
    Serial.printf("WEB_MOTION name=stop code=200 ip=%s\n", ip);
    sendResponse(200, kJsonType, body, strlen(body));
    return;
  }

  motion::Kind kind;
  if (!motion::parse(name, kind)) {
    sendError(400, "invalid_name");
    return;
  }
  if (!motion_.start(kind)) {
    sendError(503, "servo_not_ready");
    return;
  }
  mood_.clear();
  ++writes_;
  char body[128];
  const int length =
      snprintf(body, sizeof(body), "{\"ok\":true,\"motion\":\"%s\",\"steps\":%u}",
               motion::name(motion_.kind()),
               static_cast<unsigned>(motion_.totalSteps()));
  Serial.printf("WEB_MOTION name=%s code=200 ip=%s\n",
                motion::name(motion_.kind()), ip);
  sendResponse(200, kJsonType, body,
               length > 0 ? static_cast<size_t>(length) : 0);
}

void Server::sendStatus() {
  char ip[16];
  formatIp(wifi_.localIp(), ip, sizeof(ip));
  char body[800];
  const int length = snprintf(
      body, sizeof(body),
      "{\"ok\":true,\"uptime_ms\":%lu,"
      "\"wifi\":{\"state\":\"%s\",\"ip\":\"%s\",\"rssi\":%d},"
      "\"expression\":\"%s\",\"mood\":\"%s\","
      "\"motion\":{\"name\":\"%s\",\"state\":\"%s\",\"step\":%u,\"total\":%u},"
      "\"servo1\":{\"angle\":%d,\"target\":%d,\"moving\":%u,"
      "\"output\":\"%s\",\"channel\":%u,\"ready\":%u},"
      "\"servo2\":{\"angle\":%d,\"target\":%d,\"moving\":%u,"
      "\"output\":\"%s\",\"channel\":%u,\"ready\":%u}}",
      static_cast<unsigned long>(millis()), wifi_.stateName(), ip,
      static_cast<int>(wifi_.rssi()), eyes::name(eyes_.expression()),
      mood::name(mood_.kind()), motion::name(motion_.kind()),
      motion_.stateName(), static_cast<unsigned>(motion_.step()),
      static_cast<unsigned>(motion_.totalSteps()), servo1_.angle(),
      servo1_.target(), servo1_.moving() ? 1U : 0U,
      servo1_.outputEnabled() ? "on" : "off",
      static_cast<unsigned>(servo1_.channel()), servo1_.ready() ? 1U : 0U,
      servo2_.angle(), servo2_.target(), servo2_.moving() ? 1U : 0U,
      servo2_.outputEnabled() ? "on" : "off",
      static_cast<unsigned>(servo2_.channel()), servo2_.ready() ? 1U : 0U);
  if (length <= 0 || static_cast<size_t>(length) >= sizeof(body)) {
    sendError(500, "status_too_long");
    return;
  }
  sendResponse(200, kJsonType, body, static_cast<size_t>(length));
}

void Server::sendPage() {
  sendResponse(200, kHtmlType, kControlPage, sizeof(kControlPage) - 1, kCsp);
}

void Server::sendResponse(int code, const char* contentType, const char* body,
                          size_t length, const char* extraHeaders) {
  if (!active_ || responding_) return;
  const int headerLength = snprintf(
      responseHeader_, sizeof(responseHeader_),
      "HTTP/1.1 %d %s\r\n"
      "Content-Type: %s\r\n"
      "Content-Length: %u\r\n"
      "Cache-Control: no-store\r\n"
      "Connection: close\r\n"
      "X-Content-Type-Options: nosniff\r\n"
      "%s\r\n",
      code, reasonPhrase(code),
      contentType != nullptr ? contentType : "text/plain",
      static_cast<unsigned>(length),
      extraHeaders != nullptr ? extraHeaders : "");
  if (headerLength <= 0) {
    finishResponse();
    return;
  }
  responseHeaderLength_ = static_cast<size_t>(headerLength) <
                                  sizeof(responseHeader_)
                              ? static_cast<size_t>(headerLength)
                              : sizeof(responseHeader_) - 1;
  responseBodyPtr_ = nullptr;
  responseBodyLength_ = 0;
  if (body != nullptr && length > 0) {
    if (length > sizeof(responseBody_)) {
      // Only the flash-resident control page reaches this size.
      responseBodyPtr_ = body;
    } else {
      memcpy(responseBody_, body, length);
      responseBodyPtr_ = responseBody_;
    }
    responseBodyLength_ = length;
  }
  responseSent_ = 0;
  responseStartedMs_ = millis();
  responding_ = true;
  if (code >= 400) ++rejected_;
  flushResponse();
}

void Server::flushResponse() {
  if (!responding_) return;
  const size_t total = responseHeaderLength_ + responseBodyLength_;
  while (responseSent_ < total) {
    const uint8_t* data;
    size_t remaining;
    if (responseSent_ < responseHeaderLength_) {
      data = reinterpret_cast<const uint8_t*>(responseHeader_) + responseSent_;
      remaining = responseHeaderLength_ - responseSent_;
    } else {
      data = reinterpret_cast<const uint8_t*>(responseBodyPtr_) +
             (responseSent_ - responseHeaderLength_);
      remaining = total - responseSent_;
    }
    const int fd = client_.fd();
    if (fd < 0) {
      finishResponse();
      return;
    }
    const int sent = ::send(fd, data, remaining, MSG_DONTWAIT);
    if (sent > 0) {
      responseSent_ += static_cast<size_t>(sent);
      continue;
    }
    if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
      finishResponse();
      return;
    }
    break;  // Send buffer is full; continue from the next loop() update.
  }
  if (responseSent_ >= total) {
    finishResponse();
    return;
  }
  if (static_cast<int32_t>(millis() - responseStartedMs_) >=
      static_cast<int32_t>(kResponseTimeoutMs)) {
    finishResponse();
  }
}

void Server::finishResponse() {
  responding_ = false;
  closeConnection();
}

void Server::sendError(int code, const char* error, const char* extraHeaders) {
  char ip[16];
  formatIp(client_.remoteIP(), ip, sizeof(ip));
  // Do not log the raw path, query or headers: a client may have put a secret
  // in the wrong place, and the log must never contain it.
  Serial.printf("WEB_REJECT code=%d error=%s ip=%s\n", code,
                error != nullptr ? error : "error", ip);
  char body[96];
  const int length =
      snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}",
               error != nullptr ? error : "error");
  sendResponse(code, kJsonType, body,
               length > 0 ? static_cast<size_t>(length) : 0, extraHeaders);
}

const char* Server::reasonPhrase(int code) {
  switch (code) {
    case 200: return "OK";
    case 204: return "No Content";
    case 400: return "Bad Request";
    case 401: return "Unauthorized";
    case 403: return "Forbidden";
    case 404: return "Not Found";
    case 405: return "Method Not Allowed";
    case 408: return "Request Timeout";
    case 411: return "Length Required";
    case 413: return "Payload Too Large";
    case 429: return "Too Many Requests";
    case 431: return "Request Header Fields Too Large";
    case 500: return "Internal Server Error";
    case 503: return "Service Unavailable";
    default: return "Error";
  }
}

void Server::printStatus() const {
  Serial.printf(
      "WEB listening=%u port=80 requests=%lu writes=%lu rejected=%lu "
      "rate_limited=%lu auth=%s\n",
      listening_ ? 1U : 0U, static_cast<unsigned long>(requests_),
      static_cast<unsigned long>(writes_), static_cast<unsigned long>(rejected_),
      static_cast<unsigned long>(rateLimited_),
      authConfigured_ ? "enabled" : "disabled");
}

}  // namespace web
