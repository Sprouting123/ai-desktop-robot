#include "eyes_state.h"
#include <cstring>

namespace eyes {
static constexpr const char* kNames[] = {
  "normal", "happy", "angry", "sad", "embarrassed", "sympathy", "comfort",
  "melancholy", "left", "right"
};
const char* name(Expression type) { return kNames[static_cast<uint8_t>(type)]; }
bool parse(const char* text, Expression& result) {
  for (uint8_t i = 0; i < 10; ++i) {
    if (std::strcmp(text, kNames[i]) == 0) { result = static_cast<Expression>(i); return true; }
  }
  return false;
}
const char* name(Phase phase) {
  static constexpr const char* names[] = {"idle", "closing", "closed", "opening"};
  return names[static_cast<uint8_t>(phase)];
}
uint16_t State::moveDuration() const {
  // Slow expressions deliberately spend longer on each closure step.
  if (expression == Expression::Sad) return 320;
  if (expression == Expression::Comfort) return 360;
  if (expression == Expression::Melancholy) return 400;
  return 200;
}
uint32_t State::nextInterval() {
  rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5;
  // Normal keeps the required 3-5 s cadence; low moods blink less often.
  uint32_t low = 3000, span = 2001;
  switch (expression) {
    case Expression::Sad: low = 5000; break;
    case Expression::Comfort: low = 4500; break;
    case Expression::Melancholy: low = 6000; break;
    case Expression::Embarrassed: low = 3600; break;
    default: break;
  }
  return low + rng % span;
}
void State::setExpression(Expression type, uint32_t now) {
  expression = type;
  phase = Phase::Idle;  // A new expression cancels any blink in progress.
  entered = phaseStarted = idleStarted = now;
  interval = nextInterval();
}
bool State::blink(uint32_t now) {
  if (phase != Phase::Idle) return false;  // Never restart or queue mid-blink.
  phase = Phase::Closing;
  phaseStarted = now;
  return true;
}
void State::tick(uint32_t now) {
  // Advance at most one phase per loop; a slow bus never skips the closed hold.
  const uint32_t elapsed = now - phaseStarted;
  if (phase == Phase::Idle) {
    if (now - idleStarted >= interval) blink(now);
  } else if (phase == Phase::Closing && elapsed >= moveDuration()) {
    phase = Phase::Closed; phaseStarted = now;
  } else if (phase == Phase::Closed && elapsed >= 200) {
    phase = Phase::Opening; phaseStarted = now;
  } else if (phase == Phase::Opening && elapsed >= moveDuration()) {
    phase = Phase::Idle; phaseStarted = idleStarted = now;
    ++completed; interval = nextInterval();
  }
}
uint8_t State::closure(uint32_t now) const {
  if (phase == Phase::Idle) return 0;
  if (phase == Phase::Closed) return 4;
  uint32_t step = (now - phaseStarted) * 3 / moveDuration();
  if (step > 2) step = 2;
  return phase == Phase::Closing ? static_cast<uint8_t>(step + 1)
                                : static_cast<uint8_t>(3 - step);
}
uint8_t State::accent(uint32_t now) const {
  const uint32_t elapsed = now - entered;
  switch (expression) {
    case Expression::Sad: {
      static constexpr uint8_t tear[] = {0, 1, 2, 2};
      return tear[(elapsed / 600) % 4];
    }
    case Expression::Embarrassed: return elapsed % 4200 >= 3400 ? 1 : 0;
    case Expression::Comfort: return (elapsed / 900) % 2;  // Gentle rise/fall.
    case Expression::Melancholy: {
      static constexpr uint8_t droop[] = {0, 1, 2, 1};
      return droop[(elapsed / 1100) % 4];  // Slow eyelid droop.
    }
    default: return 0;
  }
}
}  // namespace eyes
