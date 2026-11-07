#include "servo_controller.h"

namespace servo {
namespace {
constexpr int kFullRangeTenths = 1800;  // 180.0 degrees in 0.1 degree units.
}

bool Controller::begin() {
  actualFrequencyHz_ =
      ledcSetup(config_.ledcChannel, config_.frequencyHz, config_.resolutionBits);
  if (actualFrequencyHz_ == 0) {
    ready_ = false;
    outputEnabled_ = false;
    moving_ = false;
    Serial.printf(
        "SERVO_INIT ready=0 pin=%u channel=%u requested_hz=%u actual_hz=0 "
        "resolution_bits=%u output=off\n",
        static_cast<unsigned>(config_.pin),
        static_cast<unsigned>(config_.ledcChannel),
        static_cast<unsigned>(config_.frequencyHz),
        static_cast<unsigned>(config_.resolutionBits));
    return false;
  }

  ledcAttachPin(config_.pin, config_.ledcChannel);
  // Zero duty means no pulses at all. The servo stays relaxed until the user
  // explicitly asks for an angle, so boot never starts an automatic sweep.
  ledcWrite(config_.ledcChannel, 0);

  ready_ = true;
  outputEnabled_ = false;
  moving_ = false;
  currentTenths_ = static_cast<int16_t>(config_.centerAngle * 10);
  targetTenths_ = currentTenths_;
  lastStepMs_ = millis();

  uint32_t step = static_cast<uint32_t>(config_.speedDegPerSec) *
                  config_.stepIntervalMs * 10UL / 1000UL;
  if (step == 0) step = 1;
  if (step > 32767UL) step = 32767UL;
  stepTenths_ = static_cast<uint16_t>(step);

  Serial.printf(
      "SERVO_INIT ready=1 pin=%u channel=%u requested_hz=%u actual_hz=%lu "
      "resolution_bits=%u output=off center=%d range=%d-%d pulse_us=%u-%u "
      "speed_dps=%u step_ms=%u\n",
      static_cast<unsigned>(config_.pin),
      static_cast<unsigned>(config_.ledcChannel),
      static_cast<unsigned>(config_.frequencyHz),
      static_cast<unsigned long>(actualFrequencyHz_),
      static_cast<unsigned>(config_.resolutionBits),
      config_.centerAngle, config_.minAngle, config_.maxAngle,
      static_cast<unsigned>(config_.minPulseUs),
      static_cast<unsigned>(config_.maxPulseUs),
      static_cast<unsigned>(config_.speedDegPerSec),
      static_cast<unsigned>(config_.stepIntervalMs));
  return true;
}

uint16_t Controller::pulseUsForTenths(int16_t tenths) const {
  int32_t clamped = tenths;
  if (clamped < 0) clamped = 0;
  if (clamped > kFullRangeTenths) clamped = kFullRangeTenths;
  const int32_t span =
      static_cast<int32_t>(config_.maxPulseUs) - config_.minPulseUs;
  const int32_t pulse =
      config_.minPulseUs + clamped * span / kFullRangeTenths;
  return static_cast<uint16_t>(pulse);
}

uint16_t Controller::pulseUsFor(int angle) const {
  int32_t tenths = angle * 10;
  if (tenths < 0) tenths = 0;
  if (tenths > kFullRangeTenths) tenths = kFullRangeTenths;
  return pulseUsForTenths(static_cast<int16_t>(tenths));
}

void Controller::writeCurrentAngle() {
  if (!ready_ || !outputEnabled_) return;
  const uint32_t periodUs = 1000000UL / actualFrequencyHz_;
  if (periodUs == 0) return;
  const uint32_t scale = 1UL << config_.resolutionBits;
  const uint32_t duty =
      static_cast<uint32_t>(pulseUsForTenths(currentTenths_)) * scale / periodUs;
  ledcWrite(config_.ledcChannel, duty);
}

bool Controller::setAngle(int angle) {
  if (!ready_ || !validAngle(angle)) return false;

  if (!outputEnabled_) {
    // Re-enable at the last known position first. This avoids a sudden jump to
    // a different angle when resuming after `servo stop`.
    outputEnabled_ = true;
    writeCurrentAngle();
  }

  targetTenths_ = static_cast<int16_t>(angle * 10);
  lastStepMs_ = millis();
  if (targetTenths_ == currentTenths_) {
    moving_ = false;
    return true;
  }
  moving_ = true;
  return true;
}

void Controller::stop() {
  moving_ = false;
  outputEnabled_ = false;
  if (ready_) ledcWrite(config_.ledcChannel, 0);
}

void Controller::update() {
  if (!ready_ || !moving_ || !outputEnabled_) return;
  const uint32_t now = millis();
  if (now - lastStepMs_ < config_.stepIntervalMs) return;
  lastStepMs_ = now;

  const int16_t delta = targetTenths_ - currentTenths_;
  const int16_t step = static_cast<int16_t>(stepTenths_);
  if (delta > 0) {
    currentTenths_ += (delta > step ? step : delta);
  } else {
    currentTenths_ -= (-delta > step ? step : -delta);
  }
  writeCurrentAngle();
  if (currentTenths_ == targetTenths_) moving_ = false;
}

const char* Controller::state() const {
  if (moving_) return "moving";
  if (outputEnabled_) return "idle";
  return "stopped";
}

void Controller::printStatus() const {
  Serial.printf(
      "SERVO state=%s ready=%u angle=%d target=%d pulse_us=%u output=%s "
      "pin=%u frequency_hz=%lu min=%d max=%d speed_dps=%u\n",
      state(), ready_ ? 1U : 0U, angle(), target(),
      outputEnabled_ ? pulseUsForTenths(currentTenths_) : 0,
      outputEnabled_ ? "on" : "off",
      static_cast<unsigned>(config_.pin),
      static_cast<unsigned long>(actualFrequencyHz_),
      config_.minAngle, config_.maxAngle,
      static_cast<unsigned>(config_.speedDegPerSec));
}

}  // namespace servo
