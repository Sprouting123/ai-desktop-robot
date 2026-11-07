#pragma once
#include <cstdint>

namespace eyes {
enum class Expression : uint8_t {
  Normal, Happy, Angry, Sad, Embarrassed, Sympathy, Comfort, Melancholy, Left, Right
};
enum class Phase : uint8_t { Idle, Closing, Closed, Opening };
const char* name(Expression type);
bool parse(const char* text, Expression& result);
const char* name(Phase phase);

// Pure time-based model, independent of Arduino and I2C; unsigned elapsed times
// remain correct across millis() rollover. No heap allocations or queued actions.
struct State {
  Expression expression = Expression::Normal;
  Phase phase = Phase::Idle;
  uint32_t entered = 0, phaseStarted = 0, idleStarted = 0;
  uint32_t interval = 4000, completed = 0, rng = 0x4162a317;
  void setExpression(Expression type, uint32_t now);
  bool blink(uint32_t now);  // False while a blink is already in progress.
  void tick(uint32_t now);
  uint8_t closure(uint32_t now) const;  // 0=open ... 4=closed
  uint8_t accent(uint32_t now) const;
  uint16_t moveDuration() const;
  uint32_t nextInterval();
};
}  // namespace eyes
