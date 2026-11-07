#pragma once
#include "eyes_state.h"
#include <U8g2lib.h>

class Print;

namespace eyes {
class Engine {
 public:
  explicit Engine(U8G2& display) : display_(display) {}
  void setExpression(Expression type);  // Unified future business/AI entry point.
  bool blink();
  void pause();
  void update();
  void printStatus() const;
  void dump(Print& out);  // ASCII framebuffer preview for software checks.
  bool active() const { return active_; }
  Expression expression() const { return state_.expression; }
 private:
  U8G2& display_;
  State state_;
  bool active_ = false, force_ = true, pending_ = false;
  uint8_t cursor_ = 0;
  uint8_t sent_[1024] = {};
  uint32_t lastKey_ = UINT32_MAX, frames_ = 0, transfers_ = 0, maxTransferUs_ = 0;
  uint32_t frameHash_ = 0;
  void render(uint8_t closure, uint8_t accent);
};
}  // namespace eyes
