#!/usr/bin/env python3
"""Local tests for scripts/tts_client.py; no real TTS service is contacted.

A fake DashScope/SSE server and a fake edge-tts command exercise request shape,
PCM output, streaming chunks, URL fallback, HTTP/timeout errors, cost estimates,
key isolation and result files. ffmpeg and aplay are never asked to reach the
network. Run with: .venv/bin/python scripts/test_tts_client.py
"""

import base64
import http.server
import json
import os
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import tts_client  # noqa: E402

FAKE_KEY = "sk-tts-0123456789abcdef0123456789abcdef"
os.environ["DASHSCOPE_API_KEY"] = FAKE_KEY  # tests never reach a real host
SENTENCE = "你好，我是小桌。"
PCM = b"\x01\x00\xff\x7f\x00\x80" * 800  # 2400 samples, valid s16 mono

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


class FakeDashScope:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.delay = 0.0
        self.mode = "sse"
        self.pcm = PCM
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    body = None
                fake.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "json": body,
                })
                if fake.delay:
                    time.sleep(fake.delay)
                if fake.status != 200:
                    payload = json.dumps({
                        "code": "InvalidApiKey",
                        "message": "bad key " + FAKE_KEY,
                    }).encode("utf-8")
                    self.send_response(fake.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self._stream(fake)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _stream(self, fake):
                if fake.mode == "url":
                    event = {
                        "request_id": "req-url",
                        "usage": {"characters": 7},
                        "output": {"audio": {
                            "url": f"http://127.0.0.1:{fake.port}/audio.pcm",
                        }},
                    }
                    self.wfile.write(
                        ("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
                    return
                half = len(fake.pcm) // 2
                first = {
                    "request_id": "req-sse",
                    "usage": {"characters": 7},
                    "output": {"audio": {
                        "data": base64.b64encode(
                            fake.pcm[:half]).decode("ascii"),
                    }},
                }
                second = {
                    "request_id": "req-sse",
                    "output": {"audio": {
                        "data": base64.b64encode(
                            fake.pcm[half:]).decode("ascii"),
                    }, "finish_reason": "stop"},
                    "usage": {"characters": 7},
                }
                if fake.mode == "badbase64":
                    second["output"]["audio"]["data"] = "not base64!"
                for event in (first, second):
                    self.wfile.write(
                        ("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def do_GET(self):
                if self.path == "/audio.pcm":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(fake.pcm)))
                    self.end_headers()
                    self.wfile.write(fake.pcm)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                return

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/api/v1/services/audio/tts/SpeechSynthesizer"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def make_config(api=None, **overrides):
    options = {
        "provider": "cosyvoice",
        "base_url": api.base_url if api else tts_client.DEFAULT_COSY_BASE_URL,
        "connect_timeout": 2.0,
        "read_timeout": 5.0,
        "out_dir": tempfile.mkdtemp(prefix="tts-test-"),
    }
    options.update(overrides)
    return tts_client.TTSConfig(**options)


def test_sse_success():
    print("CosyVoice SSE request and PCM output")
    api = FakeDashScope()
    try:
        config = make_config(api)
        result = tts_client.synthesize(SENTENCE, config)
        record = result.record
        check("status", record["status"], "success")
        check("pcm bytes", record["pcm_bytes"], len(PCM))
        check("frames", record["frames"], len(PCM) // 2)
        check("sample rate", record["sample_rate"], 16000)
        check("channels", record["channels"], 1)
        check("characters", record["characters"], 7)
        check("request id", record["request_id"], "req-sse")
        check("model", record["model"], tts_client.DEFAULT_COSY_MODEL)
        check("voice", record["voice"], tts_client.DEFAULT_COSY_VOICE)
        check("cost", record["cost_cny"], 0.0007)
        check_true("latency", record["latency_ms"] >= 0)
        check("request count", len(api.requests), 1)
        request = api.requests[0]
        check("auth", request["headers"].get("Authorization"),
              f"Bearer {FAKE_KEY}")
        check("sse header", request["headers"].get("X-DashScope-SSE"),
              "enable")
        body = request["json"]
        check("body model", body["model"], tts_client.DEFAULT_COSY_MODEL)
        check("body text", body["input"]["text"], SENTENCE)
        check("body format", body["input"]["format"], "pcm")
        check("body sample rate", body["input"]["sample_rate"], 16000)
        check("body voice", body["input"]["voice"], tts_client.DEFAULT_COSY_VOICE)
        check_true("saved pcm equals", pathlib.Path(
            record["pcm_path"]).read_bytes() == PCM)
        with wave.open(record["wav_path"], "rb") as wav:
            check("wav channels", wav.getnchannels(), 1)
            check("wav rate", wav.getframerate(), 16000)
            check("wav width", wav.getsampwidth(), 2)
            check("wav frames", wav.getnframes(), len(PCM) // 2)
        saved = json.loads(pathlib.Path(record["record_file"]).read_text(
            encoding="utf-8"))
        check("record file hides key", FAKE_KEY in json.dumps(saved), False)
        check("record file status", saved["status"], "success")
    finally:
        api.close()


def test_url_fallback():
    print("CosyVoice URL fallback")
    api = FakeDashScope()
    try:
        api.mode = "url"
        result = tts_client.synthesize(SENTENCE, make_config(api))
        check("url mode pcm", result.record["pcm_bytes"], len(PCM))
        check("url request id", result.record["request_id"], "req-url")
    finally:
        api.close()


def test_http_errors():
    print("CosyVoice HTTP errors")
    api = FakeDashScope()
    try:
        for status, reason in ((401, "http_401"), (403, "http_403"),
                               (429, "http_429"), (500, "http_5xx")):
            api.status = status
            try:
                tts_client.synthesize(SENTENCE, make_config(api))
                got = None
            except tts_client.TTSError as exc:
                got = exc.reason
                check(f"{status} key redacted", FAKE_KEY in exc.message, False)
            check(f"{status} reason", got, reason)
    finally:
        api.close()

    api = FakeDashScope()
    try:
        api.mode = "badbase64"
        try:
            tts_client.synthesize(SENTENCE, make_config(api))
            got = None
        except tts_client.TTSError as exc:
            got = exc.reason
        check("bad base64", got, "bad_response")
    finally:
        api.close()

    api = FakeDashScope()
    try:
        api.delay = 1.0
        try:
            tts_client.synthesize(
                SENTENCE, make_config(api, read_timeout=0.3))
            got = None
        except tts_client.TTSError as exc:
            got = exc.reason
        check("timeout", got, "timeout")
    finally:
        api.close()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    try:
        tts_client.synthesize(
            SENTENCE, make_config(base_url=f"http://127.0.0.1:{port}/tts",
                                  connect_timeout=0.5))
        got = None
    except tts_client.TTSError as exc:
        got = exc.reason
    check("connection refused", got, "network_error")


def test_key_loading():
    print("TTS key loading")
    saved = os.environ.pop("DASHSCOPE_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as temp:
            temp = pathlib.Path(temp)
            missing = temp / "missing"
            try:
                tts_client.load_api_key(missing)
                reason = None
            except tts_client.TTSError as exc:
                reason = exc.reason
            check("missing key", reason, "missing_api_key")

            short = temp / "short"
            short.write_text("short\n", encoding="utf-8")
            try:
                tts_client.load_api_key(short)
                reason = None
            except tts_client.TTSError as exc:
                reason = exc.reason
            check("short key", reason, "invalid_api_key")

            good = temp / "good"
            good.write_text(FAKE_KEY + "\n", encoding="utf-8")
            good.chmod(0o644)
            info = tts_client.load_api_key(good)
            check("loaded", info.key == FAKE_KEY, True)
            check("repr hides key", FAKE_KEY in repr(info), False)
            check("loose permissions", info.loose_permissions, True)
            os.environ["DASHSCOPE_API_KEY"] = FAKE_KEY
            info = tts_client.load_api_key(good)
            check("env wins", info.source, "env:DASHSCOPE_API_KEY")
    finally:
        os.environ.pop("DASHSCOPE_API_KEY", None)
        if saved is not None:
            os.environ["DASHSCOPE_API_KEY"] = saved


def test_text_and_cost():
    print("text validation and cost")
    check("empty", tts_client.valid_tts_text(""), False)
    check("spaces", tts_client.valid_tts_text("   "), False)
    check("punctuation", tts_client.valid_tts_text("。。。"), False)
    check("normal", tts_client.valid_tts_text("你好"), True)
    check("too long", tts_client.valid_tts_text("字" * 301), False)
    check("cost v3-flash", tts_client.estimate_cost_cny(
        "cosyvoice-v3-flash", 10000), 1.0)
    check("cost v3.5-flash", tts_client.estimate_cost_cny(
        "cosyvoice-v3.5-flash", 10000), 0.8)
    check("unknown cost", tts_client.estimate_cost_cny("nope", 100), None)
    check("none characters", tts_client.estimate_cost_cny(
        "cosyvoice-v3-flash", None), None)


def make_fake_edge(path, pcm, fail=False):
    """Executable fake that ignores -m edge_tts and writes a WAV file."""
    script = pathlib.Path(path)
    payload = base64.b64encode(pcm).decode("ascii")
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import base64, sys, wave\n"
        f"FAIL = {fail!r}\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('--write-media') + 1]\n"
        "if FAIL: print('synthetic edge failure', file=sys.stderr); "
        "sys.exit(3)\n"
        "data = base64.b64decode('" + payload + "')\n"
        "with wave.open(out, 'wb') as w:\n"
        "    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)\n"
        "    w.writeframes(data)\n",
        encoding="utf-8")
    script.chmod(0o755)
    return script


def test_edge_provider():
    print("Edge provider with a fake command and real ffmpeg")
    with tempfile.TemporaryDirectory() as temp:
        temp = pathlib.Path(temp)
        fake = make_fake_edge(temp / "fake_edge", PCM)
        config = tts_client.TTSConfig(
            provider="edge", edge_python=str(fake), out_dir=temp / "out")
        result = tts_client.synthesize(SENTENCE, config)
        check("edge status", result.record["status"], "success")
        check("edge provider", result.record["provider"], "edge")
        check("edge cost", result.record["cost_cny"], 0.0)
        check_true("edge frames", result.record["frames"] > 0)
        check("edge sample rate", result.record["sample_rate"], 16000)
        check_true("edge wav exists",
                   pathlib.Path(result.record["wav_path"]).is_file())

        broken = make_fake_edge(temp / "broken_edge", PCM, fail=True)
        config = tts_client.TTSConfig(
            provider="edge", edge_python=str(broken),
            out_dir=temp / "out2")
        try:
            tts_client.synthesize(SENTENCE, config)
            got = None
        except tts_client.TTSError as exc:
            got = exc.reason
        check("edge failure", got, "edge_error")

        config = tts_client.TTSConfig(
            provider="edge", edge_python=str(temp / "no-such-edge"),
            out_dir=temp / "out3")
        try:
            tts_client.synthesize(SENTENCE, config)
            got = None
        except tts_client.TTSError as exc:
            got = exc.reason
        check("edge unavailable", got, "edge_unavailable")


def test_cli_without_key():
    print("CLI without a DashScope key")
    env = os.environ.copy()
    env.pop("DASHSCOPE_API_KEY", None)
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory() as temp:
        missing = pathlib.Path(temp) / "no-key"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "tts_client.py"),
             "--provider", "cosyvoice", "--key-file", str(missing),
             "--out-dir", str(pathlib.Path(temp) / "out"), "你好"],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            timeout=30)
    check("missing key exit", result.returncode, 2)
    check("missing key reason", "missing_api_key" in result.stderr, True)
    check("missing key stdout empty", result.stdout.strip(), "")


def test_cli_with_fake_server():
    print("CLI against a local fake server")
    api = FakeDashScope()
    try:
        with tempfile.TemporaryDirectory() as temp:
            temp = pathlib.Path(temp)
            key = temp / "key"
            key.write_text(FAKE_KEY + "\n", encoding="utf-8")
            key.chmod(0o600)
            env = os.environ.copy()
            env.pop("DASHSCOPE_API_KEY", None)
            env.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "tts_client.py"),
                 "--provider", "cosyvoice", "--base-url", api.base_url,
                 "--key-file", str(key), "--out-dir", str(temp / "out"),
                 "--json", SENTENCE],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=30)
        check("cli exit", result.returncode, 0)
        payload = json.loads(result.stdout)
        check("cli pcm", payload["pcm_bytes"], len(PCM))
        check("cli key not printed", FAKE_KEY in result.stdout + result.stderr,
              False)
    finally:
        api.close()


def main():
    test_sse_success()
    test_url_fallback()
    test_http_errors()
    test_key_loading()
    test_text_and_cost()
    test_edge_provider()
    test_cli_without_key()
    test_cli_with_fake_server()
    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
