#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <esp32s3/spiram.h>

#ifndef RGB_LED_PIN
#error "Select diagnostics, rgb_gpio48, or rgb_gpio38 in PlatformIO."
#endif
static_assert(RGB_LED_PIN == -1 || RGB_LED_PIN == 48 || RGB_LED_PIN == 38,
              "Only the two documented candidate pins are supported.");

namespace {
constexpr uint8_t kBrightness = 24;  // About 9% of the 0..255 range.
constexpr uint32_t kColorDurationMs = 1000;

#if RGB_LED_PIN >= 0
Adafruit_NeoPixel led(1, RGB_LED_PIN, NEO_GRB + NEO_KHZ800);
struct Color {
  const char* name;
  uint8_t red;
  uint8_t green;
  uint8_t blue;
};
constexpr Color kColors[] = {
    {"RED", 255, 0, 0}, {"GREEN", 0, 255, 0}, {"BLUE", 0, 0, 255}};
size_t nextColor = 0;
#endif

void printHardware() {
  // ESP.getPsramSize() reports heap capacity after allocator overhead.
  // Use the chip capacity for the N16R8 check, and report both separately.
  const size_t psramBytes = psramFound() ? esp_spiram_get_size() : 0;
  Serial.printf("[hardware] chip=%s cores=%u flash=%lu psram_chip=%lu psram_heap=%lu\n",
                ESP.getChipModel(), ESP.getChipCores(),
                static_cast<unsigned long>(ESP.getFlashChipSize()),
                static_cast<unsigned long>(psramBytes),
                static_cast<unsigned long>(ESP.getPsramSize()));
  Serial.printf("[config] rgb_pin=%d brightness=%u interval_ms=%lu console=UART0\n",
                RGB_LED_PIN, kBrightness,
                static_cast<unsigned long>(kColorDurationMs));
  if (ESP.getFlashChipSize() != 16UL * 1024 * 1024 ||
      psramBytes != 8UL * 1024 * 1024) {
    Serial.println("[warning] Detected memory differs from reported N16R8; verify module/config.");
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  delay(1000);  // Bounded startup delay; runs even without a serial monitor.
  Serial.println("\n[experiment 001] RGB LED / Arduino");
  printHardware();
#if RGB_LED_PIN >= 0
  led.begin();
  led.setBrightness(kBrightness);
  led.clear();
  led.show();
#else
  Serial.println("[diagnostics] No RGB GPIO is driven. Select a candidate environment to test the LED.");
#endif
}

void loop() {
#if RGB_LED_PIN >= 0
  const Color& color = kColors[nextColor];
  led.setPixelColor(0, led.Color(color.red, color.green, color.blue));
  led.show();
  Serial.printf("[rgb] ms=%lu pin=%d color=%s (command sent; visual confirmation required)\n",
                static_cast<unsigned long>(millis()), RGB_LED_PIN, color.name);
  nextColor = (nextColor + 1) % (sizeof(kColors) / sizeof(kColors[0]));
#else
  // Repeat the hardware report so it can be captured after opening the monitor.
  printHardware();
#endif
  delay(kColorDurationMs);
}
