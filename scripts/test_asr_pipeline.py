#!/usr/bin/env python3
"""Local tests for the receiver's automatic ASR queue; no model is loaded.

A fake `--json` ASR script stands in for scripts/asr_local.py so these tests
cover queueing, silence skipping, failure recovery and shutdown draining
without the 2 GB Paraformer model. The real ASR path is exercised separately
with an existing WAV via `audio_receiver.py --process-wav`.

Run with: .venv/bin/python scripts/test_asr_pipeline.py
"""

import http.client
import json
import math
import os
import pathlib
import secrets
import socket
import struct
import subprocess
import sys
import time
import wave
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECEIVER = ROOT / "scripts" / "audio_receiver.py"
ASR_LOCAL = ROOT / "scripts" / "asr_local.py"
FRAMES = 160000
BYTES = FRAMES * 2

SPEECH = struct.pack(
    "<%dh" % FRAMES,
    *[int(1200 * math.sin(2 * math.pi * 440 * i / 16000))
      for i in range(FRAMES)])
SILENT = b"\x00" * BYTES

FAKE_ASR = '''#!/usr/bin/env python3
import json
import pathlib
import sys
import time

wav = pathlib.Path(sys.argv[-1])
here = pathlib.Path(__file__).resolve().parent
with (here / "invocations.log").open("a", encoding="utf-8") as log:
    log.write(wav.name + "\\n")
mode_path = here / "mode.txt"
mode = mode_path.read_text().strip() if mode_path.exists() else "success"
if mode == "block":
    (here / "busy").write_text(wav.name, encoding="utf-8")
    release = here / "release"
    deadline = time.time() + 30
    while not release.exists() and time.time() < deadline:
        time.sleep(0.05)
    if not release.exists():
        print(json.dumps({"status": "error", "reason": "block_timeout",
                          "error": "release file never appeared"}))
        sys.exit(1)
if mode == "error":
    print(json.dumps({"status": "error", "reason": "fake_error",
                      "error": "deliberate failure", "text": ""}))
    sys.exit(1)
print(json.dumps({
    "status": "success",
    "wav": str(wav),
    "text": "测试文本",
    "duration_s": 10.0,
    "model_load_ms": 45.6,
    "inference_ms": 12.3,
    "rtf": 0.0012,
    "peak_rss_mb": 123.4,
}, ensure_ascii=False))
'''

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


def headers(token, payload):
    return {
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


def upload(port, token, payload):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20.0)
    try:
        connection.request("POST", "/upload", body=payload,
                           headers=headers(token, payload))
        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace")
        return response.status, body
    finally:
        connection.close()


def file_from_body(body):
    for part in body.split():
        if part.startswith("file="):
            return part[5:]
    return None


def wait_for_line(stream, needle, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = stream.readline()
        if not line:
            return None
        if needle in line:
            return line
    return None


def wait_result(asr_dir, wav_name, timeout=15.0):
    path = asr_dir / f"{pathlib.Path(wav_name).stem}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.05)
    return None


def wait_file(path, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


class Scenario:
    def __init__(self, name):
        self.dir = ROOT / "work" / f"asr-test-{os.getpid()}-{name}"
        self.out_dir = self.dir / "audio"
        self.asr_dir = self.dir / "asr"
        self.token_file = self.dir / "token"
        self.fake_dir = self.dir / "fake"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fake_dir.mkdir(parents=True, exist_ok=True)
        self.fake = self.fake_dir / "fake_asr.py"
        self.fake.write_text(FAKE_ASR, encoding="utf-8")
        self.mode_file = self.fake_dir / "mode.txt"
        self.mode_file.write_text("success", encoding="utf-8")
        self.token = secrets.token_hex(16)
        self.token_file.write_text(self.token + "\n", encoding="utf-8")
        self.token_file.chmod(0o600)
        self.port = free_port()
        self.process = None

    def start(self, *extra):
        command = [
            sys.executable, str(RECEIVER),
            "--host", "127.0.0.1", "--port", str(self.port),
            "--token-file", str(self.token_file),
            "--out-dir", str(self.out_dir),
            "--asr-dir", str(self.asr_dir),
            "--asr-python", sys.executable,
            "--asr-script", str(self.fake),
            "--header-timeout", "0.5",
        ]
        command.extend(extra)
        self.process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True)
        ready = wait_for_line(self.process.stdout, "listening")
        if ready is None:
            raise SystemExit(f"receiver failed to start: {self.dir}")
        return ready

    def stop(self):
        if self.process is None:
            return None
        self.process.terminate()
        try:
            output = self.process.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            self.process.kill()
            output = self.process.communicate()[0]
        return output


def test_receive_and_skip():
    print("receive, silence skip, success")
    scenario = Scenario("basic")
    scenario.start()
    try:
        print("  silent upload")
        status, body = upload(scenario.port, scenario.token, SILENT)
        name = file_from_body(body)
        check("silent upload -> 200", status, 200)
        result = wait_result(scenario.asr_dir, name)
        check("silent result written", result is not None, True)
        check("silent status", result.get("status") if result else None,
              "skipped")
        check("silent reason", result.get("reason") if result else None,
              "silent")
        check("fake ASR not invoked for silence",
              len(list(scenario.fake_dir.glob("invocations.log"))), 0)

        print("  speech upload")
        status, body = upload(scenario.port, scenario.token, SPEECH)
        name = file_from_body(body)
        check("speech upload -> 200", status, 200)
        result = wait_result(scenario.asr_dir, name)
        check("speech result written", result is not None, True)
        check("speech status", result.get("status") if result else None,
              "success")
        check("speech text", result.get("text") if result else None, "测试文本")
        check("inference_ms", result.get("inference_ms") if result else None,
              12.3)
        check("wav crc32 in result",
              result.get("wav_crc32") if result else None,
              f"{zlib.crc32(SPEECH) & 0xFFFFFFFF:08x}")
        wav_path = scenario.out_dir / name
        with wave.open(str(wav_path), "rb") as wav:
            saved = wav.readframes(wav.getnframes())
        check("WAV contents unchanged", saved == SPEECH, True)
        invocations = (scenario.fake_dir / "invocations.log").read_text(
            encoding="utf-8").splitlines()
        check("fake ASR invoked once for speech", invocations, [name])
    finally:
        scenario.stop()


def test_failure_recovery():
    print("ASR failure then recovery")
    scenario = Scenario("recover")
    scenario.mode_file.write_text("error", encoding="utf-8")
    scenario.start()
    try:
        status, body = upload(scenario.port, scenario.token, SPEECH)
        name = file_from_body(body)
        check("failing upload still 200", status, 200)
        result = wait_result(scenario.asr_dir, name)
        check("failure recorded", result.get("status") if result else None,
              "error")
        check("failure reason", result.get("reason") if result else None,
              "fake_error")

        scenario.mode_file.write_text("success", encoding="utf-8")
        status, body = upload(scenario.port, scenario.token, SPEECH)
        name = file_from_body(body)
        check("next upload -> 200", status, 200)
        result = wait_result(scenario.asr_dir, name)
        check("server recovered after ASR failure",
              result.get("status") if result else None, "success")
    finally:
        output = scenario.stop()
        check("server exited without crash", "Traceback" in (output or ""),
              False)


def test_bounded_queue():
    print("bounded queue and drain")
    scenario = Scenario("queue")
    scenario.mode_file.write_text("block", encoding="utf-8")
    scenario.start("--asr-queue", "1")
    try:
        status, body = upload(scenario.port, scenario.token, SPEECH)
        first = file_from_body(body)
        check("first upload -> 200", status, 200)
        check("worker became busy", wait_file(scenario.fake_dir / "busy"), True)

        status, body = upload(scenario.port, scenario.token, SPEECH)
        second = file_from_body(body)
        check("second upload -> 200 (queued)", status, 200)

        status, body = upload(scenario.port, scenario.token, SPEECH)
        third = file_from_body(body)
        check("third upload -> 200 (queue full)", status, 200)
        result = wait_result(scenario.asr_dir, third)
        check("queue full result written", result is not None, True)
        check("queue full status", result.get("status") if result else None,
              "skipped")
        check("queue full reason", result.get("reason") if result else None,
              "queue_full")

        (scenario.fake_dir / "release").write_text("go", encoding="utf-8")
        first_result = wait_result(scenario.asr_dir, first, timeout=20.0)
        second_result = wait_result(scenario.asr_dir, second, timeout=20.0)
        check("first drained", first_result.get("status")
              if first_result else None, "success")
        check("second drained", second_result.get("status")
              if second_result else None, "success")
    finally:
        output = scenario.stop()
        check("queue test had no traceback", "Traceback" in (output or ""),
              False)


def test_once_shutdown():
    print("--once waits for ASR result")
    scenario = Scenario("once")
    scenario.start("--once")
    status, body = upload(scenario.port, scenario.token, SPEECH)
    name = file_from_body(body)
    check("--once upload -> 200", status, 200)
    try:
        code = scenario.process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        scenario.process.kill()
        code = None
    check("--once exits", code, 0)
    result = wait_result(scenario.asr_dir, name)
    check("result written before exit", result is not None, True)
    check("--once result success",
          result.get("status") if result else None, "success")
    scenario.stop()


def test_json_error_and_offline():
    print("asr_local --json error and offline pipeline")
    result = subprocess.run(
        [sys.executable, str(ASR_LOCAL), "--json", "work/missing.wav"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=20)
    check("missing WAV exit", result.returncode, 1)
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    check("missing WAV JSON status", payload.get("status"), "error")
    check("missing WAV JSON has error", bool(payload.get("error")), True)

    scenario = Scenario("offline")
    wav_path = scenario.out_dir / "offline.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(SPEECH)
    result = subprocess.run(
        [sys.executable, str(RECEIVER),
         "--token-file", str(scenario.token_file),
         "--out-dir", str(scenario.out_dir),
         "--asr-dir", str(scenario.asr_dir),
         "--asr-python", sys.executable,
         "--asr-script", str(scenario.fake),
         "--process-wav", str(wav_path)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    check("offline pipeline exit", result.returncode, 0)
    saved = wait_result(scenario.asr_dir, wav_path.name)
    check("offline result status", saved.get("status") if saved else None,
          "success")
    check("offline result text", saved.get("text") if saved else None, "测试文本")


def main():
    test_receive_and_skip()
    test_failure_recovery()
    test_bounded_queue()
    test_once_shutdown()
    test_json_error_and_offline()
    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
