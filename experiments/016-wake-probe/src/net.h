// 实验 016 第二阶段：探针内 Wi-Fi STA 与 HTTP 上传。
// 协议与实验 013 主固件一致：POST /upload，原始 s16le PCM 直接作请求体。
// 令牌只从被 Git 忽略的 probe_secrets.h 读取，任何日志都不打印它。
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
  bool ok;
  char turn[40];
  char reason[64];
} net_upload_result_t;

// 初始化 NVS / netif / Wi-Fi STA 并开始连接，非阻塞。
bool net_start(void);
bool net_wifi_connected(void);

// 阻塞上传：内部最多尝试 3 次，每次从偏移 0 重发。
bool net_upload(const uint8_t *data, size_t len, uint32_t crc,
                net_upload_result_t *out);

typedef struct {
  bool ok;
  char reply_id[48];
  char reason[64];
} net_reply_result_t;

// 返回值：0=已下载（*buf 由调用者 heap_caps_free），1=回答尚未生成（404，稍后再试），
// -1=失败。成功时 *len 为 PCM 字节数，*crc 为服务端校验值。
int net_fetch_reply(const char *turn, uint8_t **buf, size_t *len, uint32_t *crc,
                    net_reply_result_t *out);
