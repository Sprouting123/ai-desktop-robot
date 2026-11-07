#include "motion_engine.h"

#include <cstring>

namespace motion {

const char* name(Kind kind) {
  switch (kind) {
    case Kind::Neutral: return "neutral";
    case Kind::Wiggle: return "wiggle";
    case Kind::Together: return "together";
    case Kind::Alternate: return "alternate";
    default: return "none";
  }
}

bool parse(const char* text, Kind& kind) {
  if (std::strcmp(text, "neutral") == 0) kind = Kind::Neutral;
  else if (std::strcmp(text, "wiggle") == 0) kind = Kind::Wiggle;
  else if (std::strcmp(text, "together") == 0) kind = Kind::Together;
  else if (std::strcmp(text, "alternate") == 0) kind = Kind::Alternate;
  else return false;
  return true;
}

Profile profileFor(Kind kind) {
  switch (kind) {
    case Kind::Wiggle: return kWiggleProfile;
    case Kind::Together: return kTogetherProfile;
    case Kind::Alternate: return kAlternateProfile;
    default: return kNeutralProfile;
  }
}

bool Engine::validProfile(Kind kind, const Profile& profile) const {
  if (kind == Kind::None || profile.cycles == 0) return false;
  if (kind == Kind::Neutral) {
    return first_.validAngle(first_.centerAngle()) &&
           second_.validAngle(second_.centerAngle());
  }
  return profile.lowAngle <= profile.highAngle &&
         first_.validAngle(profile.lowAngle) &&
         first_.validAngle(profile.highAngle) &&
         second_.validAngle(profile.lowAngle) &&
         second_.validAngle(profile.highAngle);
}

bool Engine::start(Kind kind, const Profile& profile) {
  if (!first_.ready() || !second_.ready()) return false;
  if (!validProfile(kind, profile)) return false;

  kind_ = kind;
  profile_ = profile;
  state_ = State::Running;
  phase_ = Phase::Idle;
  stepIndex_ = 0;
  switch (kind) {
    case Kind::Wiggle: stepsPerCycle_ = 4; break;
    case Kind::Neutral: stepsPerCycle_ = 1; break;
    default: stepsPerCycle_ = 2; break;  // together / alternate
  }
  totalSteps_ = static_cast<uint16_t>(stepsPerCycle_) * profile.cycles;
  beginStep(1);  // Apply the first targets immediately, then wait in update().
  return true;
}

void Engine::beginStep(uint16_t index) {
  stepIndex_ = index;
  const uint16_t local = static_cast<uint16_t>((index - 1) % stepsPerCycle_);
  int target1 = first_.centerAngle();
  int target2 = second_.centerAngle();
  switch (kind_) {
    case Kind::Wiggle:
      // Servo 1 moves while servo 2 holds center, then the reverse.
      if (local == 0) target1 = profile_.lowAngle;
      else if (local == 1) target1 = profile_.highAngle;
      else if (local == 2) target2 = profile_.lowAngle;
      else target2 = profile_.highAngle;
      break;
    case Kind::Together:
      target1 = (local == 0) ? profile_.lowAngle : profile_.highAngle;
      target2 = target1;
      break;
    case Kind::Alternate:
      target1 = (local == 0) ? profile_.lowAngle : profile_.highAngle;
      target2 = (local == 0) ? profile_.highAngle : profile_.lowAngle;
      break;
    case Kind::Neutral:
    default:
      break;  // Both stay at the configured center angle.
  }

  // A failed target stops the whole sequence instead of leaving one servo
  // running with stale intentions.
  if (!first_.setAngle(target1) || !second_.setAngle(target2)) {
    stop();
    return;
  }
  phase_ = Phase::WaitMove;
}

void Engine::advance() {
  if (stepIndex_ < totalSteps_) {
    beginStep(static_cast<uint16_t>(stepIndex_ + 1));
    return;
  }
  // Every action ends at the center with outputs still enabled and holding.
  // The sequence itself is finished; no step remains queued.
  first_.center();
  second_.center();
  phase_ = Phase::Center;
}

void Engine::update() {
  if (state_ != State::Running) return;
  const uint32_t now = millis();
  switch (phase_) {
    case Phase::WaitMove:
      if (!first_.moving() && !second_.moving()) {
        if (profile_.dwellMs == 0) {
          advance();
        } else {
          dwellUntil_ = now + profile_.dwellMs;
          phase_ = Phase::Dwell;
        }
      }
      break;
    case Phase::Dwell:
      // Unsigned subtraction wrapped through int32_t stays correct on rollover.
      if (static_cast<int32_t>(now - dwellUntil_) >= 0) advance();
      break;
    case Phase::Center:
      if (!first_.moving() && !second_.moving()) {
        state_ = State::Idle;
        kind_ = Kind::None;
        phase_ = Phase::Done;
        stepIndex_ = 0;
        totalSteps_ = 0;
      }
      break;
    default:
      break;
  }
}

void Engine::stop() {
  first_.stop();
  second_.stop();
  kind_ = Kind::None;
  state_ = State::Stopped;
  phase_ = Phase::Idle;
  stepIndex_ = 0;
  totalSteps_ = 0;
}

void Engine::cancel() {
  // Abandon the sequence without touching either controller: a manual command
  // for one channel must not turn off or redirect the other one. The other
  // servo simply finishes its last target and keeps holding it.
  kind_ = Kind::None;
  state_ = State::Idle;
  phase_ = Phase::Idle;
  stepIndex_ = 0;
  totalSteps_ = 0;
}

const char* Engine::stateName() const {
  switch (state_) {
    case State::Running: return "running";
    case State::Stopped: return "stopped";
    default: return "idle";
  }
}

void Engine::printStatus() const {
  const char* phaseText = "done";
  if (state_ == State::Running) {
    switch (phase_) {
      case Phase::WaitMove: phaseText = "moving"; break;
      case Phase::Dwell: phaseText = "dwell"; break;
      case Phase::Center: phaseText = "centering"; break;
      default: phaseText = "starting"; break;
    }
  } else if (state_ == State::Stopped) {
    phaseText = "stopped";
  }
  Serial.printf(
      "MOTION name=%s state=%s phase=%s step=%u total=%u "
      "angle1=%d target1=%d moving1=%u output1=%s "
      "angle2=%d target2=%d moving2=%u output2=%s\n",
      name(kind_), stateName(), phaseText, static_cast<unsigned>(stepIndex_),
      static_cast<unsigned>(totalSteps_), first_.angle(), first_.target(),
      first_.moving() ? 1U : 0U, first_.outputEnabled() ? "on" : "off",
      second_.angle(), second_.target(), second_.moving() ? 1U : 0U,
      second_.outputEnabled() ? "on" : "off");
}

}  // namespace motion
