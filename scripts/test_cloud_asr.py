#!/usr/bin/env python3
"""Local tests for scripts/cloud_asr.py; no real ASR service is contacted.

A fake OpenAI-compatible server exercises request shape, data-URI encoding,
context messages, response parsing, cost estimates, error mapping, bounded
retries and key isolation. Run with: .venv/bin/python scripts/test_cloud_asr.py
"""

import base64
import contextlib
import http.server
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import threading
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import cloud_asr  # noqa: E402

FAKE_KEY = "sk-asr-0123456789abcdef0123456789abcdef"
os.environ["DASHSCOPE_API_KEY"] = FAKE_KEY
SAMPLE_RATE = 16000

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


def make_wav(path, seconds=1.0, rate=SAMPLE_RATE, channels=1, width=2,
             frames=None):
    if frames is None:
        frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\x10\x00" * frames * channels)
    return path


class FakeServer:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.body = self.success_body()
        self.headers = {}
        self.delay = 0.0
        self.sequence = None  # list of (status, body, headers)
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
                    import time
                    time.sleep(fake.delay)
                status, payload, headers = fake.status, fake.body, fake.headers
                if fake.sequence:
                    status, payload, headers = fake.sequence.pop(0)
                if isinstance(payload, (dict, list)):
                    payload = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                     Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    @staticmethod
    def success_body(text="你好，我是小桌。", seconds=1, language="zh"):
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "model": "qwen3-asr-flash",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": text,
                    "annotations": [{
                        "type": "audio_info",
                        "language": language,
                        "emotion": "neutral",
                    }],
                },
            }],
            "usage": {
                "completion_tokens": 12,
                "prompt_tokens": 42,
                "total_tokens": 54,
                "seconds": seconds,
                "prompt_tokens_details": {"audio_tokens": 42},
            },
        }

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def expect_error(name, func, reason):
    try:
        func()
    except cloud_asr.CloudASRError as exc:
        check(name + "_reason", exc.reason, reason)
        return exc
    except Exception as exc:  # noqa: BLE001
        check(name + "_reason", type(exc).__name__, reason)
        return None
    check(name + "_reason", "no-error", reason)
    return None


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cloud-asr-test-"))
    server = FakeServer()
    good = make_wav(tmp / "good.wav", 2.0)
    config = cloud_asr.ASRConfig(base_url=server.base_url)

    print("[1] key loading")
    env_key = cloud_asr.load_api_key(str(tmp / "missing"))
    check("env_source", env_key.source, "env:DASHSCOPE_API_KEY")
    check("env_length", len(env_key.key), len(FAKE_KEY))
    key_file = tmp / "key"
    key_file.write_text("sk-file-0123456789abcdef0123456789\n")
    key_file.chmod(0o600)
    os.environ.pop("DASHSCOPE_API_KEY", None)
    file_key = cloud_asr.load_api_key(str(key_file))
    check("file_source", file_key.source, str(key_file))
    check("file_strip", file_key.key.endswith("\n"), False)
    check("file_permissions", file_key.loose_permissions, False)
    key_file.chmod(0o644)
    check("loose_permissions",
          cloud_asr.load_api_key(str(key_file)).loose_permissions, True)
    expect_error("missing_key", lambda: cloud_asr.load_api_key(
        str(tmp / "absent")), "missing_api_key")
    key_file.write_text("short")
    expect_error("short_key", lambda: cloud_asr.load_api_key(
        str(key_file)), "invalid_api_key")
    key_file.write_text("bad key with spaces 0123456789")
    expect_error("space_key", lambda: cloud_asr.load_api_key(
        str(key_file)), "invalid_api_key")
    os.environ["DASHSCOPE_API_KEY"] = FAKE_KEY

    print("[2] WAV validation")
    check("duration", round(cloud_asr.inspect_wav(good)[0], 3), 2.0)
    expect_error("missing_wav", lambda: cloud_asr.inspect_wav(
        tmp / "absent.wav"), "bad_wav")
    bad_rate = make_wav(tmp / "rate.wav", rate=8000)
    expect_error("rate", lambda: cloud_asr.inspect_wav(bad_rate), "bad_wav")
    stereo = make_wav(tmp / "stereo.wav", channels=2)
    expect_error("stereo", lambda: cloud_asr.inspect_wav(stereo), "bad_wav")
    empty = make_wav(tmp / "empty.wav", frames=0)
    expect_error("empty", lambda: cloud_asr.inspect_wav(empty), "bad_wav")
    long_file = make_wav(tmp / "long.wav", seconds=301.0)
    expect_error("too_long", lambda: cloud_asr.inspect_wav(long_file),
                 "audio_too_long")

    print("[3] request shape")
    server.requests.clear()
    record = cloud_asr.transcribe_file(good, config)
    check("status", record["status"], "success")
    check("text", record["text"], "你好，我是小桌。")
    check("language", record["language"], "zh")
    check("emotion", record["emotion"], "neutral")
    check("usage_seconds", record["usage"].get("seconds"), 1)
    check("cost", record["cost_cny_estimate"], 0.00022)
    check("request_count", len(server.requests), 1)
    request = server.requests[0]
    check("path", request["path"], "/v1/chat/completions")
    check("auth", request["headers"].get("Authorization")
          == f"Bearer {FAKE_KEY}", True)
    check("model", request["json"]["model"], "qwen3-asr-flash")
    check("stream", request["json"]["stream"], False)
    check("language_option", request["json"]["asr_options"]["language"], "zh")
    check("itn_default", request["json"]["asr_options"]["enable_itn"], False)
    content = request["json"]["messages"][0]["content"]
    check("content_type", content[0]["type"], "input_audio")
    uri = content[0]["input_audio"]["data"]
    check("data_prefix", uri.startswith("data:audio/wav;base64,"), True)
    decoded = base64.b64decode(uri.split(",", 1)[1])
    check("data_matches_file",
          decoded == pathlib.Path(good).read_bytes(), True)

    print("[4] context message")
    server.requests.clear()
    context_config = cloud_asr.ASRConfig(
        base_url=server.base_url, context="小桌, 桌宠")
    cloud_asr.transcribe_file(good, context_config)
    messages = server.requests[0]["json"]["messages"]
    check("message_count", len(messages), 2)
    check("system_role", messages[0]["role"], "system")
    check("system_text", messages[0]["content"], "小桌, 桌宠")
    check("user_role", messages[1]["role"], "user")

    print("[5] options and cost")
    check("cost_beijing",
          cloud_asr.estimate_cost_cny(
              "https://dashscope.aliyuncs.com/compatible-mode/v1", 10),
          0.0022)
    check("cost_singapore",
          cloud_asr.estimate_cost_cny(
              "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", 10),
          0.0026)
    check("cost_zero", cloud_asr.estimate_cost_cny(server.base_url, 0), 0.0)

    print("[6] HTTP errors")
    os.environ["DASHSCOPE_API_KEY"] = FAKE_KEY
    server.status = 401
    server.body = {"error": {"message": "invalid key " + FAKE_KEY}}
    exc = expect_error("http_401", lambda: cloud_asr.transcribe_file(
        good, config), "http_401")
    check("redacted", FAKE_KEY in (exc.message if exc else ""), False)
    server.status = 403
    expect_error("http_403", lambda: cloud_asr.transcribe_file(
        good, config), "http_403")
    server.status = 400
    expect_error("http_400", lambda: cloud_asr.transcribe_file(
        good, config), "http_error")
    server.status = 200
    server.body = b"not json"
    expect_error("bad_json", lambda: cloud_asr.transcribe_file(
        good, config), "bad_response")
    server.body = {"choices": []}
    expect_error("no_choices", lambda: cloud_asr.transcribe_file(
        good, config), "bad_response")
    server.body = {"choices": [{"message": {"content": "  "}}]}
    expect_error("empty_text", lambda: cloud_asr.transcribe_file(
        good, config), "empty_text")

    print("[7] retries")
    server.body = server.success_body()
    server.sequence = [
        (500, {"error": {"message": "temporary"}}, {"Retry-After": "0"}),
        (429, {"error": {"message": "busy"}}, {"Retry-After": "0"}),
        (200, server.success_body(), {}),
    ]
    server.requests.clear()
    retry_config = cloud_asr.ASRConfig(base_url=server.base_url,
                                       max_retries=2)
    record = cloud_asr.transcribe_file(good, retry_config)
    check("retry_success", record["text"], "你好，我是小桌。")
    check("retry_attempts", len(server.requests), 3)
    server.sequence = [
        (500, {"error": {"message": "temporary"}}, {"Retry-After": "0"}),
        (500, {"error": {"message": "temporary"}}, {"Retry-After": "0"}),
    ]
    server.requests.clear()
    expect_error("retry_exhausted", lambda: cloud_asr.transcribe_file(
        good, config), "http_5xx")
    check("retry_exhausted_attempts", len(server.requests), 2)
    server.sequence = [
        (401, {"error": {"message": "bad key"}}, {}),
        (200, server.success_body(), {}),
    ]
    server.requests.clear()
    expect_error("no_retry_401", lambda: cloud_asr.transcribe_file(
        good, config), "http_401")
    check("no_retry_401_attempts", len(server.requests), 1)

    print("[8] CLI JSON")
    server.sequence = None
    server.status = 200
    server.body = server.success_body(text="测试输出")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cloud_asr.main(["--json", "--base-url", server.base_url,
                               str(good)])
    check("cli_exit", code, 0)
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    check("cli_lines", len(lines), 1)
    payload = json.loads(lines[0])
    check("cli_text", payload["text"], "测试输出")
    check("cli_provider", payload["provider"], "qwen3-asr-flash")
    check("cli_no_key", FAKE_KEY in out.getvalue(), False)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cloud_asr.main(["--json", "--base-url", server.base_url,
                               str(tmp / "absent.wav")])
    payload = json.loads(out.getvalue().strip().splitlines()[-1])
    check("cli_error_exit", code, 1)
    check("cli_error_status", payload["status"], "error")
    check("cli_error_reason", payload["reason"], "bad_wav")

    server.close()
    print()
    print(f"{'PASS' if failures == 0 else 'FAIL'}: {checks - failures}/"
          f"{checks} checks passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
