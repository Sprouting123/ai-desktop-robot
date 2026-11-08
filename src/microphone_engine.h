#pragma once
#include <Arduino.h>
#include <driver/i2s.h>

namespace mic {

// INMP441 wiring requested for experiment 010. The module is a digital I2S
// microphone with no configuration bus: SCK/WS are driven by the ESP32 and the
// 24-bit sample arrives in a 32-bit slot, left-justified. The module's L/R pin
// is wired to GND, but this specimen delivers samples in the right slot
// (measured 2026-11-08), so the engine selects I2S_CHANNEL_FMT_ONLY_RIGHT.
struct Config {
  uint8_t bclkPin;
  uint8_t wsPin;
  uint8_t dataPin;
  i2s_port_t port;
  uint32_t sampleRate;
  uint8_t bitsPerSlot;
  uint8_t dmaBufferCount;
  uint16_t blockFrames;
};

constexpr uint16_t kBlockFrames = 256;  // 16 ms at 16 kHz; one non-blocking read.
constexpr uint8_t kWindowBlocks = 32;   // About 0.5 s of recent statistics.
constexpr uint32_t kSettleFrames = 8000;   // 0.5 s discarded after i2s_start.
constexpr uint32_t kRecordFrames = 48000;  // Exactly 3.0 s at 16 kHz.
constexpr uint32_t kRecordBytes = kRecordFrames * sizeof(int16_t);

enum class RecordState : uint8_t { kIdle, kRecording, kReady };
// GPIO16/17/18 do not overlap the OLED (8/9), servos (4/5), MAX98357A (6/7/15)
// or RGB (48). Port 1 keeps the speaker's I2S_NUM_0 path untouched.
constexpr Config kDefaultConfig = {
    16,  // SCK / BCLK
    17,  // WS / LRC
    18,  // SD / DIN
    I2S_NUM_1,
    16000,
    32,  // Slot width; INMP441 carries 24 significant bits.
    4,
    kBlockFrames,
};

// Owns the RX-only I2S driver for the INMP441. It never installs a TX channel
// on this port and never touches the speaker engine on I2S_NUM_0. The driver is
// installed lazily on the first `mic start`, so boot does not clock the
// microphone or capture anything.
class Engine {
 public:
  explicit Engine(const Config& config = kDefaultConfig);
  ~Engine() { end(); }

  // Logs the configuration only. No driver install and no capture at boot.
  void begin();

  // Installs the driver on first use, then starts RX. Returns false when the
  // driver cannot be installed; capture state is then reported as error.
  bool start();
  // Stops the I2S peripheral but keeps the driver installed for a fast restart.
  // A recording in progress is discarded; a completed recording is kept.
  void stop();
  // Reads at most one DMA block per call with a zero timeout. Never waits.
  void update();
  void end();

  // Captures exactly kRecordFrames into a PSRAM (or internal heap) buffer.
  // Fails when a recording or dump is already active, or memory is unavailable.
  bool startRecording();
  // Begins a non-blocking serial dump of the last completed recording.
  bool startDump();
  bool dumpActive() const { return dumpActive_; }

  void printStatus() const;
  void printLevel() const;

  bool running() const { return running_; }
  bool ready() const { return installed_; }
  const char* state() const;
  uint32_t totalFrames() const { return totalFrames_; }
  uint32_t errors() const { return errors_; }
  RecordState recordState() const { return recordState_; }
  uint32_t recordedFrames() const { return recordFrames_; }
  uint32_t recordedBytes() const { return recordFrames_ * sizeof(int16_t); }
  uint32_t recordedCrc32() const { return recordCrc_; }

 private:
  bool install();
  void uninstall();
  void resetCapture();
  void pushBlock(uint32_t frames, uint32_t peak, uint64_t sumSquares,
                 bool allZero);
  void finishRecording();
  void emitDumpLine();
  const char* signalName() const;
  const char* recordName() const;
  static uint32_t crc32(const uint8_t* data, size_t length);

  struct BlockStat {
    uint32_t frames;
    uint32_t peak;
    uint64_t sumSquares;
    uint16_t zero;  // 1 when every sample in the block was exactly zero.
  };

  Config config_;
  int32_t words_[kBlockFrames] = {};  // One 32-bit RX slot per element.
  int16_t* recordBuffer_ = nullptr;   // kRecordBytes, PSRAM preferred.
  uint32_t recordFrames_ = 0;
  uint32_t settleFrames_ = 0;  // Startup samples still to discard.
  uint32_t recordCrc_ = 0;
  RecordState recordState_ = RecordState::kIdle;
  bool dumpActive_ = false;
  uint32_t dumpOffset_ = 0;
  uint32_t dumpLines_ = 0;
  BlockStat window_[kWindowBlocks] = {};
  uint8_t windowHead_ = 0;
  uint8_t windowCount_ = 0;
  uint64_t windowSumSquares_ = 0;
  uint32_t windowFrames_ = 0;
  uint32_t windowPeak_ = 0;
  uint16_t windowZeroBlocks_ = 0;
  uint32_t totalFrames_ = 0;
  uint32_t blocks_ = 0;
  uint32_t zeroBlocks_ = 0;
  uint32_t reads_ = 0;
  uint32_t timeouts_ = 0;
  uint32_t errors_ = 0;
  int32_t lastErrorCode_ = 0;
  bool installed_ = false;
  bool running_ = false;
  bool failed_ = false;
};

}  // namespace mic
