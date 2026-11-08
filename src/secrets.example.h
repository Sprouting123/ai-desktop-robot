#pragma once

// Copy this file to src/secrets.h and fill in your own values.
// src/secrets.h is ignored by Git and must never be committed.
//
// The ESP32-S3 only supports 2.4 GHz Wi-Fi; 5 GHz-only SSIDs will not work.
// The access token is required in the X-Auth-Token header for every state
// changing POST request. Generate a fresh token with:
//
//   openssl rand -hex 16
//
// Do not reuse a Wi-Fi password as the token, and do not put either value in
// source files, logs, URLs, screenshots or chat messages.

#define WIFI_SSID "your-2.4ghz-ssid"
#define WIFI_PASSWORD "your-wifi-password"
#define API_TOKEN "replace-with-a-32-character-random-hex-token"
