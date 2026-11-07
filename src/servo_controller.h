#pragma once
#include <Arduino.h>

namespace servo {

// All angle/pulse limits live here so a future calibration only changes one
// place. The conservative defaults keep the first tests away from mechanical
// limits while still using the normal SG90 50 Hz interface.
struct Config {
  uint8_t pin;
  uint8_t ledcChannel;
  uint16_t frequencyHz;
  uint8_t resolutionBits;
  uint16_t minPulseUs;
  uint16_t maxPulseUs;
  int minAngle;
  int maxAngle;
  int centerAngle;
  uint16_t speedDegPerSec;
  uint16_t stepIntervalMs;
};

constexpr Config makeConfig(uint8_t pin, uint8_t ledcChannel) {
  return Config{
      pin,
      ledcChannel,  // separate from the RGB (RMT) and OLED (I2C) paths
      50,           // SG90 refresh rate
      14,           // ESP32-S3 LEDC maximum; about 1.2 us pulse resolution
      600,          // conservative full-range pulse limits for a 180 degree SG90
      2400,
      60,   // software travel limits used by the servo commands
      120,
      90,   // neutral / power-on reference
      60,   // degrees per second while moving
      20,   // update one small step every 20 ms
  };
}

// Servo 1 keeps the experiment 005 wiring and channel.
constexpr Config kDefaultConfig = makeConfig(4, 0);
// Servo 2 uses GPIO5 and LEDC channel 1. On ESP32-S3 channels 0 and 1 share
// timer 0; both run at 50 Hz / 14 bit, so the shared timer stays consistent.
constexpr Config kServo2Config = makeConfig(5, 1);

class Controller {
 public:
  explicit Controller(const Config& config = kDefaultConfig) : config_(config) {}

  // Configures LEDC but deliberately leaves the output at zero duty. No pulse
  // is generated until the first setAngle()/center() command. The label keeps
  // the two instances distinguishable in the boot log (SERVO1_INIT, ...).
  bool begin(const char* label = "SERVO");
  bool setAngle(int angle);
  bool center() { return setAngle(config_.centerAngle); }
  void stop();  // Cancel the schedule and remove pulses (servo relaxed).
  void update();  // Non-blocking; call from loop().

  bool validAngle(int angle) const {
    return angle >= config_.minAngle && angle <= config_.maxAngle;
  }
  uint16_t pulseUsFor(int angle) const;
  int angle() const { return (currentTenths_ + 5) / 10; }
  int target() const { return (targetTenths_ + 5) / 10; }
  int minAngle() const { return config_.minAngle; }
  int maxAngle() const { return config_.maxAngle; }
  int centerAngle() const { return config_.centerAngle; }
  bool moving() const { return moving_; }
  bool outputEnabled() const { return outputEnabled_; }
  bool ready() const { return ready_; }
  uint8_t pin() const { return config_.pin; }
  uint8_t channel() const { return config_.ledcChannel; }
  const char* state() const;
  void printStatus(const char* label = "SERVO") const;

 private:
  void writeCurrentAngle();
  uint16_t pulseUsForTenths(int16_t tenths) const;

  Config config_;
  bool ready_ = false;
  bool outputEnabled_ = false;
  bool moving_ = false;
  int16_t currentTenths_ = 0;
  int16_t targetTenths_ = 0;
  uint32_t lastStepMs_ = 0;
  uint16_t stepTenths_ = 0;
  uint32_t actualFrequencyHz_ = 0;
};

}  // namespace servo
