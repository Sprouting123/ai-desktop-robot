#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <esp32s3/spiram.h>
#include <cstdlib>
#include <cstring>

#include "audio_engine.h"
#include "audio_uploader.h"
#include "voice_clips.h"
#include "voice_receiver.h"
#include "eyes_engine.h"
#include "microphone_engine.h"
#include "mood_controller.h"
#include "motion_engine.h"
#include "servo_controller.h"
#include "wake_engine.h"
#include "web_server.h"
#include "wifi_manager.h"

// Local Wi-Fi credentials and the API token live in an untracked file. The
// project still builds without it; networking reports itself as disabled.
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef API_TOKEN
#define API_TOKEN ""
#endif
// Optional experiment 013 receiver. Empty values leave `mic upload` disabled;
// the firmware still builds and every local function keeps working.
#ifndef AUDIO_UPLOAD_HOST
#define AUDIO_UPLOAD_HOST ""
#endif
#ifndef AUDIO_UPLOAD_PORT
#define AUDIO_UPLOAD_PORT 0
#endif
#ifndef AUDIO_UPLOAD_PATH
#define AUDIO_UPLOAD_PATH "/upload"
#endif
#ifndef AUDIO_UPLOAD_TOKEN
#define AUDIO_UPLOAD_TOKEN ""
#endif

#ifndef RGB_LED_PIN
#error "Select diagnostics, rgb_gpio48, or rgb_gpio38 in PlatformIO."
#endif
static_assert(RGB_LED_PIN == -1 || RGB_LED_PIN == 48 || RGB_LED_PIN == 38,
              "Only the two documented candidate pins are supported.");

namespace {
constexpr uint8_t kBrightness = 24;
constexpr int kI2cSda = 8;
constexpr int kI2cScl = 9;
constexpr uint32_t kI2cFrequency = 100000;
constexpr uint16_t kI2cTimeoutMs = 25;
bool i2cReady = false;
constexpr uint8_t kOledAddress = 0x3C;
// Wire owns GPIO8/9. Leave U8g2 pins unset so its GPIO init does not
// reconfigure an already running ESP32 I2C bus during driver switches.
U8G2_SH1106_128X64_NONAME_F_HW_I2C sh1106(U8G2_R0, U8X8_PIN_NONE);
U8G2_SSD1306_128X64_NONAME_F_HW_I2C ssd1306(U8G2_R0, U8X8_PIN_NONE);
eyes::Engine eyesEngine(sh1106);
servo::Controller servo1Controller(servo::kDefaultConfig);
servo::Controller servo2Controller(servo::kServo2Config);
// The motion engine coordinates the two controllers; it never touches PWM
// directly and therefore cannot bypass the servo limits.
motion::Engine motionEngine(servo1Controller, servo2Controller);
// Mood couples one expression with one motion profile through the existing
// eyes and motion entry points.
mood::Controller moodController(eyesEngine, motionEngine);
// Audio is an independent I2S path (GPIO6/7/15). It shares no state with the
// eyes, servos or network layer and produces silence until an explicit beep.
audio::Engine audioEngine;
// The microphone owns I2S_NUM_1 in RX-only mode. It never installs a TX path
// and does not share state with the speaker engine on I2S_NUM_0.
mic::Engine microphoneEngine;
// Uploads the completed PSRAM recording over Wi-Fi without copying it. It is
// advanced one small step per loop and only starts on an explicit command.
upload::Client audioUploader(&microphoneEngine);
// Downloads the matching TTS reply into PSRAM and replays it through the same
// AudioEngine. Auto mode only reacts to a completed explicit `mic upload`.
reply::Client voiceClient(audioEngine, audioUploader);
// Offline WakeNet detection and VAD recording. It owns I2S_NUM_1 while running,
// so the manual microphone engine is mutually exclusive with it.
wake::Engine wakeEngine;
// Networking only calls the same controllers as the serial commands. It does
// not own a second copy of expression, motion or servo state.
wifi::Manager wifiManager;
web::Server webServer(wifiManager, eyesEngine, moodController, motionEngine,
                      servo1Controller, servo2Controller);
const char* oledDriver = "none";
bool oledDrawCalled = false;
bool eyesVisible = false;
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
  Serial.println("HELP red | green | blue | off | status | help | i2cscan | oled_sh1106 | oled_ssd1306 | oled_status | eyes <normal|happy|angry|sad|embarrassed|sympathy|comfort|melancholy|left|right> | eyes blink | eyes status | eyes dump | servo <60-120> | servo center | servo status | servo stop | servo1 <60-120> | servo1 center | servo1 status | servo1 stop | servo2 <60-120> | servo2 center | servo2 status | servo2 stop | servo both center | servo both stop | motion neutral | motion wiggle | motion together | motion alternate | motion stop | motion status | mood happy | mood sad | mood angry | mood normal | mood status | mood stop | wifi status | wifi reconnect | web status | audio beep | audio hello | audio stop | audio status | mic status | mic start | mic level | mic probe | mic stop | mic record | mic dump | mic upload | mic upload status | mic upload cancel | voice status | voice fetch | voice fetch newest | voice play | voice stop | voice auto on | voice auto off | wake status | wake start | wake stop; max_line=32; endings=LF/CR/CRLF");
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

void scanI2c() {
  if (!i2cReady) {
    Serial.println("ERR i2c_not_ready; reset to retry initialization");
    return;
  }
  Serial.printf("I2C_SCAN begin sda=%d scl=%d frequency_hz=%lu range=0x08-0x77\n",
                kI2cSda, kI2cScl, static_cast<unsigned long>(kI2cFrequency));
  unsigned found = 0;
  unsigned errors = 0;
  // Skip reserved addresses. Probe with address + STOP, no display data.
  // Synchronous command: each transaction has a timeout; LED state is untouched.
  for (uint8_t address = 0x08; address <= 0x77; ++address) {
    Wire.beginTransmission(address);
    const uint8_t result = Wire.endTransmission(true);
    if (result == 0) {
      ++found;
      Serial.printf("I2C_FOUND address=0x%02X\n", address);
    } else if (result != 2) {  // Address NACK is normal for an unused address.
      ++errors;
      Serial.printf("I2C_ERROR address=0x%02X code=%u\n", address, result);
    }
  }
  Serial.printf("I2C_SCAN done devices=%u errors=%u result=%s\n", found, errors,
                errors ? "bus_error" : (found ? "ok" : "no_devices"));
}

// Returns the requested display only after it responds at 0x3C. begin() runs
// only when the active driver changes, so repeated eye commands do not reset it.
U8G2* prepareDisplay(bool useSh1106) {
  if (!i2cReady) {
    Serial.println("ERR i2c_not_ready; reset to retry initialization");
    return nullptr;
  }
  Wire.beginTransmission(kOledAddress);
  const uint8_t probe = Wire.endTransmission(true);
  if (probe != 0) {
    Serial.printf("ERR oled_no_ack address=0x%02X code=%u\n", kOledAddress, probe);
    return nullptr;
  }
  const char* driver = useSh1106 ? "SH1106" : "SSD1306";
  U8G2& display =
      useSh1106 ? static_cast<U8G2&>(sh1106) : static_cast<U8G2&>(ssd1306);
  if (std::strcmp(oledDriver, driver) != 0) {
    display.setI2CAddress(kOledAddress << 1);  // U8g2 expects the shifted address.
    display.setBusClock(kI2cFrequency);
    display.begin();  // Library return value is not proof of physical success.
    Wire.setTimeOut(kI2cTimeoutMs);
    oledDriver = driver;
  }
  return &display;
}

void printOledStatus() {
  Serial.printf("OLED_STATUS driver=%s address=0x%02X draw_called=%u visual=unverified frequency_hz=%lu screen=%s\n",
                oledDriver, kOledAddress, oledDrawCalled ? 1U : 0U,
                static_cast<unsigned long>(Wire.getClock()),
                eyesVisible ? "eyes" : "test");
}

void showOledTest(bool useSh1106) {
  // Keep the eyes running if the requested driver cannot be prepared.
  U8G2* display = prepareDisplay(useSh1106);
  if (!display) return;
  eyesEngine.pause();
  eyesVisible = false;
  oledDrawCalled = false;
  display->clearBuffer();
  display->setDrawColor(1);
  display->drawFrame(0, 0, 128, 64);
  // Four distinct corner markers: filled square, frame, cross, diagonal cross.
  display->drawBox(2, 2, 5, 5);
  display->drawFrame(121, 2, 5, 5);
  display->drawHLine(2, 59, 5);
  display->drawVLine(4, 57, 5);
  display->drawLine(121, 57, 125, 61);
  display->drawLine(125, 57, 121, 61);
  display->setFont(u8g2_font_6x10_tf);
  display->drawStr(10, 18, "HELLO ESP32!");
  display->drawStr(10, 31, "OLED TEST 003");
  display->drawStr(10, 44, "I2C: 0x3C");
  display->drawStr(40, 59, oledDriver);
  display->sendBuffer();
  oledDrawCalled = true;
  // U8g2's Arduino transport does not propagate per-transfer Wire errors.
  // This ACK and completion log are software evidence, not an optical check.
  Wire.beginTransmission(kOledAddress);
  const uint8_t after = Wire.endTransmission(true);
  Serial.printf("OLED_DRAW driver=%s address=0x%02X probe_after=%u visual=unverified\n",
                oledDriver, kOledAddress, after);
  printOledStatus();
}

// The eyes always use the physically verified SH1106 path. Switching back from
// the SSD1306 test screen reinitializes SH1106 through prepareDisplay().
bool showEyes(eyes::Expression type, bool blinkNow, bool *started) {
  U8G2* display = prepareDisplay(true);
  if (!display) return false;
  const bool wasVisible = eyesVisible;
  eyesVisible = true;
  if (blinkNow && wasVisible) {
    // A blink command on the live eye screen must not reset a blink in
    // progress; the state model rejects or starts it.
    const bool b = eyesEngine.blink();
    if (started) *started = b;
  } else {
    eyesEngine.setExpression(type);
    if (blinkNow) {
      const bool b = eyesEngine.blink();
      if (started) *started = b;
    }
  }
  if (!wasVisible) {
    Serial.printf("EYES_MODE driver=SH1106 expression=%s auto_blink=1\n",
                  eyes::name(type));
  }
  return true;
}

void executeEyes(char* args) {
  if (*args == '\0') {
    Serial.println("ERR eyes_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    eyesEngine.printStatus();
    return;
  }
  if (std::strcmp(args, "blink") == 0) {
    bool started = false;
    if (!showEyes(eyesEngine.expression(), true, &started)) return;
    Serial.printf("OK blink expression=%s started=%u\n",
                  eyes::name(eyesEngine.expression()), started ? 1U : 0U);
    return;
  }
  if (std::strcmp(args, "dump") == 0) {
    // Debug preview only; it draws into the framebuffer without an I2C write.
    if (!eyesVisible && !showEyes(eyesEngine.expression(), false, nullptr)) return;
    eyesEngine.dump(Serial);
    return;
  }
  eyes::Expression type;
  if (!eyes::parse(args, type)) {
    Serial.println("ERR unknown_expression; use help");
    return;
  }
  if (!showEyes(type, false, nullptr)) return;
  // A direct eyes command breaks the mood/face mapping but never starts or
  // stops a servo action by itself.
  moodController.clear();
  Serial.printf("OK expression=%s\n", eyes::name(type));
}

// Any command that changes servo output takes manual control. Cancelling the
// sequence first prevents automatic targets and manual targets from competing.
// Only the commanded channel changes afterwards; the other servo finishes its
// last target and keeps holding it, exactly as in phase 1.
void takeManualServoControl() {
  motionEngine.cancel();
  moodController.clear();
}

// Shared command body for the legacy `servo` form (servo 1) and the explicit
// servo1/servo2 forms. name is used in OK lines, statusLabel in status output.
void executeServo(servo::Controller& controller, const char* name,
                  const char* statusLabel, char* args) {
  if (*args == '\0') {
    Serial.println("ERR servo_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    controller.printStatus(statusLabel);
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    // Explicit safe state: cancel movement and stop generating pulses.
    takeManualServoControl();
    controller.stop();
    Serial.printf("OK %s=stopped output=off\n", name);
    return;
  }
  if (std::strcmp(args, "center") == 0) {
    if (!controller.ready()) {
      Serial.println("ERR servo_not_ready");
      return;
    }
    takeManualServoControl();
    if (!controller.center()) {
      Serial.println("ERR servo_not_ready");
      return;
    }
    Serial.printf("OK %s=center angle=%d\n", name, controller.centerAngle());
    return;
  }

  char* end = nullptr;
  const long value = std::strtol(args, &end, 10);
  // Reject negative values, non-digits, trailing words and absurd values.
  // Values that parse but are outside the configured range get a separate error.
  if (end == args || *end != '\0' || value < 0 || value > 1000) {
    Serial.println("ERR servo_usage; use help");
    return;
  }
  const int angle = static_cast<int>(value);
  if (!controller.validAngle(angle)) {
    Serial.printf("ERR servo_range min=%d max=%d\n",
                  controller.minAngle(), controller.maxAngle());
    return;
  }
  if (!controller.ready()) {
    Serial.println("ERR servo_not_ready");
    return;
  }
  // Only a valid, ready command interrupts an automatic sequence. Rejected
  // arguments leave the current motion exactly as it was.
  takeManualServoControl();
  if (!controller.setAngle(angle)) {
    Serial.println("ERR servo_not_ready");
    return;
  }
  Serial.printf("OK %s=target angle=%d\n", name, angle);
}

void executeServoBoth(char* action) {
  if (std::strcmp(action, "center") == 0) {
    // Check both first so a failed controller cannot leave a half-applied
    // command; both share the same configuration and boot readiness.
    if (!servo1Controller.ready() || !servo2Controller.ready()) {
      Serial.println("ERR servo_not_ready");
      return;
    }
    takeManualServoControl();
    servo1Controller.center();
    servo2Controller.center();
    Serial.printf("OK servo1=center angle=%d\n", servo1Controller.centerAngle());
    Serial.printf("OK servo2=center angle=%d\n", servo2Controller.centerAngle());
    return;
  }
  if (std::strcmp(action, "stop") == 0) {
    // Requirement: this command also clears every automatic action and mood.
    motionEngine.stop();
    moodController.clear();
    servo1Controller.stop();
    servo2Controller.stop();
    Serial.println("OK servo1=stopped output=off");
    Serial.println("OK servo2=stopped output=off");
    return;
  }
  Serial.println("ERR servo_usage; use help");
}

void executeMotion(char* args) {
  if (*args == '\0') {
    Serial.println("ERR motion_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    motionEngine.printStatus();
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    // Cancel the remaining sequence and remove both pulses. The mood label no
    // longer describes the machine, but the face is deliberately kept.
    motionEngine.stop();
    moodController.clear();
    Serial.println("OK motion=stopped output=off");
    return;
  }
  motion::Kind kind;
  if (!motion::parse(args, kind)) {
    Serial.println("ERR motion_usage; use help");
    return;
  }
  if (!motionEngine.start(kind)) {
    Serial.println("ERR servo_not_ready");
    return;
  }
  // A manual motion replaces any coordinated mood, but not the expression.
  moodController.clear();
  Serial.printf("OK motion=%s steps=%u\n", motion::name(kind),
                static_cast<unsigned>(motionEngine.totalSteps()));
}

void executeMood(char* args) {
  if (*args == '\0') {
    Serial.println("ERR mood_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    moodController.printStatus();
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    // Explicitly report that the face is not reset: only the motion stops.
    moodController.stop();
    Serial.printf("OK mood=stopped output=off screen=kept expression=%s\n",
                  eyes::name(eyesEngine.expression()));
    return;
  }
  mood::Kind kind;
  if (!mood::parse(args, kind)) {
    Serial.println("ERR mood_usage; use help");
    return;
  }
  if (!moodController.start(kind)) {
    Serial.println("ERR servo_not_ready");
    return;
  }
  Serial.printf("OK mood=%s expression=%s motion=%s\n", mood::name(kind),
                eyes::name(eyesEngine.expression()), motion::name(motionEngine.kind()));
}

void executeWifi(char* args) {
  if (std::strcmp(args, "status") == 0) {
    wifiManager.printStatus();
    return;
  }
  if (std::strcmp(args, "reconnect") == 0) {
    if (!wifiManager.enabled()) {
      Serial.println("ERR wifi_disabled; fill in src/secrets.h and rebuild");
      return;
    }
    wifiManager.reconnect();
    Serial.println("OK wifi=reconnect");
    return;
  }
  Serial.println("ERR wifi_usage; use help");
}

void executeWeb(char* args) {
  if (std::strcmp(args, "status") == 0) {
    webServer.printStatus();
    return;
  }
  Serial.println("ERR web_usage; use help");
}

// Voice commands download the reply for the last upload turn and play it via
// the existing I2S path. They never start a recording or an upload.
void executeVoice(char* args) {
  if (*args == '\0') {
    Serial.println("ERR voice_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    voiceClient.printStatus();
    return;
  }
  if (std::strcmp(args, "fetch") == 0 ||
      std::strcmp(args, "fetch newest") == 0) {
    const bool newest = std::strcmp(args, "fetch newest") == 0;
    const reply::Client::StartResult result =
        newest ? voiceClient.fetchNewest() : voiceClient.fetchLatest();
    switch (result) {
      case reply::Client::StartResult::Ok:
        Serial.printf("OK voice=fetching mode=%s\n",
                      newest ? "newest" : "latest");
        return;
      case reply::Client::StartResult::Busy:
        Serial.println("ERR voice_busy");
        return;
      case reply::Client::StartResult::NotConfigured:
        Serial.println("ERR voice_not_configured");
        return;
      case reply::Client::StartResult::WifiDown:
        Serial.println("ERR voice_wifi");
        return;
      case reply::Client::StartResult::NoTurn:
        Serial.println("ERR voice_bad_turn");
        return;
    }
    return;
  }
  if (std::strcmp(args, "play") == 0) {
    if (!voiceClient.hasClip()) {
      Serial.println("ERR voice_no_clip");
      return;
    }
    if (!voiceClient.play()) {
      Serial.println("ERR voice_play_failed");
      return;
    }
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    const bool wasDownload = voiceClient.active();
    const bool wasPlaying = voiceClient.playing();
    voiceClient.cancel();
    if (wasPlaying) audioEngine.stop();
    Serial.printf("OK voice=stopped download=%u playback=%u\n",
                  wasDownload ? 1U : 0U, wasPlaying ? 1U : 0U);
    return;
  }
  if (std::strncmp(args, "auto", 4) == 0 &&
      (args[4] == '\0' || args[4] == ' ' || args[4] == '\t')) {
    char* action = args + 4;
    while (*action == ' ' || *action == '\t') ++action;
    if (std::strcmp(action, "on") == 0) {
      voiceClient.setAuto(true);
      Serial.println("OK voice=auto enabled=1");
      return;
    }
    if (std::strcmp(action, "off") == 0) {
      voiceClient.setAuto(false);
      Serial.println("OK voice=auto enabled=0");
      return;
    }
  }
  Serial.println("ERR voice_usage; use help");
}

// ---------------------------------------------------------------------------
// Experiment 016: wake-initiated dialog.
//
// The wake engine only reports a finalized VAD clip. This layer starts exactly
// one upload per clip through the existing upload::Client, then lets the
// existing voice auto mode fetch and play the reply. While an upload, download
// or playback is active the wake engine is suppressed (half duplex), so the
// speaker cannot trigger the microphone.
// ---------------------------------------------------------------------------
uint32_t handledWakeReady = 0;
uint32_t wakeReadyAtMs = 0;
uint32_t wakeCooldownUntilMs = 0;
bool wakeUploadPending = false;
bool wakeWaitLogged = false;

const char* uploadResultName(upload::Client::StartResult result) {
  switch (result) {
    case upload::Client::StartResult::Ok: return "ok";
    case upload::Client::StartResult::Busy: return "busy";
    case upload::Client::StartResult::NoRecording: return "no_recording";
    case upload::Client::StartResult::DumpBusy: return "dump_busy";
    case upload::Client::StartResult::NotConfigured: return "not_configured";
    case upload::Client::StartResult::WifiDown: return "wifi_down";
  }
  return "unknown";
}

void resetWakeDialogState() {
  handledWakeReady = 0;
  wakeReadyAtMs = 0;
  wakeCooldownUntilMs = 0;
  wakeUploadPending = false;
  wakeWaitLogged = false;
}

bool startWakeEngine() {
  if (wakeEngine.running()) {
    Serial.println("WAKE_ALREADY running=1");
    return true;
  }
  if (audioUploader.active()) {
    Serial.println("ERR wake_upload_busy");
    return false;
  }
  if (microphoneEngine.recordState() == mic::RecordState::kRecording ||
      microphoneEngine.dumpActive()) {
    Serial.println("ERR wake_mic_busy");
    return false;
  }
  if (voiceClient.active()) {
    Serial.println("ERR wake_voice_busy");
    return false;
  }
  if (audioEngine.playing() || voiceClient.playing()) {
    Serial.println("ERR wake_audio_busy");
    return false;
  }
  // I2S_NUM_1 has one owner. Release the manual driver; a completed manual
  // recording is discarded, so upload it before starting the wake engine.
  if (microphoneEngine.ready()) microphoneEngine.end();
  resetWakeDialogState();
  return wakeEngine.start();
}

void finishWakeClip(const char* reason) {
  Serial.printf("WAKE_UPLOAD_SKIP reason=%s\n", reason);
  handledWakeReady = wakeEngine.readyCount();
  wakeEngine.releaseRecording();
  wakeReadyAtMs = 0;
  wakeWaitLogged = false;
}

// Called once per loop after uploader.update() and voiceClient.update().
void updateWakeDialog() {
  if (!wakeEngine.running()) return;

  if (wakeUploadPending && !audioUploader.active()) {
    const bool done = std::strcmp(audioUploader.stateName(), "done") == 0;
    const char* turn = audioUploader.lastTurn();
    Serial.printf("WAKE_UPLOAD_RESULT state=%s turn=%s\n",
                  audioUploader.stateName(),
                  (done && turn[0] != '\0') ? turn : "-");
    wakeUploadPending = false;
    handledWakeReady = wakeEngine.readyCount();
    wakeEngine.releaseRecording();
    wakeReadyAtMs = 0;
    wakeWaitLogged = false;
    wakeCooldownUntilMs = millis() + 800;
  }

  if (wakeEngine.readyCount() == handledWakeReady) return;
  if (wakeUploadPending) return;
  if (audioUploader.active() || voiceClient.active()) return;
  if (!wakeEngine.hasRecording()) {
    handledWakeReady = wakeEngine.readyCount();
    return;
  }

  const uint32_t now = millis();
  if (wakeReadyAtMs == 0) wakeReadyAtMs = now == 0 ? 1 : now;
  if (!audioUploader.configured()) {
    finishWakeClip("not_configured");
    return;
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (now - wakeReadyAtMs >= 10000) {
      finishWakeClip("wifi_timeout");
      return;
    }
    if (!wakeWaitLogged) {
      wakeWaitLogged = true;
      Serial.println("WAKE_UPLOAD_WAIT reason=wifi");
    }
    return;
  }

  const upload::Client::StartResult result = audioUploader.start(wakeEngine);
  if (result == upload::Client::StartResult::Ok) {
    wakeUploadPending = true;
    Serial.printf("WAKE_UPLOAD_START bytes=%lu frames=%lu crc32=%08lx\n",
                  static_cast<unsigned long>(wakeEngine.bytes()),
                  static_cast<unsigned long>(wakeEngine.frames()),
                  static_cast<unsigned long>(wakeEngine.crc32()));
  } else {
    finishWakeClip(uploadResultName(result));
  }
}

void updateWakeSuppression() {
  const bool busy = audioUploader.active() || wakeUploadPending ||
                    voiceClient.active() || voiceClient.playing() ||
                    audioEngine.playing();
  const uint32_t now = millis();
  if (busy) wakeCooldownUntilMs = now + 1200;
  const bool cooldown =
      static_cast<int32_t>(wakeCooldownUntilMs - now) > 0;
  wakeEngine.setSuppressed(busy || cooldown);
}

void executeWake(char* args) {
  if (*args == '\0') {
    Serial.println("ERR wake_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    wakeEngine.printStatus();
    return;
  }
  if (std::strcmp(args, "start") == 0) {
    if (!startWakeEngine()) {
      Serial.println("ERR wake_start_failed");
      return;
    }
    Serial.printf("OK wake=started state=%s\n", wakeEngine.stateName());
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    if (audioUploader.active() || wakeUploadPending) {
      Serial.println("ERR wake_upload_busy");
      return;
    }
    wakeEngine.stop();
    Serial.println("OK wake=stopped");
    return;
  }
  Serial.println("ERR wake_usage; use help");
}

// Audio commands only control local playback (the test tone or the embedded
// voice clip). They never trigger a motion, expression or network action, and
// playback is never started at boot.
void executeAudio(char* args) {
  if (*args == '\0') {
    Serial.println("ERR audio_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    audioEngine.printStatus();
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    audioEngine.stop();
    Serial.println("OK audio=stopped output=silent");
    return;
  }
  if (std::strcmp(args, "beep") == 0) {
    const bool wasPlaying = audioEngine.playing();
    if (!audioEngine.beep()) {
      // Initialization is retried inside beep(); a hard failure is reported
      // instead of crashing or blocking the loop.
      Serial.println("ERR audio_not_ready");
      return;
    }
    Serial.printf("OK audio=beep tone_hz=%u duration_ms=%u amplitude_pct=%u restarted=%u\n",
                  audioEngine.toneHz(), audioEngine.durationMs(),
                  audioEngine.amplitudePercent(), wasPlaying ? 1U : 0U);
    return;
  }
  if (std::strcmp(args, "hello") == 0) {
    const audio::Clip& clip = voice::helloClip();
    const bool wasPlaying = audioEngine.playing();
    if (!audioEngine.playClip(clip)) {
      // ready() is only true after a successful install, so a failure there
      // means the driver is unavailable; otherwise the asset metadata was
      // rejected before any flash read.
      Serial.println(audioEngine.ready() ? "ERR audio_clip_invalid"
                                         : "ERR audio_not_ready");
      return;
    }
    const uint32_t frames = audioEngine.clipFrames();
    const uint32_t durationMs =
        voice::kSampleRate == 0
            ? 0
            : static_cast<uint32_t>(
                  (static_cast<uint64_t>(frames) * 1000) / voice::kSampleRate);
    Serial.printf(
        "OK audio=hello clip=%s bytes=%lu frames=%lu duration_ms=%lu "
        "volume_pct=%u sample_rate_hz=%lu restarted=%u\n",
        clip.name, static_cast<unsigned long>(audioEngine.clipBytes()),
        static_cast<unsigned long>(frames),
        static_cast<unsigned long>(durationMs), clip.volumePercent,
        static_cast<unsigned long>(voice::kSampleRate), wasPlaying ? 1U : 0U);
    return;
  }
  Serial.println("ERR audio_usage; use help");
}

// The wake engine owns I2S_NUM_1 while it runs. Commands that would install or
// capture with the manual microphone driver must stop it first; status, dump
// and upload of an existing clip stay available.
bool rejectMicWhileWake() {
  if (!wakeEngine.running()) return false;
  Serial.println("ERR mic_wake_active; run wake stop first");
  return true;
}

// Microphone commands only control local capture. They never record to flash,
// save a file, upload data or start a network action, and capture is off at
// boot. `mic level` reads the rolling window statistics; it never blocks.
void executeMic(char* args) {
  if (*args == '\0') {
    Serial.println("ERR mic_usage; use help");
    return;
  }
  if (std::strcmp(args, "status") == 0) {
    microphoneEngine.printStatus();
    return;
  }
  if (std::strcmp(args, "level") == 0) {
    microphoneEngine.printLevel();
    return;
  }
  if (std::strcmp(args, "probe") == 0) {
    if (rejectMicWhileWake()) return;
    if (audioUploader.active()) {
      Serial.println("ERR mic_upload_busy");
      return;
    }
    if (microphoneEngine.dumpActive()) {
      Serial.println("ERR mic_dump_busy");
      return;
    }
    if (microphoneEngine.recordState() == mic::RecordState::kRecording) {
      Serial.println("ERR mic_recording");
      return;
    }
    if (!microphoneEngine.probeChannels()) {
      Serial.println("ERR mic_probe_failed");
      return;
    }
    Serial.println("OK mic=probe");
    return;
  }
  if (std::strcmp(args, "start") == 0) {
    if (rejectMicWhileWake()) return;
    if (audioUploader.active()) {
      Serial.println("ERR mic_upload_busy");
      return;
    }
    if (microphoneEngine.dumpActive()) {
      Serial.println("ERR mic_dump_busy");
      return;
    }
    if (microphoneEngine.recordState() == mic::RecordState::kRecording) {
      Serial.println("ERR mic_recording");
      return;
    }
    const bool wasRunning = microphoneEngine.running();
    if (!microphoneEngine.start()) {
      Serial.println("ERR mic_not_ready");
      return;
    }
    Serial.printf("OK mic=started running=1 restarted=%u\n",
                  wasRunning ? 1U : 0U);
    return;
  }
  if (std::strcmp(args, "stop") == 0) {
    if (audioUploader.active()) {
      // Cancel the transfer but keep the completed recording for a retry.
      audioUploader.cancel();
      return;
    }
    microphoneEngine.stop();
    Serial.println("OK mic=stopped running=0");
    return;
  }
  if (std::strcmp(args, "record") == 0) {
    if (rejectMicWhileWake()) return;
    if (audioUploader.active()) {
      Serial.println("ERR mic_upload_busy");
      return;
    }
    if (microphoneEngine.dumpActive()) {
      Serial.println("ERR mic_dump_busy");
      return;
    }
    if (microphoneEngine.recordState() == mic::RecordState::kRecording) {
      Serial.println("ERR mic_recording");
      return;
    }
    if (!microphoneEngine.startRecording()) {
      Serial.println("ERR mic_record_failed");
      return;
    }
    Serial.printf("OK mic=recording frames=%lu duration_ms=%lu\n",
                  static_cast<unsigned long>(mic::kRecordFrames),
                  static_cast<unsigned long>(mic::kRecordFrames * 1000UL /
                                             mic::kDefaultConfig.sampleRate));
    return;
  }
  if (std::strcmp(args, "dump") == 0) {
    if (audioUploader.active()) {
      Serial.println("ERR mic_upload_busy");
      return;
    }
    if (microphoneEngine.dumpActive()) {
      Serial.println("ERR mic_dump_busy");
      return;
    }
    if (microphoneEngine.recordState() == mic::RecordState::kRecording) {
      Serial.println("ERR mic_recording");
      return;
    }
    if (!microphoneEngine.startDump()) {
      Serial.println("ERR mic_no_recording");
      return;
    }
    return;
  }
  if (std::strncmp(args, "upload", 6) == 0 &&
      (args[6] == '\0' || args[6] == ' ' || args[6] == '\t')) {
    char* sub = args + 6;
    while (*sub == ' ' || *sub == '\t') ++sub;
    if (*sub != '\0') {
      if (std::strcmp(sub, "status") == 0) {
        audioUploader.printStatus();
        return;
      }
      if (std::strcmp(sub, "cancel") == 0) {
        audioUploader.cancel();
        return;
      }
      Serial.println("ERR mic_usage; use help");
      return;
    }
    if (audioUploader.active()) {
      Serial.println("ERR mic_upload_busy");
      return;
    }
    if (microphoneEngine.recordState() == mic::RecordState::kRecording) {
      Serial.println("ERR mic_recording");
      return;
    }
    if (microphoneEngine.dumpActive()) {
      Serial.println("ERR mic_dump_busy");
      return;
    }
    switch (audioUploader.start(microphoneEngine)) {
      case upload::Client::StartResult::Ok:
        return;
      case upload::Client::StartResult::Busy:
        Serial.println("ERR mic_upload_busy");
        return;
      case upload::Client::StartResult::DumpBusy:
        Serial.println("ERR mic_dump_busy");
        return;
      case upload::Client::StartResult::NoRecording:
        Serial.println("ERR mic_no_recording");
        return;
      case upload::Client::StartResult::NotConfigured:
        Serial.println("ERR mic_upload_not_configured");
        return;
      case upload::Client::StartResult::WifiDown:
        Serial.println("ERR mic_upload_wifi");
        return;
    }
    return;
  }
  Serial.println("ERR mic_usage; use help");
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
  } else if (std::strcmp(text, "i2cscan") == 0) {
    scanI2c();
  } else if (std::strcmp(text, "oled_sh1106") == 0) {
    showOledTest(true);
  } else if (std::strcmp(text, "oled_ssd1306") == 0) {
    showOledTest(false);
  } else if (std::strcmp(text, "oled_status") == 0) {
    printOledStatus();
  } else if (std::strncmp(text, "eyes", 4) == 0 &&
             (text[4] == '\0' || isPadding(text[4]))) {
    char* args = text + 4;
    while (isPadding(*args)) ++args;
    executeEyes(args);
  } else if (std::strncmp(text, "motion", 6) == 0 &&
             (text[6] == '\0' || isPadding(text[6]))) {
    char* args = text + 6;
    while (isPadding(*args)) ++args;
    executeMotion(args);
  } else if (std::strncmp(text, "mood", 4) == 0 &&
             (text[4] == '\0' || isPadding(text[4]))) {
    char* args = text + 4;
    while (isPadding(*args)) ++args;
    executeMood(args);
  } else if (std::strncmp(text, "wifi", 4) == 0 &&
             (text[4] == '\0' || isPadding(text[4]))) {
    char* args = text + 4;
    while (isPadding(*args)) ++args;
    executeWifi(args);
  } else if (std::strncmp(text, "web", 3) == 0 &&
             (text[3] == '\0' || isPadding(text[3]))) {
    char* args = text + 3;
    while (isPadding(*args)) ++args;
    executeWeb(args);
  } else if (std::strncmp(text, "audio", 5) == 0 &&
             (text[5] == '\0' || isPadding(text[5]))) {
    char* args = text + 5;
    while (isPadding(*args)) ++args;
    executeAudio(args);
  } else if (std::strncmp(text, "mic", 3) == 0 &&
             (text[3] == '\0' || isPadding(text[3]))) {
    char* args = text + 3;
    while (isPadding(*args)) ++args;
    executeMic(args);
  } else if (std::strncmp(text, "voice", 5) == 0 &&
             (text[5] == '\0' || isPadding(text[5]))) {
    char* args = text + 5;
    while (isPadding(*args)) ++args;
    executeVoice(args);
  } else if (std::strncmp(text, "wake", 4) == 0 &&
             (text[4] == '\0' || isPadding(text[4]))) {
    char* args = text + 4;
    while (isPadding(*args)) ++args;
    executeWake(args);
  } else if (std::strncmp(text, "servo1", 6) == 0 &&
             (text[6] == '\0' || isPadding(text[6]))) {
    char* args = text + 6;
    while (isPadding(*args)) ++args;
    executeServo(servo1Controller, "servo1", "SERVO1", args);
  } else if (std::strncmp(text, "servo2", 6) == 0 &&
             (text[6] == '\0' || isPadding(text[6]))) {
    char* args = text + 6;
    while (isPadding(*args)) ++args;
    executeServo(servo2Controller, "servo2", "SERVO2", args);
  } else if (std::strncmp(text, "servo", 5) == 0 &&
             (text[5] == '\0' || isPadding(text[5]))) {
    char* args = text + 5;
    while (isPadding(*args)) ++args;
    if (std::strncmp(args, "both", 4) == 0 &&
        (args[4] == '\0' || isPadding(args[4]))) {
      char* action = args + 4;
      while (isPadding(*action)) ++action;
      executeServoBoth(action);
    } else {
      // Legacy `servo ...` keeps its experiment 005 meaning: servo 1.
      executeServo(servo1Controller, "servo", "SERVO", args);
    }
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
  Serial.println("\n[experiment 016] wake word / Arduino");
  i2cReady = Wire.begin(kI2cSda, kI2cScl, kI2cFrequency);
  Wire.setTimeOut(kI2cTimeoutMs);
  Serial.printf("I2C_INIT ready=%u sda=%d scl=%d frequency_hz=%lu timeout_ms=%u\n",
                i2cReady ? 1U : 0U, kI2cSda, kI2cScl,
                static_cast<unsigned long>(kI2cFrequency), kI2cTimeoutMs);
  printHardware();
  // No pulses on either channel until an explicit servo command, so boot and
  // the first flash of experiment 006 cannot start an automatic sweep.
  servo1Controller.begin("SERVO1");
  servo2Controller.begin("SERVO2");
  // Installing I2S only drives clocks with zeroed DMA data. No tone is played
  // at boot; the first sound requires an explicit `audio beep` or `audio hello`.
  audioEngine.begin();
  // Report the linked asset's real length, which comes from the linker symbols
  // rather than a hand-maintained constant.
  const audio::Clip& hello = voice::helloClip();
  Serial.printf(
      "AUDIO_CLIP name=%s bytes=%lu frames=%lu sample_rate_hz=%lu volume_pct=%u\n",
      hello.name, static_cast<unsigned long>(hello.bytes),
      static_cast<unsigned long>(hello.bytes / sizeof(int16_t)),
      static_cast<unsigned long>(hello.sampleRate), hello.volumePercent);
  // Report the microphone plan without installing the RX driver: capture stays
  // off and the INMP441 sees no clocks until an explicit `mic start`.
  microphoneEngine.begin();
  // The wake engine reports its plan only; I2S and ESP-SR start after the
  // local subsystems have been initialized.
  wakeEngine.begin();
  // Copy and validate the optional receiver settings. Nothing connects and no
  // audio moves until an explicit `mic upload`; the token is never logged.
  audioUploader.begin(AUDIO_UPLOAD_HOST, AUDIO_UPLOAD_PORT, AUDIO_UPLOAD_PATH,
                      AUDIO_UPLOAD_TOKEN);
  // The reply download reuses the receiver host, port and token; only the
  // path differs (/reply/latest). Auto playback is on, but it starts only
  // after an explicit upload succeeds.
  voiceClient.begin(AUDIO_UPLOAD_HOST, AUDIO_UPLOAD_PORT, AUDIO_UPLOAD_TOKEN);
  printStatus();
  printHelp();
  showEyes(eyes::Expression::Normal, false, nullptr);
  // Both calls only configure state or start a background attempt; no wait.
  // With an empty SSID the network stays disabled and every local function
  // (OLED, servos, serial) continues to work.
  wifiManager.begin(WIFI_SSID, WIFI_PASSWORD);
  webServer.begin(API_TOKEN);
  wifiManager.printStatus();
  webServer.printStatus();
  // Formal firmware behavior: start listening at boot. If the model partition
  // is missing, the engine reports the reason and every other subsystem keeps
  // working; `wake start` can retry later.
  Serial.println("WAKE_AUTO_START model=nihaoxiaozhi half_duplex=1");
  if (!wakeEngine.start()) {
    Serial.println("WAKE_START_FAILED reason=auto; local functions continue");
  }
}

void loop() {
  // Read only bytes already available: no readStringUntil(), timeout wait or delay().
  for (size_t count = 0; count < kReadBudget && Serial.available() > 0; ++count) {
    const int ch = Serial.read();
    if (ch < 0) break;
    receiveByte(static_cast<uint8_t>(ch));
  }
  // Networking is advanced in small steps. It never waits for a connection or
  // a whole HTTP request, so the OLED and servo schedules below keep running.
  wifiManager.update();
  webServer.update();
  // One small upload step per loop: no wait for the socket, and the completed
  // PSRAM recording is read in place.
  audioUploader.update();
  // One small reply-download step per loop. Auto mode observes the uploader's
  // success counter; playback still goes through AudioEngine below.
  voiceClient.update();
  // Wake-initiated dialog: one automatic upload per finalized VAD clip, then
  // the existing voice auto mode fetches and plays the answer.
  updateWakeDialog();
  // Half duplex: no new wake word while uploading, downloading, playing, or
  // during the short echo cooldown after playback.
  updateWakeSuppression();
  // Audio streams one small chunk per loop and never waits for the DMA queue.
  audioEngine.update();
  // One non-blocking RX read per loop; capture only runs after `mic start`.
  microphoneEngine.update();
  // One dirty display region per loop; never blocks waiting for a full frame.
  eyesEngine.update();
  // The motion engine only advances a state machine and sets new targets; it
  // never waits for a servo to arrive.
  motionEngine.update();
  // One small step per servo at most; their 20 ms schedules are independent of
  // OLED I/O and of each other. Channels 0 and 1 share timer 0 by design, but
  // each controller owns its angle, target and movement state.
  servo1Controller.update();
  servo2Controller.update();
}
