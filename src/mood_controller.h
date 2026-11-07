#pragma once
#include <Arduino.h>

#include "eyes_engine.h"
#include "motion_engine.h"

namespace mood {

enum class Kind : uint8_t { None, Normal, Happy, Sad, Angry };

const char* name(Kind kind);
bool parse(const char* text, Kind& kind);

// Couples one face expression with one motion profile. This is the single
// entry point a future cloud AI can call to trigger a mood.
class Controller {
 public:
  Controller(eyes::Engine& eyes, motion::Engine& motion)
      : eyes_(eyes), motion_(motion) {}

  bool start(Kind kind);
  void stop();   // Stop motion and close PWM; the face stays as it is.
  void clear();  // Forget the mood label; never changes eyes or servos.
  void printStatus() const;
  Kind kind() const { return kind_; }

 private:
  eyes::Engine& eyes_;
  motion::Engine& motion_;
  Kind kind_ = Kind::None;
};

}  // namespace mood
