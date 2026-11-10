#include "audio_uploader.h"

#include <cerrno>
#include <cstdio>
#include <cstring>

#include <lwip/sockets.h>

namespace upload {
namespace {

bool responseMatches(const char* response, const mic::Engine& mic) {
  char bytes[32];
  char crc[24];
  std::snprintf(bytes, sizeof(bytes), "bytes=%lu",
                static_cast<unsigned long>(mic.recordedBytes()));
  std::snprintf(crc, sizeof(crc), "crc32=%08lx",
                static_cast<unsigned long>(mic.recordedCrc32()));
  // The receiver may put other fields between bytes and crc32 (it currently
  // reports frames=...) so match the values separately rather than requiring
  // one fixed contiguous string.
  return std::strstr(response, " 200 ") != nullptr &&
         std::strstr(response, "OK ") != nullptr &&
         std::strstr(response, bytes) != nullptr &&
         std::strstr(response, crc) != nullptr;
}

bool printableToken(const char* token) {
  const size_t length = std::strlen(token);
  if (length < 16 || length > Client::kMaxToken) return false;
  for (size_t i = 0; i < length; ++i) {
    const unsigned char value = static_cast<unsigned char>(token[i]);
    if (value < 0x21 || value > 0x7e) return false;
  }
  return true;
}

}  // namespace

void Client::begin(const char* host, uint16_t port, const char* path,
                   const char* token) {
  host_[0] = '\0';
  path_[0] = '\0';
  token_[0] = '\0';
  port_ = 0;
  configured_ = false;
  address_ = IPAddress();

  if (host != nullptr) {
    std::snprintf(host_, sizeof(host_), "%s", host);
  }
  if (path != nullptr) {
    std::snprintf(path_, sizeof(path_), "%s", path);
  }
  if (token != nullptr) {
    std::snprintf(token_, sizeof(token_), "%s", token);
  }
  port_ = port;
  address_.fromString(host_);

  const uint32_t rawAddress = static_cast<uint32_t>(address_);
  const bool hostValid = rawAddress != 0 && rawAddress != 0xFFFFFFFFUL;
  const bool pathValid = path_[0] == '/';
  configured_ = hostValid && port_ != 0 && pathValid && printableToken(token_);

  // The token itself is never printed, only whether the config is complete.
  if (configured_) {
    Serial.printf("UPLOAD_CONFIG configured=1 host=%s port=%u path=%s\n",
                  host_, static_cast<unsigned>(port_), path_);
  } else {
    Serial.println("UPLOAD_CONFIG configured=0");
  }
}

bool Client::active() const {
  return state_ == State::Connecting || state_ == State::Header ||
         state_ == State::Body || state_ == State::Reading ||
         state_ == State::RetryWait;
}

const char* Client::stateName() const {
  switch (state_) {
    case State::Idle:
      return "idle";
    case State::Connecting:
      return "connecting";
    case State::Header:
      return "header";
    case State::Body:
      return "body";
    case State::Reading:
      return "response";
    case State::RetryWait:
      return "retry_wait";
    case State::Done:
      return "done";
    case State::Failed:
      return "failed";
  }
  return "unknown";
}

Client::StartResult Client::start() {
  if (active()) return StartResult::Busy;
  if (mic_.dumpActive()) return StartResult::DumpBusy;
  if (mic_.recordState() == mic::RecordState::kRecording) {
    return StartResult::NoRecording;
  }
  if (mic_.recordState() != mic::RecordState::kReady) {
    return StartResult::NoRecording;
  }
  if (!configured_) return StartResult::NotConfigured;
  if (WiFi.status() != WL_CONNECTED) return StartResult::WifiDown;

  sent_ = 0;
  headerSent_ = 0;
  headerLength_ = 0;
  responseLength_ = 0;
  response_[0] = '\0';
  reason_[0] = '\0';
  attempts_ = 1;
  state_ = State::Connecting;
  client_.stop();
  logStart();
  return StartResult::Ok;
}

void Client::logStart() const {
  Serial.printf(
      "MIC_UPLOAD_START bytes=%lu crc32=%08lx host=%s port=%u attempts_max=%u\n",
      static_cast<unsigned long>(mic_.recordedBytes()),
      static_cast<unsigned long>(mic_.recordedCrc32()), host_,
      static_cast<unsigned>(port_), static_cast<unsigned>(kMaxAttempts));
}

bool Client::buildHeader() {
  const unsigned long bytes = static_cast<unsigned long>(mic_.recordedBytes());
  const unsigned long frames =
      static_cast<unsigned long>(mic_.recordedFrames());
  const unsigned long rate = static_cast<unsigned long>(mic_.sampleRate());
  const unsigned long crc =
      static_cast<unsigned long>(mic_.recordedCrc32());
  const int length = std::snprintf(
      header_, sizeof(header_),
      "POST %s HTTP/1.1\r\n"
      "Host: %s:%u\r\n"
      "X-Auth-Token: %s\r\n"
      "Content-Type: application/octet-stream\r\n"
      "Content-Length: %lu\r\n"
      "X-Audio-Format: s16le\r\n"
      "X-Sample-Rate: %lu\r\n"
      "X-Channels: 1\r\n"
      "X-Frames: %lu\r\n"
      "X-Crc32: %08lx\r\n"
      "Connection: close\r\n\r\n",
      path_, host_, static_cast<unsigned>(port_), token_, bytes, rate, frames,
      crc);
  if (length <= 0 || static_cast<size_t>(length) >= sizeof(header_)) {
    headerLength_ = 0;
    return false;
  }
  headerLength_ = static_cast<size_t>(length);
  return true;
}

void Client::startAttempt(uint32_t now) {
  headerSent_ = 0;
  sent_ = 0;
  responseLength_ = 0;
  response_[0] = '\0';
  if (!buildHeader()) {
    failFinal("header");
    return;
  }
  // Bounded blocking: a LAN connect normally completes in milliseconds. The
  // timeout keeps a missing receiver from stalling the main loop for long.
  if (!client_.connect(address_, port_, kConnectTimeoutMs)) {
    scheduleRetry(now, "connect");
    return;
  }
  client_.setNoDelay(true);
  lastProgressMs_ = now;
  state_ = State::Header;
}

void Client::scheduleRetry(uint32_t now, const char* reason) {
  closeSocket();
  std::snprintf(reason_, sizeof(reason_), "%s", reason);
  if (attempts_ >= kMaxAttempts) {
    failFinal(reason);
    return;
  }
  ++attempts_;
  state_ = State::RetryWait;
  deadlineMs_ = now + kRetryDelayMs;
  Serial.printf("MIC_UPLOAD_RETRY attempt=%u reason=%s\n",
                static_cast<unsigned>(attempts_), reason_);
}

void Client::failFinal(const char* reason) {
  closeSocket();
  std::snprintf(reason_, sizeof(reason_), "%s", reason);
  state_ = State::Failed;
  Serial.printf("MIC_UPLOAD_FAILED reason=%s attempts=%u\n", reason_,
                static_cast<unsigned>(attempts_));
  Serial.printf("ERR mic_upload_failed reason=%s attempts=%u\n", reason_,
                static_cast<unsigned>(attempts_));
}

void Client::succeed() {
  closeSocket();
  state_ = State::Done;
  ++successCount_;
  // The receiver appends turn=<id> to its 200 response. Only accept the
  // documented ID characters so the value can be placed in a URL later.
  lastTurn_[0] = '\0';
  const char* turn = std::strstr(response_, "turn=");
  if (turn != nullptr) {
    turn += 5;
    size_t length = 0;
    while (length < sizeof(lastTurn_) - 1) {
      const char ch = turn[length];
      const bool valid = (ch >= '0' && ch <= '9') ||
                         (ch >= 'a' && ch <= 'z') ||
                         (ch >= 'A' && ch <= 'Z') || ch == '_' || ch == '-';
      if (!valid) break;
      lastTurn_[length] = ch;
      ++length;
    }
    lastTurn_[length] = '\0';
  }
  Serial.printf("MIC_UPLOAD_DONE bytes=%lu crc32=%08lx attempts=%u turn=%s\n",
                static_cast<unsigned long>(mic_.recordedBytes()),
                static_cast<unsigned long>(mic_.recordedCrc32()),
                static_cast<unsigned>(attempts_),
                lastTurn_[0] == '\0' ? "-" : lastTurn_);
  Serial.printf("OK mic=uploaded bytes=%lu crc32=%08lx\n",
                static_cast<unsigned long>(mic_.recordedBytes()),
                static_cast<unsigned long>(mic_.recordedCrc32()));
}

void Client::evaluateResponse() {
  response_[responseLength_] = '\0';
  if (responseLength_ == 0) {
    failFinal("no_response");
    return;
  }
  const bool statusOk = std::strstr(response_, " 200 ") != nullptr;
  if (responseMatches(response_, mic_)) {
    succeed();
    return;
  }
  failFinal(statusOk ? "bad_response" : "rejected");
}

void Client::closeSocket() {
  client_.stop();
}

void Client::cancel() {
  if (active()) {
    closeSocket();
    state_ = State::Idle;
    Serial.println("OK upload=cancelled mic=ready");
    return;
  }
  if (state_ == State::Done || state_ == State::Failed) {
    state_ = State::Idle;
    Serial.println("OK upload=reset");
    return;
  }
  Serial.println("OK upload=idle");
}

void Client::printStatus() const {
  Serial.printf(
      "UPLOAD state=%s configured=%u bytes=%lu sent=%lu crc32=%08lx "
      "attempts=%u host=%s port=%u\n",
      stateName(), configured_ ? 1U : 0U,
      static_cast<unsigned long>(mic_.recordedBytes()),
      static_cast<unsigned long>(sent_),
      static_cast<unsigned long>(mic_.recordedCrc32()),
      static_cast<unsigned>(attempts_), host_, static_cast<unsigned>(port_));
}

void Client::update() {
  const uint32_t now = millis();
  switch (state_) {
    case State::Idle:
    case State::Done:
    case State::Failed:
      return;

    case State::RetryWait:
      if (static_cast<int32_t>(now - deadlineMs_) >= 0) {
        state_ = State::Connecting;
      }
      return;

    case State::Connecting:
      startAttempt(now);
      return;

    case State::Header: {
      if (!client_.connected()) {
        scheduleRetry(now, "closed");
        return;
      }
      if (static_cast<int32_t>(now - lastProgressMs_) >=
          static_cast<int32_t>(kStallTimeoutMs)) {
        scheduleRetry(now, "stall");
        return;
      }
      // WiFiClient in Arduino-ESP32 2.0.17 inherits Print::availableForWrite(),
      // which always returns 0. Send directly on the socket with MSG_DONTWAIT,
      // as web_server.cpp does, so no blocking write can stall the loop.
      const int fd = client_.fd();
      if (fd < 0) {
        scheduleRetry(now, "socket");
        return;
      }
      size_t take = headerLength_ - headerSent_;
      if (take > kChunkBytes) take = kChunkBytes;
      const int written = ::send(
          fd, reinterpret_cast<const uint8_t*>(header_) + headerSent_, take,
          MSG_DONTWAIT);
      if (written > 0) {
        headerSent_ += static_cast<size_t>(written);
        lastProgressMs_ = now;
        if (headerSent_ >= headerLength_) state_ = State::Body;
        return;
      }
      if (written < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        scheduleRetry(now, "write");
      }
      return;
    }

    case State::Body: {
      if (!client_.connected()) {
        scheduleRetry(now, "closed");
        return;
      }
      if (static_cast<int32_t>(now - lastProgressMs_) >=
          static_cast<int32_t>(kStallTimeoutMs)) {
        scheduleRetry(now, "stall");
        return;
      }
      const uint32_t total = mic_.recordedBytes();
      if (sent_ >= total) {
        state_ = State::Reading;
        deadlineMs_ = now + kResponseTimeoutMs;
        return;
      }
      const int fd = client_.fd();
      if (fd < 0) {
        scheduleRetry(now, "socket");
        return;
      }
      const uint32_t remaining = total - sent_;
      size_t take = remaining < kChunkBytes ? remaining : kChunkBytes;
      const int written = ::send(
          fd, reinterpret_cast<const uint8_t*>(mic_.recordedData()) + sent_,
          take, MSG_DONTWAIT);
      if (written > 0) {
        sent_ += static_cast<uint32_t>(written);  // Partial writes are normal.
        lastProgressMs_ = now;
        return;
      }
      if (written < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
        scheduleRetry(now, "write");
      }
      return;
    }

    case State::Reading: {
      bool received = false;
      while (client_.available() > 0 &&
             responseLength_ + 1 < sizeof(response_)) {
        const int value = client_.read();
        if (value < 0) break;
        response_[responseLength_++] = static_cast<char>(value);
        received = true;
      }
      if (received) {
        response_[responseLength_] = '\0';
        deadlineMs_ = now + kResponseTimeoutMs;
        // Do not succeed on a partial response: the receiver appends the turn
        // ID after bytes/crc32, and the voice downloader waits for exactly
        // that turn. The server sends Connection: close, so waiting for the
        // close costs no extra round trip.
      }
      if (!client_.connected()) {
        evaluateResponse();
        return;
      }
      if (static_cast<int32_t>(now - deadlineMs_) >= 0) {
        evaluateResponse();
        return;
      }
      return;
    }
  }
}

}  // namespace upload
