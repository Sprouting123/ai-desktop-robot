// 实验 016 第二阶段：Wi-Fi STA 与 HTTP 上传实现。
#include "net.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "nvs_flash.h"

#include "probe_secrets.h"
#include "recorder.h"

#define UPLOAD_PATH "/upload"
#define CONNECT_TIMEOUT_MS 1500
#define IO_TIMEOUT_S 5
#define RESPONSE_TIMEOUT_S 8  // 接收端写完 WAV 才回复，留足余量
#define UPLOAD_ATTEMPTS 3
#define WIFI_WAIT_MS 10000
#define RETRY_MAX_S 30

static volatile bool s_connected = false;
static volatile int s_backoff_s = 0;
static volatile int64_t s_next_retry_us = 0;

static int64_t now_us(void) { return esp_timer_get_time(); }

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id,
                               void *data) {
  (void)arg;
  if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
    printf("WIFI_STA_START\n");
    esp_wifi_connect();
  } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
    wifi_event_sta_disconnected_t *ev = (wifi_event_sta_disconnected_t *)data;
    s_connected = false;
    if (s_backoff_s == 0) {
      s_backoff_s = 2;
    } else if (s_backoff_s < RETRY_MAX_S) {
      s_backoff_s *= 2;
      if (s_backoff_s > RETRY_MAX_S) s_backoff_s = RETRY_MAX_S;
    }
    s_next_retry_us = now_us() + (int64_t)s_backoff_s * 1000000;
    printf("WIFI_LOST reason=%d retry_in_s=%d\n", (int)ev->reason, s_backoff_s);
  } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
    ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
    s_connected = true;
    s_backoff_s = 0;
    s_next_retry_us = 0;
    wifi_ap_record_t ap = {};
    int rssi = 0;
    int channel = 0;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
      rssi = ap.rssi;
      channel = ap.primary;
    }
    printf("WIFI_CONNECTED ip=" IPSTR " rssi=%d channel=%d\n",
           IP2STR(&ev->ip_info.ip), rssi, channel);
  }
}

// 只在断开且退避到期时重新发起连接；不在事件回调里阻塞。
static void reconnect_task(void *arg) {
  (void)arg;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(1000));
    if (s_connected) continue;
    if (s_next_retry_us == 0 || now_us() < s_next_retry_us) continue;
    s_next_retry_us = now_us() + (int64_t)RETRY_MAX_S * 1000000;
    printf("WIFI_RECONNECT\n");
    esp_wifi_connect();
  }
}

bool net_start(void) {
  if (strlen(WIFI_SSID) == 0) {
    printf("NET_DISABLED reason=empty_ssid\n");
    return false;
  }

  esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    nvs_flash_erase();
    err = nvs_flash_init();
  }
  if (err != ESP_OK) {
    printf("NET_FAILED reason=nvs err=%d\n", (int)err);
    return false;
  }

  err = esp_netif_init();
  if (err != ESP_OK) {
    printf("NET_FAILED reason=netif err=%d\n", (int)err);
    return false;
  }
  err = esp_event_loop_create_default();
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
    printf("NET_FAILED reason=event_loop err=%d\n", (int)err);
    return false;
  }
  if (esp_netif_create_default_wifi_sta() == NULL) {
    printf("NET_FAILED reason=sta_netif\n");
    return false;
  }

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  err = esp_wifi_init(&cfg);
  if (err != ESP_OK) {
    printf("NET_FAILED reason=wifi_init err=%d\n", (int)err);
    return false;
  }
  esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler,
                             NULL);
  esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler,
                             NULL);

  wifi_config_t wc = {};
  strncpy((char *)wc.sta.ssid, WIFI_SSID, sizeof(wc.sta.ssid) - 1);
  strncpy((char *)wc.sta.password, WIFI_PASSWORD, sizeof(wc.sta.password) - 1);
  wc.sta.threshold.authmode = WIFI_AUTH_OPEN;

  err = esp_wifi_set_mode(WIFI_MODE_STA);
  if (err == ESP_OK) err = esp_wifi_set_config(WIFI_IF_STA, &wc);
  if (err == ESP_OK) err = esp_wifi_set_ps(WIFI_PS_NONE);
  if (err == ESP_OK) err = esp_wifi_start();
  if (err != ESP_OK) {
    printf("NET_FAILED reason=wifi_start err=%d\n", (int)err);
    return false;
  }

  xTaskCreatePinnedToCore(reconnect_task, "wifi_reconnect", 3072, NULL, 2, NULL,
                          0);

  printf("NET_CONFIG host=%s port=%d path=%s token_configured=%d\n",
         AUDIO_UPLOAD_HOST, AUDIO_UPLOAD_PORT, UPLOAD_PATH,
         strlen(AUDIO_UPLOAD_TOKEN) > 0 ? 1 : 0);
  return true;
}

bool net_wifi_connected(void) { return s_connected; }

static bool wait_wifi(int timeout_ms) {
  int64_t deadline = now_us() + (int64_t)timeout_ms * 1000;
  while (!s_connected) {
    if (now_us() >= deadline) return false;
    vTaskDelay(pdMS_TO_TICKS(100));
  }
  return true;
}

static bool connect_with_timeout(int sock, const struct sockaddr *addr,
                                 socklen_t addr_len) {
  int flags = fcntl(sock, F_GETFL, 0);
  if (flags < 0) return false;
  fcntl(sock, F_SETFL, flags | O_NONBLOCK);
  int ret = connect(sock, addr, addr_len);
  if (ret < 0 && errno != EINPROGRESS) return false;
  if (ret < 0) {
    fd_set wfds;
    FD_ZERO(&wfds);
    FD_SET(sock, &wfds);
    struct timeval tv = {.tv_sec = CONNECT_TIMEOUT_MS / 1000,
                         .tv_usec = (CONNECT_TIMEOUT_MS % 1000) * 1000};
    int sel = select(sock + 1, NULL, &wfds, NULL, &tv);
    if (sel <= 0) return false;
    int so_error = 0;
    socklen_t len = sizeof(so_error);
    if (getsockopt(sock, SOL_SOCKET, SO_ERROR, &so_error, &len) != 0) return false;
    if (so_error != 0) return false;
  }
  fcntl(sock, F_SETFL, flags);
  return true;
}

static bool send_all(int sock, const uint8_t *data, size_t len) {
  size_t sent = 0;
  while (sent < len) {
    int n = send(sock, data + sent, len - sent, 0);
    if (n <= 0) {
      if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
        continue;
      }
      return false;
    }
    sent += (size_t)n;
  }
  return true;
}

static bool contains(const char *haystack, const char *needle) {
  return strstr(haystack, needle) != NULL;
}

static int do_upload_once(const uint8_t *data, size_t len, uint32_t crc,
                          net_upload_result_t *out) {
  struct addrinfo hints = {};
  hints.ai_family = AF_INET;
  hints.ai_socktype = SOCK_STREAM;
  char port_str[8];
  snprintf(port_str, sizeof(port_str), "%d", (int)AUDIO_UPLOAD_PORT);

  struct addrinfo *res = NULL;
  int gai = getaddrinfo(AUDIO_UPLOAD_HOST, port_str, &hints, &res);
  if (gai != 0 || res == NULL) {
    snprintf(out->reason, sizeof(out->reason), "dns_%d", gai);
    return -1;
  }

  int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (sock < 0) {
    freeaddrinfo(res);
    snprintf(out->reason, sizeof(out->reason), "socket_%d", errno);
    return -1;
  }
  struct timeval tv = {.tv_sec = IO_TIMEOUT_S, .tv_usec = 0};
  setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  struct timeval rtv = {.tv_sec = RESPONSE_TIMEOUT_S, .tv_usec = 0};
  setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &rtv, sizeof(rtv));

  if (!connect_with_timeout(sock, res->ai_addr, res->ai_addrlen)) {
    freeaddrinfo(res);
    close(sock);
    snprintf(out->reason, sizeof(out->reason), "connect");
    return -1;
  }
  freeaddrinfo(res);

  char header[640];
  int hlen = snprintf(header, sizeof(header),
                      "POST " UPLOAD_PATH " HTTP/1.1\r\n"
                      "Host: %s:%d\r\n"
                      "Connection: close\r\n"
                      "X-Auth-Token: %s\r\n"
                      "Content-Type: application/octet-stream\r\n"
                      "Content-Length: %u\r\n"
                      "X-Audio-Format: s16le\r\n"
                      "X-Sample-Rate: %d\r\n"
                      "X-Channels: %d\r\n"
                      "X-Frames: %u\r\n"
                      "X-Crc32: %08lx\r\n"
                      "\r\n",
                      AUDIO_UPLOAD_HOST, (int)AUDIO_UPLOAD_PORT,
                      AUDIO_UPLOAD_TOKEN, (unsigned)len, REC_SAMPLE_RATE,
                      REC_CHANNELS, (unsigned)(len / 2),
                      (unsigned long)crc);
  if (hlen <= 0 || hlen >= (int)sizeof(header)) {
    close(sock);
    snprintf(out->reason, sizeof(out->reason), "header_too_long");
    return -1;
  }

  if (!send_all(sock, (const uint8_t *)header, (size_t)hlen) ||
      !send_all(sock, data, len)) {
    close(sock);
    snprintf(out->reason, sizeof(out->reason), "send_%d", errno);
    return -1;
  }

  static char resp[1600];
  int total = 0;
  for (;;) {
    if (total >= (int)sizeof(resp) - 1) break;
    int n = recv(sock, resp + total, sizeof(resp) - 1 - (size_t)total, 0);
    if (n <= 0) break;
    total += n;
  }
  resp[total > 0 ? total : 0] = '\0';
  close(sock);

  if (total <= 0) {
    snprintf(out->reason, sizeof(out->reason), "no_response");
    return -1;
  }
  if (!contains(resp, " 200 ")) {
    snprintf(out->reason, sizeof(out->reason), "bad_status");
    return -1;
  }
  char want[64];
  snprintf(want, sizeof(want), "bytes=%u", (unsigned)len);
  if (!contains(resp, want)) {
    snprintf(out->reason, sizeof(out->reason), "bad_bytes");
    return -1;
  }
  snprintf(want, sizeof(want), "crc32=%08lx", (unsigned long)crc);
  if (!contains(resp, want)) {
    snprintf(out->reason, sizeof(out->reason), "bad_crc");
    return -1;
  }

  const char *turn = strstr(resp, "turn=");
  out->turn[0] = '\0';
  if (turn != NULL) {
    turn += 5;
    size_t i = 0;
    while (i < sizeof(out->turn) - 1 && turn[i] != '\0' && turn[i] != ' ' &&
           turn[i] != '\r' && turn[i] != '\n') {
      out->turn[i] = turn[i];
      ++i;
    }
    out->turn[i] = '\0';
  }
  if (out->turn[0] == '\0') {
    snprintf(out->reason, sizeof(out->reason), "no_turn");
    return -1;
  }
  return 0;
}

bool net_upload(const uint8_t *data, size_t len, uint32_t crc,
                net_upload_result_t *out) {
  memset(out, 0, sizeof(*out));
  if (!wait_wifi(WIFI_WAIT_MS)) {
    snprintf(out->reason, sizeof(out->reason), "wifi_not_connected");
    return false;
  }

  for (int attempt = 1; attempt <= UPLOAD_ATTEMPTS; ++attempt) {
    out->reason[0] = '\0';
    int ret = do_upload_once(data, len, crc, out);
    if (ret == 0) {
      printf("UPLOAD_DONE attempt=%d bytes=%u crc32=%08lx turn=%s\n", attempt,
             (unsigned)len, (unsigned long)crc, out->turn);
      out->ok = true;
      return true;
    }
    printf("UPLOAD_ATTEMPT_FAILED attempt=%d reason=%s\n", attempt, out->reason);
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
  printf("UPLOAD_FAILED bytes=%u crc32=%08lx reason=%s\n", (unsigned)len,
         (unsigned long)crc, out->reason);
  return false;
}

// ---------------------------------------------------------------------------
// 回答下载：GET /reply/latest?turn=<id>，原始 s16le PCM 作响应体。
// ---------------------------------------------------------------------------

#define REPLY_HEADER_MAX 2048
#define REPLY_MAX_BYTES (4u * 1024u * 1024u)

static int connect_host(void) {
  struct addrinfo hints = {};
  hints.ai_family = AF_INET;
  hints.ai_socktype = SOCK_STREAM;
  char port_str[8];
  snprintf(port_str, sizeof(port_str), "%d", (int)AUDIO_UPLOAD_PORT);

  struct addrinfo *res = NULL;
  if (getaddrinfo(AUDIO_UPLOAD_HOST, port_str, &hints, &res) != 0 ||
      res == NULL) {
    return -1;
  }
  int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (sock < 0) {
    freeaddrinfo(res);
    return -1;
  }
  if (!connect_with_timeout(sock, res->ai_addr, res->ai_addrlen)) {
    freeaddrinfo(res);
    close(sock);
    return -1;
  }
  freeaddrinfo(res);
  return sock;
}

static long header_long(const char *head, const char *name) {
  const char *p = strstr(head, name);
  if (p == NULL) return -1;
  p += strlen(name);
  while (*p == ' ' || *p == '\t') ++p;
  return strtol(p, NULL, 10);
}

static bool header_text(const char *head, const char *name, char *out,
                        size_t cap) {
  const char *p = strstr(head, name);
  out[0] = '\0';
  if (p == NULL) return false;
  p += strlen(name);
  while (*p == ' ' || *p == '\t') ++p;
  size_t i = 0;
  while (i + 1 < cap && p[i] != '\0' && p[i] != '\r' && p[i] != '\n') {
    out[i] = p[i];
    ++i;
  }
  out[i] = '\0';
  return i > 0;
}

static int do_fetch_once(const char *turn, uint8_t **out_buf, size_t *out_len,
                         uint32_t *out_crc, net_reply_result_t *res) {
  int sock = connect_host();
  if (sock < 0) {
    snprintf(res->reason, sizeof(res->reason), "connect");
    return -1;
  }
  struct timeval rtv = {.tv_sec = IO_TIMEOUT_S, .tv_usec = 0};
  setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &rtv, sizeof(rtv));

  char req[512];
  int rlen = snprintf(req, sizeof(req),
                      "GET /reply/latest?turn=%s HTTP/1.1\r\n"
                      "Host: %s:%d\r\n"
                      "Connection: close\r\n"
                      "X-Auth-Token: %s\r\n"
                      "\r\n",
                      turn, AUDIO_UPLOAD_HOST, (int)AUDIO_UPLOAD_PORT,
                      AUDIO_UPLOAD_TOKEN);
  if (rlen <= 0 || rlen >= (int)sizeof(req) ||
      !send_all(sock, (const uint8_t *)req, (size_t)rlen)) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "send");
    return -1;
  }

  static char raw[REPLY_HEADER_MAX + 1];
  static char head[REPLY_HEADER_MAX + 1];
  static uint8_t pre[REPLY_HEADER_MAX];
  int hlen = 0;
  int body_start = -1;
  for (;;) {
    if (hlen >= REPLY_HEADER_MAX) break;
    int n = recv(sock, raw + hlen, REPLY_HEADER_MAX - hlen, 0);
    if (n <= 0) break;
    hlen += n;
    raw[hlen] = '\0';
    char *sep = strstr(raw, "\r\n\r\n");
    if (sep != NULL) {
      body_start = (int)(sep - raw) + 4;
      break;
    }
  }
  if (body_start < 0) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "no_headers");
    return -1;
  }
  int pre_len = hlen - body_start;
  memcpy(pre, raw + body_start, (size_t)pre_len);
  memcpy(head, raw, (size_t)body_start);
  head[body_start] = '\0';

  if (contains(head, " 404 ")) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "not_ready");
    return 1;
  }
  if (!contains(head, " 200 ")) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "bad_status");
    return -1;
  }

  long content_len = header_long(head, "Content-Length:");
  long rate = header_long(head, "X-Sample-Rate:");
  long channels = header_long(head, "X-Channels:");
  long frames = header_long(head, "X-Frames:");
  char crc_text[16];
  bool has_crc = header_text(head, "X-Crc32:", crc_text, sizeof(crc_text));
  header_text(head, "X-Reply-Id:", res->reply_id, sizeof(res->reply_id));

  if (content_len <= 0 || (content_len & 1) != 0 ||
      (unsigned long)content_len > REPLY_MAX_BYTES) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "bad_length");
    return -1;
  }
  if (rate != REC_SAMPLE_RATE || channels != REC_CHANNELS ||
      frames != content_len / 2) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "bad_metadata");
    return -1;
  }
  if (!has_crc) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "no_crc");
    return -1;
  }

  uint8_t *body = (uint8_t *)heap_caps_malloc((size_t)content_len,
                                              MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (body == NULL) {
    body = (uint8_t *)heap_caps_malloc((size_t)content_len,
                                      MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  }
  if (body == NULL) {
    close(sock);
    snprintf(res->reason, sizeof(res->reason), "body_alloc");
    return -1;
  }

  size_t have = (size_t)content_len < (size_t)pre_len ? (size_t)content_len
                                                      : (size_t)pre_len;
  memcpy(body, pre, have);
  while (have < (size_t)content_len) {
    int n = recv(sock, body + have, (size_t)content_len - have, 0);
    if (n <= 0) break;
    have += (size_t)n;
  }
  close(sock);
  if (have != (size_t)content_len) {
    heap_caps_free(body);
    snprintf(res->reason, sizeof(res->reason), "short_body");
    return -1;
  }

  uint32_t crc = ~rec_crc32_update(0xFFFFFFFFu, body, (size_t)content_len);
  uint32_t want_crc = (uint32_t)strtoul(crc_text, NULL, 16);
  if (crc != want_crc) {
    heap_caps_free(body);
    snprintf(res->reason, sizeof(res->reason), "crc_mismatch");
    return -1;
  }

  *out_buf = body;
  *out_len = (size_t)content_len;
  *out_crc = crc;
  res->ok = true;
  return 0;
}

int net_fetch_reply(const char *turn, uint8_t **buf, size_t *len, uint32_t *crc,
                    net_reply_result_t *out) {
  memset(out, 0, sizeof(*out));
  *buf = NULL;
  *len = 0;
  *crc = 0;
  if (!wait_wifi(WIFI_WAIT_MS)) {
    snprintf(out->reason, sizeof(out->reason), "wifi_not_connected");
    return -1;
  }
  int ret = do_fetch_once(turn, buf, len, crc, out);
  if (ret == 0) {
    printf("REPLY_READY id=%s bytes=%u frames=%u duration_ms=%u crc32=%08lx\n",
           out->reply_id, (unsigned)*len, (unsigned)(*len / 2),
           (unsigned)(*len / 2 * 1000u / REC_SAMPLE_RATE),
           (unsigned long)*crc);
  }
  return ret;
}

