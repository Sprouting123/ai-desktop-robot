#!/usr/bin/env python3
"""Local tests for reply storage and the authenticated reply download endpoint.

No hardware, TTS service or API key is used. A small ReplyStore fixture is
published under a temporary directory, the receiver is started with ASR, LLM
and TTS disabled, and GET /reply/latest is checked for auth, turn pinning,
headers, body integrity and the no-reply path.

Run with: .venv/bin/python scripts/test_reply_store.py
"""

import http.client
import io
import os
import pathlib
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import wave
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audio_receiver  # noqa: E402
import reply_store  # noqa: E402
import tts_client  # noqa: E402

RECEIVER = ROOT / "scripts" / "audio_receiver.py"
PCM = bytes((i * 37) & 0xFF for i in range(3200))  # 1600 mono s16 frames

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


def check_true(name, value):
    check(name, bool(value), True)


def make_wav(pcm):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return buffer.getvalue()


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_for_line(stream, needle, timeout=5.0):
    import select
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


def get(port, path, headers=None, timeout=10.0):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data
    finally:
        connection.close()


def tts_record(pcm=PCM):
    return {
        "provider": "fake",
        "model": "fake-model",
        "voice": "fake-voice",
        "characters": 4,
        "latency_ms": 1.0,
        "total_ms": 2.0,
        "cost_cny": 0.0,
        "request_id": "fake-request",
        "record_file": "work/tts/fake.json",
    }


def test_store():
    print("ReplyStore unit behaviour")
    with tempfile.TemporaryDirectory(prefix="reply-store-") as temp:
        store = reply_store.ReplyStore(temp)
        check("empty store", store.get(), None)
        record = store.publish("20261110-120000-01", PCM, "你好", tts_record(),
                               wav_bytes=make_wav(PCM))
        check("store id", record["id"], "20261110-120000-01")
        check("store bytes", record["pcm_bytes"], len(PCM))
        check("store frames", record["frames"], len(PCM) // 2)
        check("store crc", record["crc32"],
              f"{zlib.crc32(PCM) & 0xFFFFFFFF:08x}")
        check("store sample rate", record["sample_rate"], 16000)
        loaded = store.get()
        check("latest id", loaded["id"], record["id"])
        check_true("latest bytes", loaded["pcm_path"].read_bytes() == PCM)
        check("turn lookup", store.get("20261110-120000-01")["id"], record["id"])
        check("unknown turn", store.get("20261110-120000-99"), None)
        check("invalid id", store.get("../etc/passwd"), None)
        for bad, reason in ((b"", "empty_audio"),
                            (b"\x00\x00\x00", "odd_bytes"),
                            (b"\x00\x00" * (reply_store.MAX_PCM_BYTES // 2 + 1),
                             "too_long")):
            try:
                store.publish("20261110-120000-02", bad, "x", tts_record())
                got = None
            except reply_store.ReplyError as exc:
                got = exc.reason
            check(f"reject {reason}", got, reason)
        try:
            store.publish("../bad", PCM, "x", tts_record())
            got = None
        except reply_store.ReplyError as exc:
            got = exc.reason
        check("reject bad id publish", got, "bad_id")

        # Pruning keeps only the newest files and leaves the latest pointer.
        for index in range(reply_store.KEEP_REPLIES + 3):
            store.publish(f"20261110-1300{index:02d}", PCM, f"text{index}",
                          tts_record())
        pcm_files = sorted(pathlib.Path(temp).glob("reply-*.pcm"))
        check("prune keeps limit", len(pcm_files), reply_store.KEEP_REPLIES)
        check("latest after prune", store.get()["id"],
              f"20261110-1300{reply_store.KEEP_REPLIES + 2:02d}")


def test_tts_hook():
    print("AsrPipeline TTS hook")
    with tempfile.TemporaryDirectory(prefix="reply-hook-") as temp:
        temp = pathlib.Path(temp)
        store = reply_store.ReplyStore(temp / "replies")
        wav_path = temp / "tts.wav"
        wav_path.write_bytes(make_wav(PCM))

        class FakeChat:
            def __init__(self, status):
                self.status = status

            def ask(self, text, meta):
                if self.status != "success":
                    return {"status": "error", "reason": "fake_failure"}
                return {"status": "success", "reply_text": "你好呀",
                        "latency_ms": 1.0,
                        "usage": {"prompt_tokens": 1,
                                  "completion_tokens": 1,
                                  "total_tokens": 2},
                        "cost_usd": 0.0, "session_id": "fake",
                        "turn": 1}

        original = tts_client.synthesize

        def fake_synthesize(text, config):
            return tts_client.TTSResult(
                {"status": "success", "provider": "fake", "model": "m",
                 "voice": "v", "characters": len(text), "latency_ms": 1.0,
                 "total_ms": 2.0, "cost_cny": 0.0, "request_id": "r",
                 "pcm_bytes": len(PCM), "frames": len(PCM) // 2,
                 "duration_ms": 100.0, "sample_rate": 16000, "channels": 1,
                 "wav_path": str(wav_path),
                 "record_file": str(temp / "tts.json")},
                PCM)

        config = audio_receiver.AsrConfig(
            "python", "script", temp / "asr", 1, 1.0, 1.0, 0, 0.0, 0.0)
        try:
            tts_client.synthesize = fake_synthesize
            pipeline = audio_receiver.AsrPipeline(
                config, FakeChat("success"), tts_client.TTSConfig(
                    provider="edge", out_dir=temp / "tts"), store)
            pipeline._chat("mic.wav", "你好呀", wav_path,
                           "20261110-140000-01")
            stored = store.get("20261110-140000-01")
            check_true("tts hook stored", stored is not None)
            check("tts hook bytes", stored["pcm_bytes"], len(PCM))
            check("tts hook text", stored["text"], "你好呀")

            failed = audio_receiver.AsrPipeline(
                config, FakeChat("error"), tts_client.TTSConfig(
                    provider="edge", out_dir=temp / "tts"), store)
            failed._chat("mic2.wav", "你好呀", wav_path,
                         "20261110-140000-02")
            check("no reply after chat failure",
                  store.get("20261110-140000-02"), None)
        finally:
            tts_client.synthesize = original


def test_endpoint():
    print("GET /reply/latest endpoint")
    run_dir = ROOT / "work" / f"reply-test-{os.getpid()}"
    reply_dir = run_dir / "replies"
    reply_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    token_file = run_dir / "token"
    token_file.write_text(token + "\n")
    token_file.chmod(0o600)
    port = free_port()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    process = subprocess.Popen(
        [sys.executable, str(RECEIVER), "--host", "127.0.0.1",
         "--port", str(port), "--token-file", str(token_file),
         "--out-dir", str(run_dir / "audio"), "--no-asr", "--no-llm",
         "--no-tts", "--reply-dir", str(reply_dir)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        if wait_for_line(process.stdout, "listening") is None:
            print(process.stdout.read())
            raise SystemExit("receiver did not start")

        status, _, body = get(port, "/reply/latest")
        check("missing token -> 401", status, 401)
        status, _, _ = get(port, "/reply/latest",
                           {"X-Auth-Token": "wrong-token-0123456789"})
        check("invalid token -> 403", status, 403)
        status, _, _ = get(port, "/reply/latest", {"X-Auth-Token": token})
        check("no reply -> 404", status, 404)
        status, _, _ = get(port, "/reply/latest?turn=bad%2Fturn",
                           {"X-Auth-Token": token})
        check("bad turn -> 400", status, 400)

        store = reply_store.ReplyStore(reply_dir)
        created = store.publish("20261110-150000-01", PCM, "你好",
                                tts_record(), wav_bytes=make_wav(PCM))
        status, headers, body = get(port, "/reply/latest",
                                    {"X-Auth-Token": token})
        check("reply -> 200", status, 200)
        check_true("body bytes", body == PCM)
        check("content length", headers.get("Content-Length"),
              str(len(PCM)))
        check("reply id", headers.get("X-Reply-Id"), created["id"])
        check("format", headers.get("X-Audio-Format"), "s16le")
        check("rate", headers.get("X-Sample-Rate"), "16000")
        check("channels", headers.get("X-Channels"), "1")
        check("frames", headers.get("X-Frames"), str(len(PCM) // 2))
        check("crc", headers.get("X-Crc32"),
              f"{zlib.crc32(PCM) & 0xFFFFFFFF:08x}")
        check("content type", headers.get("Content-Type"),
              "application/octet-stream")
        check("token not in headers",
              any(token in str(value) for value in headers.values()), False)

        status, _, body = get(port, "/reply/latest?turn=20261110-150000-01",
                              {"X-Auth-Token": token})
        check("turn hit -> 200", status, 200)
        check_true("turn hit body", body == PCM)
        status, _, _ = get(port, "/reply/latest?turn=20261110-150000-99",
                           {"X-Auth-Token": token})
        check("turn miss -> 404", status, 404)

        second = b"\x01\x00\x02\x00"
        store.publish("20261110-150001-02", second, "第二句", tts_record())
        status, headers, body = get(port, "/reply/latest",
                                    {"X-Auth-Token": token})
        check("latest after second", headers.get("X-Reply-Id"),
              "20261110-150001-02")
        check_true("latest body after second", body == second)
        status, _, body = get(port, "/reply/latest?turn=20261110-150000-01",
                              {"X-Auth-Token": token})
        check("old turn status", status, 200)
        check_true("old turn body", body == PCM)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    test_store()
    test_tts_hook()
    test_endpoint()
    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
