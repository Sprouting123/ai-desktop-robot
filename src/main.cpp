#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <esp32s3/spiram.h>
#include <cstring>

#ifndef RGB_LED_PIN
#error "Select diagnostics, rgb_gpio48, or rgb_gpio38 in PlatformIO."
#endif
static_assert(RGB_LED_PIN == -1 || RGB_LED_PIN == 48 || RGB_LED_PIN == 38,
              "Only the two documented candidate pins are supported.");

namespace {
constexpr uint8_t kBrightness = 24;
constexpr size_t kMaxCommandLength = 32;  // Excludes CR / LF, includes whitespace.
constexpr size_t kReadBudget = 64;        // Return to loop() even under continuous input.

struct Color {
  const char* name;
  uint8_t red;
  uint8_t green;
  uint8_t blue;
};
constexpr Color kColors[] = {
    {"red", 255, 0, 0}, {"green", 0, 255, 0},
    {"blue", 0, 0, 255}, {"off", 0, 0, 0}};
const Color* currentColor = &kColors[3];

#if RGB_LED_PIN >= 0
Adafruit_NeoPixel led(1, RGB_LED_PIN, NEO_GRB + NEO_KHZ800);
#endif

char command[kMaxCommandLength + 1] = {};
size_t commandLength = 0;
bool previousWasCR = false;
enum class LineError { None, TooLong, InvalidCharacter };
LineError lineError = LineError::None;

void printHardware() {
  // Physical capacity and allocator-managed heap capacity are different values.
  const size_t psramBytes = psramFound() ? esp_spiram_get_size() : 0;
  Serial.printf("[hardware] chip=%s cores=%u flash=%lu psram_chip=%lu psram_heap=%lu\n",
                ESP.getChipModel(), ESP.getChipCores(),
                static_cast<unsigned long>(ESP.getFlashChipSize()),
                static_cast<unsigned long>(psramBytes),
                static_cast<unsigned long>(ESP.getPsramSize()));
  if (ESP.getFlashChipSize() != 16UL * 1024 * 1024 ||
      psramBytes != 8UL * 1024 * 1024) {
    Serial.println("[warning] Detected memory differs from reported N16R8; verify module/config.");
  }
}

void printHelp() {
  Serial.println("HELP red | green | blue | off | status | help; max_line=32; endings=LF/CR/CRLF");
}

void printStatus() {
  // This reports the last commanded state, not an optical measurement.
  Serial.printf("STATUS state=%s pin=%d enabled=%u brightness=%u uptime_ms=%lu\n",
                currentColor->name, RGB_LED_PIN, RGB_LED_PIN >= 0 ? 1U : 0U,
                kBrightness, static_cast<unsigned long>(millis()));
}

void applyColor(const Color& color) {
#if RGB_LED_PIN >= 0
  led.setPixelColor(0, led.Color(color.red, color.green, color.blue));
  led.show();
  currentColor = &color;
  Serial.printf("OK state=%s pin=%d\n", color.name, RGB_LED_PIN);
#else
  Serial.println("ERR led_disabled; select rgb_gpio48 for this board");
#endif
}

bool isPadding(char ch) { return ch == ' ' || ch == '\t'; }

void executeCommand() {
  command[commandLength] = '\0';
  while (commandLength > 0 && isPadding(command[commandLength - 1])) {
    command[--commandLength] = '\0';
  }
  char* text = command;
  while (isPadding(*text)) ++text;
  if (*text == '\0') return;  // Empty/whitespace-only lines produce no response.

  for (char* p = text; *p; ++p) {
    if (*p >= 'A' && *p <= 'Z') *p += 'a' - 'A';
  }
  if (std::strcmp(text, "help") == 0) {
    printHelp();
  } else if (std::strcmp(text, "status") == 0) {
    printStatus();
  } else {
    for (const Color& color : kColors) {
      if (std::strcmp(text, color.name) == 0) {
        applyColor(color);
        return;
      }
    }
    Serial.println("ERR unknown_command; use help");
  }
}

void receiveByte(uint8_t ch) {
  if (ch == '\r' || ch == '\n') {
    if (ch == '\n' && previousWasCR) {
      previousWasCR = false;  // CRLF is one terminator, not two commands.
      return;
    }
    previousWasCR = ch == '\r';
    if (lineError == LineError::TooLong) {
      Serial.println("ERR line_too_long; max=32; discarded");
    } else if (lineError == LineError::InvalidCharacter) {
      Serial.println("ERR invalid_character; use ASCII commands; discarded");
    } else {
      executeCommand();
    }
    commandLength = 0;
    lineError = LineError::None;
    return;
  }

  previousWasCR = false;
  // Once rejected, discard the whole line, including any valid-looking suffix.
  if (lineError != LineError::None) return;
  if (ch == '\b' || ch == 0x7f) {  // Terminal Backspace / Delete.
    if (commandLength > 0) --commandLength;
    return;
  }
  if ((ch < 0x20 && ch != '\t') || ch > 0x7e) {
    lineError = LineError::InvalidCharacter;
    return;
  }
  if (commandLength == kMaxCommandLength) {
    lineError = LineError::TooLong;
    return;
  }
  command[commandLength++] = static_cast<char>(ch);
}
}  // namespace

void setup() {
  Serial.begin(115200);
#if RGB_LED_PIN >= 0
  led.begin();
  led.setBrightness(kBrightness);
  led.clear();
  led.show();
#endif
  Serial.println("\n[experiment 002] Serial RGB LED / Arduino");
  printHardware();
  printStatus();
  printHelp();
}

void loop() {
  // Read only bytes already available: no readStringUntil(), timeout wait or delay().
  for (size_t count = 0; count < kReadBudget && Serial.available() > 0; ++count) {
    const int ch = Serial.read();
    if (ch < 0) break;
    receiveByte(static_cast<uint8_t>(ch));
  }
}
