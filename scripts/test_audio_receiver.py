#!/usr/bin/env python3
"""Local tests for scripts/audio_receiver.py; no hardware or secrets needed.

Starts the receiver on 127.0.0.1 with a temporary token and output directory
under work/, then checks the happy path plus every rejection path. Rejected
requests must not leave a WAV or a temporary file behind.

Run with: .venv/bin/python scripts/test_audio_receiver.py
"""

import hashlib
import http.client
import os
import pathlib
import secrets
import select
import socket
import subprocess
import sys
import time
import wave
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECEIVER = ROOT / "scripts" / "audio_receiver.py"
FRAMES = 160000
BYTES = FRAMES * 2
PAYLOAD = bytes(range(256)) * (BYTES // 256)
PAYLOAD_CRC = f"{zlib.crc32(PAYLOAD) & 0xFFFFFFFF:08x}"

failures = 0
checks = 0


def check(name, actual, expected):
    global failures, checks
    checks += 1
    if actual == expected:
        print(f"  ok   {name}: {actual}")
    else:
        failures += 1
        print(f"  FAIL {name}: expected {expected!r}, got {actual!r}")


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def base_headers(token, payload=PAYLOAD, **overrides):
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/octet-stream",
        "X-Audio-Format": "s16le",
        "X-Sample-Rate": "16000",
        "X-Channels": "1",
        "X-Frames": str(FRAMES),
        "X-Crc32": f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}",
        "Content-Length": str(len(payload)),
        "Connection": "close",
    }
    for name, value in overrides.items():
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
    return headers


def request(port, method, path, headers, body=None, timeout=15.0):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8", "replace")
    finally:
        connection.close()


def truncated_request(port, raw_headers, partial_body):
    """Send fewer bytes than Content-Length, then half-close and read."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=15.0)
    try:
        request_bytes = b"POST /upload HTTP/1.1\r\n"
        for name, value in raw_headers.items():
            request_bytes += f"{name}: {value}\r\n".encode()
        request_bytes += b"\r\n" + partial_body
        sock.sendall(request_bytes)
        sock.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        status_line = data.split(b"\r\n", 1)[0].decode("ascii", "replace")
        return status_line
    finally:
        sock.close()


def wait_for_line(stream, needle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([stream], [], [], 0.2)
        if not ready:
            continue
        line = stream.readline()
        if not line:
            return None
        if needle in line:
            return line
    return None


def wav_files(out_dir):
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob("*.wav"))


def main():
    work = ROOT / "work"
    run_dir = work / f"receiver-test-{os.getpid()}"
    out_dir = run_dir / "audio"
    token_file = run_dir / "token"
    run_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    token_file.write_text(token + "\n")
    token_file.chmod(0o600)

    port = free_port()
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("PYTHONPATH", None)
    process = subprocess.Popen(
        [sys.executable, str(RECEIVER), "--host", "127.0.0.1",
         "--port", str(port), "--token-file", str(token_file),
         "--out-dir", str(out_dir), "--header-timeout", "0.5", "--no-asr",
         "--no-llm"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        ready = wait_for_line(process.stdout, "listening")
        if ready is None:
            print(process.stdout.read())
            raise SystemExit("receiver did not start")
        print(f"receiver on 127.0.0.1:{port}, out={out_dir}")

        print("silent connection")
        silent = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        time.sleep(0.8)  # longer than the receiver's 0.5 s header timeout
        silent.settimeout(2.0)
        try:
            closed = silent.recv(1)
        finally:
            silent.close()
        check("silent client closed by header timeout", closed, b"")
        check("no WAV after silent client", len(wav_files(out_dir)), 0)

        print("error paths (no WAV may be created)")
        status, _ = request(port, "POST", "/upload",
                            base_headers(token, **{"X-Auth-Token": None}),
                            PAYLOAD)
        check("missing token -> 401", status, 401)
        check("no WAV after missing token", len(wav_files(out_dir)), 0)

        status, _ = request(port, "POST", "/upload",
                            base_headers("0" * 32), PAYLOAD)
        check("wrong token -> 403", status, 403)
        check("no WAV after wrong token", len(wav_files(out_dir)), 0)

        status, _ = request(port, "POST", "/upload",
                            base_headers(token, **{
                                "Content-Length": str(BYTES - 1)}),
                            PAYLOAD[:-1])
        check("wrong length -> 400", status, 400)
        check("no WAV after wrong length", len(wav_files(out_dir)), 0)

        status, _ = request(port, "POST", "/upload",
                            base_headers(token, **{"X-Sample-Rate": "8000"}),
                            PAYLOAD)
        check("wrong sample rate -> 400", status, 400)
        check("no WAV after wrong format", len(wav_files(out_dir)), 0)

        status, _ = request(port, "POST", "/upload",
                            base_headers(token, **{"X-Crc32": "00000000"}),
                            PAYLOAD)
        check("wrong CRC -> 422", status, 422)
        check("no WAV after wrong CRC", len(wav_files(out_dir)), 0)

        broken = bytearray(PAYLOAD)
        broken[1234] ^= 0xFF
        status, _ = request(port, "POST", "/upload",
                            base_headers(token, **{
                                "X-Crc32": PAYLOAD_CRC}), bytes(broken))
        check("corrupted payload -> 422", status, 422)
        check("no WAV after corrupted payload", len(wav_files(out_dir)), 0)

        headers = base_headers(token)
        status_line = truncated_request(port, headers, PAYLOAD[:1000])
        check("short body -> 400", "400" in status_line, True)
        check("no WAV after short body", len(wav_files(out_dir)), 0)

        status, _ = request(port, "POST", "/other", base_headers(token),
                            PAYLOAD)
        check("wrong path -> 404", status, 404)
        status, _ = request(port, "GET", "/upload", {})
        check("GET /upload -> 405", status, 405)

        print("happy path")
        status, body = request(port, "POST", "/upload", base_headers(token),
                               PAYLOAD)
        check("valid upload -> 200", status, 200)
        check("response reports bytes", f"bytes={BYTES}" in body, True)
        check("response reports crc32", PAYLOAD_CRC in body, True)

        files = wav_files(out_dir)
        check("exactly one WAV", len(files), 1)
        if files:
            with wave.open(str(files[0]), "rb") as wav:
                check("WAV channels", wav.getnchannels(), 1)
                check("WAV sample width", wav.getsampwidth(), 2)
                check("WAV sample rate", wav.getframerate(), 16000)
                check("WAV frames", wav.getnframes(), FRAMES)
                saved = wav.readframes(FRAMES)
            check("WAV byte count", len(saved), BYTES)
            check("WAV payload identical", hashlib.sha256(saved).hexdigest(),
                  hashlib.sha256(PAYLOAD).hexdigest())
            check("WAV crc32",
                  f"{zlib.crc32(saved) & 0xFFFFFFFF:08x}", PAYLOAD_CRC)

        leftovers = sorted(out_dir.glob(".upload-*"))
        check("no temporary file left", len(leftovers), 0)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
