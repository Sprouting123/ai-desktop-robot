#include "mood_controller.h"

#include <cstring>

namespace mood {
namespace {

// Mood motion parameters stay here so tuning a mood does not touch command
// parsing or the motion state machine.
constexpr motion::Profile kHappyMotion = {80, 100, 4, 350};   // gentle sway
constexpr motion::Profile kSadMotion = {85, 95, 3, 700};      // slow, small
constexpr motion::Profile kAngryMotion = {82, 98, 4, 150};    // short, sharp

struct Mapping {
  eyes::Expression expression;
  motion::Kind motion;
  motion::Profile profile;
};

Mapping mappingFor(Kind kind) {
  switch (kind) {
    case Kind::Happy: return {eyes::Expression::Happy, motion::Kind::Wiggle, kHappyMotion};
    case Kind::Sad: return {eyes::Expression::Sad, motion::Kind::Wiggle, kSadMotion};
    case Kind::Angry: return {eyes::Expression::Angry, motion::Kind::Alternate, kAngryMotion};
    default:
      return {eyes::Expression::Normal, motion::Kind::Neutral, motion::kNeutralProfile};
  }
}

}  // namespace

const char* name(Kind kind) {
  switch (kind) {
    case Kind::Normal: return "normal";
    case Kind::Happy: return "happy";
    case Kind::Sad: return "sad";
    case Kind::Angry: return "angry";
    default: return "none";
  }
}

bool parse(const char* text, Kind& kind) {
  if (std::strcmp(text, "normal") == 0) kind = Kind::Normal;
  else if (std::strcmp(text, "happy") == 0) kind = Kind::Happy;
  else if (std::strcmp(text, "sad") == 0) kind = Kind::Sad;
  else if (std::strcmp(text, "angry") == 0) kind = Kind::Angry;
  else return false;
  return true;
}

bool Controller::start(Kind kind) {
  if (kind == Kind::None) return false;
  const Mapping mapping = mappingFor(kind);
  // Start the motion first: a failed start must not change the face.
  if (!motion_.start(mapping.motion, mapping.profile)) return false;
  eyes_.setExpression(mapping.expression);
  kind_ = kind;
  return true;
}

void Controller::stop() {
  motion_.stop();
  kind_ = Kind::None;
}

void Controller::clear() { kind_ = Kind::None; }

void Controller::printStatus() const {
  Serial.printf("MOOD mood=%s expression=%s motion=%s\n", name(kind_),
                eyes::name(eyes_.expression()), motion::name(motion_.kind()));
  motion_.printStatus();
}

}  // namespace mood
