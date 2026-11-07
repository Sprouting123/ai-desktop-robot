#include "eyes_engine.h"
#include "eyes_render.h"
#include <Arduino.h>
#include <esp_heap_caps.h>
#include <cstring>

namespace eyes {
void Engine::setExpression(Expression type) {
  if (!active_) force_ = true;  // A debug screen may have changed every pixel.
  active_ = true;
  pending_ = false;
  lastKey_ = UINT32_MAX;
  state_.setExpression(type, millis());
}

bool Engine::blink() {
  pending_ = false;
  lastKey_ = UINT32_MAX;
  return active_ && state_.blink(millis());
}

void Engine::pause() {
  active_ = false;
  pending_ = false;
}

void Engine::render(uint8_t closure, uint8_t accent) {
  eyes::drawFrame(display_, state_.expression, closure, accent);
  frameHash_ = 2166136261U;
  for (unsigned i = 0; i < 1024; ++i) {
    frameHash_ = (frameHash_ ^ display_.getBufferPtr()[i]) * 16777619U;
  }
}

void Engine::update() {
  if (!active_) return;
  const uint32_t now = millis();
  state_.tick(now);
  const uint8_t closure = state_.closure(now), accent = state_.accent(now);
  const uint32_t key = (static_cast<uint32_t>(state_.expression) << 16) |
                       (closure << 8) | accent;
  // Finish one coherent target buffer before drawing another. Serial handling
  // runs between each 32-byte region, rather than waiting for a whole frame.
  if (!pending_ && key != lastKey_) {
    render(closure, accent);
    lastKey_ = key;
    cursor_ = 0;
    pending_ = true;
    ++frames_;
  }
  if (!pending_) return;
  const uint8_t* buffer = display_.getBufferPtr();
  while (cursor_ < 32) {
    const uint8_t block = cursor_++;
    const unsigned offset = block * 32;
    if (force_ || std::memcmp(buffer + offset, sent_ + offset, 32) != 0) {
      const uint32_t started = micros();
      display_.updateDisplayArea((block % 4) * 4, block / 4, 4, 1);
      const uint32_t duration = micros() - started;
      if (duration > maxTransferUs_) maxTransferUs_ = duration;
      std::memcpy(sent_ + offset, buffer + offset, 32);
      ++transfers_;
      break;  // At most one synchronous region transfer per loop.
    }
  }
  if (cursor_ == 32) {
    pending_ = false;
    force_ = false;
  }
}

void Engine::dump(Print& out) {
  // Draw the current instant into the buffer without touching I2C, then print
  // a 64x32 ASCII preview (one character per 2x2 pixel block).
  const uint32_t now = millis();
  const uint8_t closure = state_.closure(now), accent = state_.accent(now);
  render(closure, accent);
  out.printf("EYES_DUMP expression=%s closure=%u accent=%u hash=%08lX\n",
             name(state_.expression), closure, accent,
             static_cast<unsigned long>(frameHash_));
  const uint8_t* buffer = display_.getBufferPtr();
  for (int row = 0; row < 32; ++row) {
    for (int col = 0; col < 64; ++col) {
      uint8_t on = 0;
      for (int dy = 0; dy < 2; ++dy) {
        const int y = row * 2 + dy;
        for (int dx = 0; dx < 2; ++dx) {
          const int x = col * 2 + dx;
          on |= (buffer[(y / 8) * 128 + x] >> (y % 8)) & 1U;
        }
      }
      out.write(on ? '#' : '.');
    }
    out.write('\n');
  }
}

void Engine::printStatus() const {
  Serial.printf(
      "EYES expression=%s phase=%s auto_blink=%u mode=%s interval_ms=%lu "
      "blinks=%lu frames=%lu transfers=%lu hash=%08lX max_tx_us=%lu "
      "heap=%u min_heap=%u uptime_ms=%lu\n",
      name(state_.expression), active_ ? name(state_.phase) : "paused",
      active_ ? 1U : 0U, active_ ? "eyes" : "test",
      static_cast<unsigned long>(state_.interval),
      static_cast<unsigned long>(state_.completed),
      static_cast<unsigned long>(frames_),
      static_cast<unsigned long>(transfers_),
      static_cast<unsigned long>(frameHash_),
      static_cast<unsigned long>(maxTransferUs_),
      static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
      static_cast<unsigned>(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)),
      static_cast<unsigned long>(millis()));
}
}  // namespace eyes
