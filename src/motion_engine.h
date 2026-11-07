#pragma once
#include <Arduino.h>

#include "servo_controller.h"

namespace motion {

// Named actions accepted by the `motion` command. None means no sequence.
enum class Kind : uint8_t { None, Neutral, Wiggle, Together, Alternate };

const char* name(Kind kind);
bool parse(const char* text, Kind& kind);

// Angles, repetitions and dwell time for one action. All action shapes are
// derived from these values; no action loops forever.
struct Profile {
  int lowAngle;
  int highAngle;
  uint8_t cycles;
  uint16_t dwellMs;
};

// First-test range stays inside 75-105 degrees, well within the 60-120 degree
// servo limits. Wiggle is deliberately long enough for a person to type
// `motion stop` while it is running: 4 steps/cycle * 6 cycles.
constexpr Profile kNeutralProfile = {90, 90, 1, 0};
constexpr Profile kWiggleProfile = {75, 105, 6, 350};
constexpr Profile kTogetherProfile = {75, 105, 5, 350};
constexpr Profile kAlternateProfile = {75, 105, 5, 300};

Profile profileFor(Kind kind);

// Coordinates the two existing servo::Controller instances. It only sets
// targets and waits on millis(); PWM, limits and gradual steps stay inside the
// servo layer.
class Engine {
 public:
  Engine(servo::Controller& first, servo::Controller& second)
      : first_(first), second_(second) {}

  bool start(Kind kind) { return start(kind, profileFor(kind)); }
  bool start(Kind kind, const Profile& profile);
  void stop();    // Cancel the sequence and remove both pulses.
  void cancel();  // Manual takeover: forget the sequence, leave both outputs.
  void update();  // Non-blocking; call from loop().
  void printStatus() const;

  Kind kind() const { return kind_; }
  const char* stateName() const;
  uint16_t step() const { return stepIndex_; }
  uint16_t totalSteps() const { return totalSteps_; }

 private:
  enum class State : uint8_t { Idle, Running, Stopped };
  enum class Phase : uint8_t { Idle, WaitMove, Dwell, Center, Done };

  bool validProfile(Kind kind, const Profile& profile) const;
  void beginStep(uint16_t index);
  void advance();

  servo::Controller& first_;
  servo::Controller& second_;
  Kind kind_ = Kind::None;
  State state_ = State::Idle;
  Phase phase_ = Phase::Idle;
  Profile profile_ = kNeutralProfile;
  uint16_t stepIndex_ = 0;
  uint16_t totalSteps_ = 0;
  uint8_t stepsPerCycle_ = 1;
  uint32_t dwellUntil_ = 0;
};

}  // namespace motion
