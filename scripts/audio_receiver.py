#!/usr/bin/env python3
"""Receive one ESP32 PCM upload over the trusted LAN and save it as a WAV.

The ESP32 runs experiment 013 and sends a binary POST only after an explicit
`mic upload` command. This server validates the token, length, format headers
and CRC-32 before writing anything, so a rejected request never leaves a WAV.

Run after generating the shared token (the file is ignored by Git):

    openssl rand -hex 16 > work/audio_upload_token
    chmod 600 work/audio_upload_token
    .venv/bin/python scripts/audio_receiver.py

The token must also be set as AUDIO_UPLOAD_TOKEN in the ignored src/secrets.h.
Use this only on a trusted home LAN; never forward the port from the internet.
"""

import argparse
import hmac
import os
import pathlib
import re
import socket
import sys
import threading
import time
import wave
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES = 160000
EXPECTED_BYTES = FRAMES * 2
DEFAULT_TOKEN_FILE = "work/audio_upload_token"
DEFAULT_OUT_DIR = "work/audio"
CRC_RE = re.compile(r"[0-9a-fA-F]{8}")
FORMAT_HEADERS = {
    "Content-Type": "application/octet-stream",
    "X-Audio-Format": "s16le",
    "X-Sample-Rate": str(SAMPLE_RATE),
    "X-Channels": str(CHANNELS),
    "X-Frames": str(FRAMES),
}


def load_token(path):
    try:
        token = pathlib.Path(path).read_text().strip()
    except OSError as error:
        raise SystemExit(f"cannot read token file {path}: {error}")
    if not 16 <= len(token) <= 64 or any(
        ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token
    ):
        raise SystemExit(
            f"token file {path} must contain 16-64 printable ASCII characters"
        )
    return token


class Receiver(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, token, out_dir, max_uploads, header_timeout):
        super().__init__(address, Handler)
        self.token = token
        self.out_dir = pathlib.Path(out_dir)
        self.max_uploads = max_uploads
        self.header_timeout = header_timeout
        self.uploads = 0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DeskRobotAudio/1.0"

    def setup(self):
        super().setup()
        # Bound header parsing too: a client that connects and never sends a
        # request must not wedge this single-threaded receiver.
        self.connection.settimeout(self.server.header_timeout)

    # Never use the default logger: it writes a line for every request and is
    # not needed here. Our own messages never include the token.
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        return

    def _log(self, text):
        print(f"[receiver] {text}", flush=True)

    def _reply(self, code, text):
        body = text.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, "OK")
        elif self.path == "/upload":
            self._reply(405, "ERR method_not_allowed")
        else:
            self._reply(404, "ERR not_found")

    def do_POST(self):
        if self.path != "/upload":
            self._reply(404, "ERR not_found")
            return

        token = self.headers.get("X-Auth-Token", "")
        if not token:
            self._log("reject missing_token")
            self._reply(401, "ERR missing_token")
            return
        if not hmac.compare_digest(token, self.server.token):
            self._log(f"reject invalid_token remote={self.client_address[0]}")
            self._reply(403, "ERR invalid_token")
            return

        length_text = self.headers.get("Content-Length")
        try:
            length = int(length_text)
        except (TypeError, ValueError):
            self._log("reject bad_length")
            self._reply(400, "ERR bad_length")
            return
        if length != EXPECTED_BYTES:
            self._log(f"reject length={length} expected={EXPECTED_BYTES}")
            self._reply(413 if length > EXPECTED_BYTES else 400,
                        "ERR bad_length")
            return

        for name, expected in FORMAT_HEADERS.items():
            actual = (self.headers.get(name) or "").strip()
            if actual.lower() != expected.lower():
                self._log(f"reject header={name} value={actual!r}")
                self._reply(400, "ERR bad_format")
                return

        crc_text = (self.headers.get("X-Crc32") or "").strip()
        if not CRC_RE.fullmatch(crc_text):
            self._log("reject bad_crc_header")
            self._reply(400, "ERR bad_crc")
            return

        # Bound the body read so a stalled sender cannot hold the server open.
        self.connection.settimeout(10.0)
        try:
            data = self.rfile.read(length)
        except (socket.timeout, OSError) as error:
            self._log(f"reject body_read remote={self.client_address[0]} "
                      f"error={type(error).__name__}")
            self._reply(408, "ERR body_read")
            return
        if len(data) != length:
            self._log(f"reject short_body got={len(data)} expected={length}")
            self._reply(400, "ERR short_body")
            return

        crc = zlib.crc32(data) & 0xFFFFFFFF
        if f"{crc:08x}" != crc_text.lower():
            self._log(f"reject crc got={crc:08x} header={crc_text.lower()}")
            self._reply(422, "ERR bad_crc")
            return

        name = self._write_wav(data)
        if name is None:
            self._reply(500, "ERR write_failed")
            return

        self.server.uploads += 1
        self._log(f"ok remote={self.client_address[0]} bytes={length} "
                  f"crc32={crc:08x} file={name} count={self.server.uploads}")
        self._reply(200, f"OK bytes={length} frames={FRAMES} crc32={crc:08x} "
                         f"file={name}")
        if (self.server.max_uploads
                and self.server.uploads >= self.server.max_uploads):
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _write_wav(self, data):
        out_dir = self.server.out_dir
        temp = None
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = out_dir / f"mic-{stamp}.wav"
            index = 1
            while path.exists():
                path = out_dir / f"mic-{stamp}-{index}.wav"
                index += 1
            temp = out_dir / f".upload-{os.getpid()}.tmp"
            with wave.open(str(temp), "wb") as wav:
                wav.setnchannels(CHANNELS)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(data)
            os.replace(temp, path)
            return path.name
        except OSError as error:
            print(f"[receiver] write failed: {error}", flush=True)
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
            return None


def main():
    parser = argparse.ArgumentParser(
        description="Receive a 10 s PCM upload and write a WAV")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default: 0.0.0.0, trusted LAN only)")
    parser.add_argument("--port", type=int, default=8080,
                        help="TCP port (default: 8080; the ESP32 web UI keeps 80)")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE,
                        help=f"shared token file (default: {DEFAULT_TOKEN_FILE})")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                        help=f"WAV output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--header-timeout", type=float, default=10.0,
                        help="seconds to wait for request headers (default: 10)")
    parser.add_argument("--max-uploads", type=int, default=0,
                        help="exit after N accepted uploads (0 = unlimited)")
    parser.add_argument("--once", action="store_true",
                        help="same as --max-uploads 1")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if args.header_timeout <= 0:
        raise SystemExit("header timeout must be positive")
    max_uploads = 1 if args.once else args.max_uploads
    token = load_token(args.token_file)

    server = Receiver((args.host, args.port), token, args.out_dir, max_uploads,
                      args.header_timeout)
    print(f"[receiver] listening host={args.host} port={args.port} "
          f"out={args.out_dir} max_uploads={max_uploads or 'unlimited'}; "
          f"trusted LAN only", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("[receiver] interrupted", flush=True)
    finally:
        server.server_close()
        print(f"[receiver] stopped uploads={server.uploads}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
