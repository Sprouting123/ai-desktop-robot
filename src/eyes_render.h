#pragma once
#include "eyes_state.h"
#include <U8g2lib.h>

namespace eyes {
// Draws one complete 128x64 frame into the U8g2 buffer. This module performs
// no I2C transfer and keeps no animation state, so it can also be built on a
// host for offline previews. closure: 0=open ... 4=closed.
void drawFrame(U8G2& display, Expression expression, uint8_t closure,
               uint8_t accent);
}  // namespace eyes
