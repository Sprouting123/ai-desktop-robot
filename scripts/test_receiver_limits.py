#!/usr/bin/env python3
"""Tests for the receiver's upload rate/daily limits; no hardware or secrets.

Starts throwaway receivers on 127.0.0.1 with --no-asr --no-llm, so no model
runs and no paid API is called. Checks that only valid, authenticated uploads
consume quota, that denials return 429, and that the daily counter survives a
restart (and fails closed when its state file is corrupt).

Run with: .venv/bin/python scripts/test_receiver_limits.py
"""

import http.client
import json
import os
import pathlib
import secrets
import select
import socket
import subprocess
import sys
import time
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECEIVER = ROOT / "scripts" / "audio_receiver.py"
FRAMES = 16000
PAYLOAD = bytes(range(256)) * (FRAMES * 2 // 256)
CRC = f"{zlib.crc32(PAYLOAD) & 0xFFFFFFFF:08x}"

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


def headers(token, **overrides):
    values = {
        "X-Auth-Token": token,
        "Content-Type": "application/octet-stream",
        "X-Audio-Format": "s16le",
        "X-Sample-Rate": "16000",
        "X-Channels": "1",
        "X-Frames": str(FRAMES),
        "X-Crc32": CRC,
        "Content-Length": str(len(PAYLOAD)),
        "Connection": "close",
    }
    values.update(overrides)
    return values


def request(port, token, body=PAYLOAD, **overrides):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15.0)
    try:
        connection.request("POST", "/upload", body=body,
                           headers=headers(token, **overrides))
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8", "replace")
    finally:
        connection.close()


def wait_for_line(stream, needle, timeout=10.0):
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


def start(run_dir, port, token_file, out_dir, extra, env):
    process = subprocess.Popen(
        [sys.executable, str(RECEIVER), "--host", "127.0.0.1",
         "--port", str(port), "--token-file", str(token_file),
         "--out-dir", str(out_dir), "--no-asr", "--no-llm", *extra],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    line = wait_for_line(process.stdout, "listening")
    if line is None:
        output = process.stdout.read()
        process.kill()
        raise SystemExit(f"receiver did not start: {output}")
    print(f"  log: {line.strip()}")
    return process


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    work = ROOT / "work"
    run_dir = work / f"receiver-limits-test-{os.getpid()}"
    out_dir = run_dir / "audio"
    token_file = run_dir / "token"
    usage_file = run_dir / "usage.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    token_file.write_text(token + "\n")
    token_file.chmod(0o600)
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("PYTHONPATH", None)

    print("[1] per-minute limit (2 valid uploads allowed)")
    port = free_port()
    process = start(run_dir, port, token_file, out_dir,
                    ["--rate-limit-per-minute", "2"], env)
    try:
        status, _ = request(port, "0" * 32)
        check("wrong token -> 403", status, 403)
        check("first upload -> 200", request(port, token)[0], 200)
        status, body = request(port, token)
        check("second upload -> 200", status, 200)
        status, body = request(port, token)
        check("third upload -> 429", status, 429)
        check("third upload reason", body, "ERR rate_limited")
        check("only two WAVs", len(wav_files(out_dir)), 2)
        status, _ = request(port, token, body=b"", **{
            "Content-Length": "16001", "X-Frames": "8000"})
        check("odd length still -> 400", status, 400)
    finally:
        stop(process)

    print("[2] X-Real-IP from a loopback proxy is used for limiting")
    out_dir_ip = run_dir / "audio-ip"
    port = free_port()
    process = start(run_dir, port, token_file, out_dir_ip,
                    ["--rate-limit-per-minute", "1"], env)
    try:
        status, _ = request(port, token, **{"X-Real-IP": "203.0.113.5"})
        check("client A first -> 200", status, 200)
        status, _ = request(port, token, **{"X-Real-IP": "203.0.113.5"})
        check("client A second -> 429", status, 429)
        status, _ = request(port, token, **{"X-Real-IP": "203.0.113.6"})
        check("client B first -> 200", status, 200)
        status, _ = request(port, token, **{"X-Real-IP": "not-an-ip"})
        check("invalid header counted as loopback -> 200", status, 200)
        status, _ = request(port, token, **{"X-Real-IP": "not-an-ip"})
        check("invalid header second -> 429", status, 429)
    finally:
        stop(process)

    print("[3] daily limit persists across restart")
    port = free_port()
    process = start(run_dir, port, token_file, out_dir,
                    ["--rate-limit-per-minute", "10",
                     "--daily-upload-limit", "2",
                     "--usage-file", str(usage_file)], env)
    try:
        status, _ = request(port, token, body=PAYLOAD[:15998], **{
            "Content-Length": "15998", "X-Frames": "7999", "X-Crc32": CRC})
        check("invalid length -> 400", status, 400)
        check("invalid length did not consume quota",
              json.loads(usage_file.read_text())["count"]
              if usage_file.exists() else 0, 0)
        check("upload 1 -> 200", request(port, token)[0], 200)
        check("upload 2 -> 200", request(port, token)[0], 200)
        status, body = request(port, token)
        check("upload 3 -> 429", status, 429)
        check("upload 3 reason", body, "ERR daily_limit")
        check("usage count", json.loads(usage_file.read_text())["count"], 2)
        check("total WAVs", len(wav_files(out_dir)), 4)
    finally:
        stop(process)

    port = free_port()
    process = start(run_dir, port, token_file, out_dir,
                    ["--daily-upload-limit", "2",
                     "--usage-file", str(usage_file)], env)
    try:
        status, body = request(port, token)
        check("restart keeps daily limit -> 429", status, 429)
        check("restart reason", body, "ERR daily_limit")
    finally:
        stop(process)

    print("[4] corrupt usage state fails closed")
    bad = run_dir / "bad.json"
    bad.write_text("{not json")
    port = free_port()
    result = subprocess.run(
        [sys.executable, str(RECEIVER), "--host", "127.0.0.1",
         "--port", str(port), "--token-file", str(token_file),
         "--out-dir", str(out_dir), "--no-asr", "--no-llm",
         "--daily-upload-limit", "5", "--usage-file", str(bad)],
        capture_output=True, text=True, timeout=15, env=env)
    check("corrupt state exits nonzero", result.returncode != 0, True)
    check("corrupt state message",
          "cannot start upload limits" in result.stderr, True)
    check("no token in error", token in result.stderr, False)

    print("[5] daily limit requires a state file")
    result = subprocess.run(
        [sys.executable, str(RECEIVER), "--host", "127.0.0.1",
         "--port", str(free_port()), "--token-file", str(token_file),
         "--out-dir", str(out_dir), "--no-asr", "--no-llm",
         "--daily-upload-limit", "5", "--usage-file", ""],
        capture_output=True, text=True, timeout=15, env=env)
    check("missing state file exits 2", result.returncode, 2)
    check("missing state file message",
          "requires --usage-file" in result.stderr, True)

    print()
    print(f"{'PASS' if failures == 0 else 'FAIL'}: {checks - failures}/"
          f"{checks} checks passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
