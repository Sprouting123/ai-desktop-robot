// 实验 016 第二阶段：SH1106 128x64 状态提示实现。
// 接线与主工程一致：VCC 3V3、GND、SDA GPIO8、SCL GPIO9，地址 0x3C。
#include "oled.h"

#include <stdio.h>
#include <string.h>

#include "driver/i2c.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "u8g2.h"

#define OLED_I2C_PORT I2C_NUM_0
#define OLED_SDA_GPIO 8
#define OLED_SCL_GPIO 9
#define OLED_ADDR 0x3C
#define OLED_I2C_HZ 100000

static u8g2_t s_u8g2;
static SemaphoreHandle_t s_lock = NULL;
static volatile bool s_ready = false;
static volatile esp_err_t s_last_i2c = ESP_OK;
static volatile int s_fail_len = -1;
static volatile uint8_t s_fail_b0 = 0;
static volatile uint8_t s_fail_b1 = 0;

// U8g2 的 CAD 层会把“控制字节 + 命令/数据”拆成多次 U8X8_MSG_BYTE_SEND
// （每次 1 字节），因此必须在一个 START/END_TRANSFER 周期内缓存后一次性发送；
// 若逐字节单独发 I²C 事务，控制字节会丢失，OLED 只看到 0x10 这类裸命令。
static uint8_t s_tx[160];
static size_t s_tx_len = 0;

static uint8_t byte_i2c(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int,
                        void *arg_ptr) {
  (void)u8x8;
  switch (msg) {
    case U8X8_MSG_BYTE_INIT:
    case U8X8_MSG_BYTE_SET_DC:
      break;
    case U8X8_MSG_BYTE_START_TRANSFER:
      s_tx_len = 0;
      break;
    case U8X8_MSG_BYTE_SEND:
      if (arg_int == 0) break;
      if (s_tx_len + arg_int > sizeof(s_tx)) {
        s_last_i2c = ESP_FAIL;
        s_fail_len = -1;
        break;
      }
      memcpy(s_tx + s_tx_len, arg_ptr, arg_int);
      s_tx_len += arg_int;
      break;
    case U8X8_MSG_BYTE_END_TRANSFER: {
      if (s_tx_len == 0) break;
      esp_err_t err = i2c_master_write_to_device(
          OLED_I2C_PORT, OLED_ADDR, s_tx, s_tx_len, pdMS_TO_TICKS(200));
      if (err != ESP_OK && s_last_i2c == ESP_OK) {
        s_last_i2c = err;
        s_fail_len = (int)s_tx_len;
        s_fail_b0 = s_tx[0];
        s_fail_b1 = s_tx_len > 1 ? s_tx[1] : 0;
      }
      s_tx_len = 0;
      break;
    }
    default:
      return 0;
  }
  return 1;
}

static uint8_t gpio_delay(u8x8_t *u8x8, uint8_t msg, uint8_t arg_int,
                          void *arg_ptr) {
  (void)u8x8;
  (void)arg_ptr;
  switch (msg) {
    case U8X8_MSG_GPIO_AND_DELAY_INIT:
      break;
    case U8X8_MSG_DELAY_MILLI:
      vTaskDelay(pdMS_TO_TICKS(arg_int));
      break;
    case U8X8_MSG_DELAY_10MICRO:
      esp_rom_delay_us((uint32_t)arg_int * 10u);
      break;
    case U8X8_MSG_DELAY_100NANO:
      esp_rom_delay_us(1);
      break;
    case U8X8_MSG_GPIO_I2C_CLOCK:
    case U8X8_MSG_GPIO_I2C_DATA:
      break;
    default:
      return 0;
  }
  return 1;
}

// 启动时扫描 0x08–0x77，只报告应答地址，便于判断接线而不是猜。
static void oled_scan(void) {
  int found = 0;
  for (uint8_t addr = 0x08; addr <= 0x77; ++addr) {
    uint8_t dummy = 0x00;
    if (i2c_master_write_to_device(OLED_I2C_PORT, addr, &dummy, 1,
                                   pdMS_TO_TICKS(20)) == ESP_OK) {
      printf("OLED_SCAN found=0x%02x\n", addr);
      ++found;
    }
  }
  printf("OLED_SCAN done found=%d\n", found);
}

bool oled_init(void) {
  i2c_config_t conf = {};
  conf.mode = I2C_MODE_MASTER;
  conf.sda_io_num = OLED_SDA_GPIO;
  conf.scl_io_num = OLED_SCL_GPIO;
  conf.sda_pullup_en = GPIO_PULLUP_ENABLE;
  conf.scl_pullup_en = GPIO_PULLUP_ENABLE;
  conf.master.clk_speed = OLED_I2C_HZ;
  esp_err_t err = i2c_param_config(OLED_I2C_PORT, &conf);
  if (err == ESP_OK) {
    err = i2c_driver_install(OLED_I2C_PORT, I2C_MODE_MASTER, 0, 0, 0);
  }
  if (err != ESP_OK) {
    printf("OLED_FAILED stage=i2c err=%d\n", (int)err);
    return false;
  }
  oled_scan();
  s_lock = xSemaphoreCreateMutex();
  if (s_lock == NULL) {
    printf("OLED_FAILED stage=mutex\n");
    return false;
  }

  u8g2_Setup_sh1106_i2c_128x64_noname_f(&s_u8g2, U8G2_R0, byte_i2c,
                                        gpio_delay);
  u8g2_InitDisplay(&s_u8g2);
  u8g2_SetPowerSave(&s_u8g2, 0);
  u8g2_ClearBuffer(&s_u8g2);
  u8g2_SetFont(&s_u8g2, u8g2_font_6x10_tf);
  u8g2_SendBuffer(&s_u8g2);
  s_ready = true;
  printf("OLED_READY driver=sh1106 addr=0x%02x sda=%d scl=%d hz=%d\n",
         OLED_ADDR, OLED_SDA_GPIO, OLED_SCL_GPIO, OLED_I2C_HZ);
  return true;
}

bool oled_show_status(const char *text) {
  if (!s_ready || s_lock == NULL) return false;
  if (xSemaphoreTake(s_lock, pdMS_TO_TICKS(500)) != pdTRUE) return false;
  s_last_i2c = ESP_OK;
  u8g2_ClearBuffer(&s_u8g2);
  u8g2_SetFont(&s_u8g2, u8g2_font_6x10_tf);
  int width = (int)u8g2_GetStrWidth(&s_u8g2, text);
  int x = (128 - width) / 2;
  if (x < 0) x = 0;
  u8g2_DrawStr(&s_u8g2, x, 36, text);
  u8g2_SendBuffer(&s_u8g2);
  xSemaphoreGive(s_lock);
  if (s_last_i2c != ESP_OK) {
    printf("OLED_WRITE_FAILED err=%d len=%d b0=0x%02x b1=0x%02x text=%s\n",
           (int)s_last_i2c, s_fail_len, s_fail_b0, s_fail_b1, text);
    return false;
  }
  printf("OLED_SHOW text=%s\n", text);
  return true;
}
