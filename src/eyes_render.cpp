#include "eyes_render.h"

namespace eyes {
namespace {
// The two eyes occupy x=18..54 and x=74..110 in the default layout.
struct EyeBox {
  int x, y, w, h, radius;
};

bool isCrescent(Expression type) {
  return type == Expression::Happy || type == Expression::Comfort;
}

EyeBox boxFor(Expression type, int eye) {
  int x = 18 + eye * 56;
  int y = 15, w = 36, h = 37, radius = 12;
  switch (type) {
    case Expression::Angry:
      y = 27; h = 23; radius = 7;
      break;
    case Expression::Sad:
      y = 25; h = 27; radius = 11;
      break;
    case Expression::Sympathy:
      x += 2; y = 24; w = 32; h = 29; radius = 10;
      break;
    case Expression::Embarrassed:
      if (eye == 0) {
        y = 20; w = 34; h = 32; radius = 12;
      } else {
        x += 2; y = 26; w = 32; h = 24; radius = 10;
      }
      break;
    case Expression::Melancholy:
      y = 34; h = 17; radius = 5;
      break;
    case Expression::Left:
      x -= 10;
      break;
    case Expression::Right:
      x += 10;
      break;
    default:
      break;
  }
  return {x, y, w, h, radius};
}

int gazeShiftX(Expression type, uint8_t accent) {
  if (type != Expression::Embarrassed) return 0;
  return accent ? -7 : 3;  // Occasional sideways glance.
}

void drawDrop(U8G2& d, int x, int y, int radius) {
  d.setDrawColor(1);
  d.drawTriangle(x - radius, y, x + radius, y, x, y - radius - 3);
  d.drawDisc(x, y + 1, radius);
}

// A thick arch: the upper rim of one ellipse minus a lower copy. The lower
// half is erased so the result reads as a smile-shaped eye, not a blob.
void drawCrescent(U8G2& d, int cx, int baseY, int rx, int ry,
                  uint8_t closure) {
  if (closure == 4) {
    d.drawRBox(cx - rx + 3, baseY - 2, 2 * rx - 6, 3, 1);
    return;
  }
  const int flat = ry * (4 - closure) / 4;  // Closing squashes the arch.
  const int arch = flat < 2 ? 2 : flat;
  const int thickness = arch < 5 ? arch : 5;
  d.setDrawColor(1);
  d.drawFilledEllipse(cx, baseY, rx, arch);
  d.setDrawColor(0);
  d.drawFilledEllipse(cx, baseY + thickness, rx, arch);
  d.drawBox(cx - rx - 2, baseY + 1, 2 * rx + 5, arch + thickness + 4);
  d.setDrawColor(1);
}

void drawOpenEye(U8G2& d, const EyeBox& box, Expression type,
                 uint8_t closure, uint8_t accent) {
  const int x = box.x + gazeShiftX(type, accent);
  if (closure == 4) {
    // Closed eyes keep the expression's horizontal position.
    d.drawRBox(x + 3, box.y + box.h - 4, box.w - 6, 3, 1);
    return;
  }

  d.setDrawColor(1);
  d.drawRBox(x, box.y, box.w, box.h, box.radius);

  // Angry eyes lose their upper inner corner, producing a downward slant.
  if (type == Expression::Angry) {
    d.setDrawColor(0);
    if (box.x < 64)
      d.drawTriangle(x, box.y, x + box.w - 1, box.y,
                     x + box.w - 1, box.y + 11);
    else
      d.drawTriangle(x, box.y, x + box.w - 1, box.y, x, box.y + 11);
  }

  // The pupil stays in the frame and the lid covers it, so a blink only
  // changes the lid rows instead of repainting the whole eye over I2C.
  const int radius = type == Expression::Melancholy ? 3 : 4;
  int cx = x + box.w / 2;
  int cy = box.y + box.h / 2;
  if (type == Expression::Sad || type == Expression::Melancholy)
    cy = box.y + box.h - 7;  // Looking down.
  if (type == Expression::Embarrassed)
    cx += accent ? -2 : 1;
  d.setDrawColor(0);
  d.drawDisc(cx, cy, radius);
  if (radius >= 4) {
    d.setDrawColor(1);  // One-pixel catch light inside the pupil.
    d.drawPixel(cx - 1, cy - 2);
  }
  d.setDrawColor(1);

  // Upper lid descends from the top; the pupil disappears under it naturally.
  // Melancholy adds a permanent heavy lid that sinks with its slow accent.
  if (closure > 0 || type == Expression::Melancholy) {
    int lid = closure * box.h / 4 + 1;
    if (type == Expression::Melancholy) {
      lid += 2 + accent * 2;  // Slow droop; keeps at least a thin slit.
      if (lid > box.h - 3) lid = box.h - 3;
    }
    d.setDrawColor(0);
    d.drawBox(x - 1, box.y - 1, box.w + 2, lid);
    d.setDrawColor(1);
  }
}

void drawBrows(U8G2& d, Expression type) {
  for (int eye = 0; eye < 2; ++eye) {
    const EyeBox b = boxFor(type, eye);
    const int innerIsRight = eye == 0;
    if (type == Expression::Angry) {
      for (int t = 0; t < 3; ++t) {
        if (innerIsRight)
          d.drawLine(b.x, 12 + t, b.x + b.w - 1, 22 + t);
        else
          d.drawLine(b.x, 22 + t, b.x + b.w - 1, 12 + t);
      }
    } else if (type == Expression::Sad) {
      for (int t = 0; t < 2; ++t) {
        if (innerIsRight)
          d.drawLine(b.x, 22 + t, b.x + b.w - 1, 13 + t);
        else
          d.drawLine(b.x, 13 + t, b.x + b.w - 1, 22 + t);
      }
    } else if (type == Expression::Sympathy) {
      // A mild sad brow: inner ends raised, but far less than Sad.
      if (innerIsRight)
        d.drawLine(b.x, 19, b.x + b.w - 1, 16);
      else
        d.drawLine(b.x, 16, b.x + b.w - 1, 19);
    } else if (type == Expression::Melancholy) {
      d.drawHLine(b.x + 2, 29, b.w - 4);
    } else if (type == Expression::Embarrassed) {
      if (eye == 0)
        d.drawLine(b.x, 15, b.x + 24, 12);
      else
        d.drawLine(b.x, 19, b.x + 24, 18);
    }
  }
}
}  // namespace

void drawFrame(U8G2& d, Expression type, uint8_t closure, uint8_t accent) {
  d.clearBuffer();
  d.setDrawColor(1);

  if (isCrescent(type)) {
    const int baseY = type == Expression::Happy ? 42 : 42 + accent;
    drawCrescent(d, 36, baseY, 18, type == Expression::Happy ? 15 : 11,
                 closure);
    drawCrescent(d, 92, baseY, 18, type == Expression::Happy ? 15 : 11,
                 closure);
  } else {
    for (int eye = 0; eye < 2; ++eye) {
      drawOpenEye(d, boxFor(type, eye), type, closure, accent);
    }
  }

  d.setDrawColor(1);
  drawBrows(d, type);

  if (type == Expression::Sad) {
    drawDrop(d, 30, 52 + accent * 2, 2);
  } else if (type == Expression::Embarrassed) {
    drawDrop(d, 114, 12 + accent * 2, 2);
    for (int side = 0; side < 2; ++side) {
      const int x = side ? 111 : 12;
      d.drawLine(x, 47, x + 4, 44);
      d.drawLine(x, 50, x + 4, 47);
    }
  } else if (type == Expression::Sympathy) {
    d.drawLine(59, 58, 63, 55);
    d.drawLine(63, 55, 68, 58);
  } else if (type == Expression::Comfort) {
    d.drawLine(59, 55 + accent, 63, 58 + accent);
    d.drawLine(63, 58 + accent, 68, 55 + accent);
    for (int side = 0; side < 2; ++side) {
      const int x = side ? 111 : 12;
      d.drawLine(x, 46 + accent, x + 5, 46 + accent);
    }
  }
}
}  // namespace eyes
