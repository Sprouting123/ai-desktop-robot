#!/usr/bin/env python3
"""Local tests for scripts/llm_client.py; no real API is contacted.

A fake OpenAI-compatible server on 127.0.0.1 records each request and returns
configurable responses. Tests cover request shape, thinking-mode disabling,
bounded history, key loading, HTTP/timeout/malformed-response handling, cost
estimation and session records. No paid request can be triggered here.

Run with: .venv/bin/python scripts/test_llm_client.py
"""

import datetime
import http.server
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import llm_client  # noqa: E402

FAKE_KEY = "sk-test-0123456789abcdef0123456789abcdef"
REPLY = "我在呢，今天想聊点什么？"

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


def success_body(reply=REPLY, usage=None):
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": "deepseek-flash",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop",
        }],
        "usage": usage if usage is not None else {
            "prompt_tokens": 120,
            "completion_tokens": 18,
            "total_tokens": 138,
            "prompt_cache_hit_tokens": 20,
            "prompt_cache_miss_tokens": 100,
        },
    }


class FakeAPI:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.body = success_body()
        self.delay = 0.0
        self.retry_after = None
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                fake.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "json": payload,
                })
                if fake.delay:
                    time.sleep(fake.delay)
                body = fake.body
                if not isinstance(body, bytes):
                    body = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if fake.retry_after:
                    self.send_header("Retry-After", str(fake.retry_after))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *args):
                return

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def make_provider(api, **overrides):
    options = {
        "base_url": api.base_url,
        "connect_timeout": 2.0,
        "read_timeout": 5.0,
    }
    options.update(overrides)
    return llm_client.DeepSeekProvider(
        llm_client.LLMConfig(**options), FAKE_KEY)


def make_session(api, session_dir=None, history_turns=6,
                 max_context_chars=4000, **provider_overrides):
    return llm_client.ChatSession(
        make_provider(api, **provider_overrides),
        max_turns=history_turns,
        max_context_chars=max_context_chars,
        session_dir=session_dir)


def test_request_and_success():
    print("request shape and success parsing")
    api = FakeAPI()
    try:
        session = make_session(api)
        record = session.ask("你好，你是谁？")
        check("status", record["status"], "success")
        check("reply", record["reply_text"], REPLY)
        check("model", record["model"], "deepseek-flash")
        check("thinking disabled", record["thinking"], "disabled")
        check_true("latency recorded", record["latency_ms"] > 0)
        check("usage prompt", record["usage"].get("prompt_tokens"), 120)
        check("usage completion", record["usage"].get("completion_tokens"), 18)
        check_true("cost estimated", record["cost_usd"] is not None)
        check_true("cost positive", record["cost_usd"] > 0)
        check("request count", len(api.requests), 1)
        request = api.requests[0]
        check("request path", request["path"], "/chat/completions")
        check("auth header present",
              request["headers"].get("Authorization") == f"Bearer {FAKE_KEY}",
              True)
        body = request["json"]
        check("body model", body.get("model"), "deepseek-flash")
        check("body max_tokens", body.get("max_tokens"),
              llm_client.DEFAULT_MAX_TOKENS)
        check("body stream", body.get("stream"), False)
        check("body thinking", body.get("thinking"), {"type": "disabled"})
        messages = body.get("messages") or []
        check("system prompt first", messages[0]["role"], "system")
        check_true("system prompt non-empty", messages[0]["content"])
        check("user message", messages[-1],
              {"role": "user", "content": "你好，你是谁？"})
    finally:
        api.close()


def test_history_is_bounded():
    print("bounded multi-turn history")
    api = FakeAPI()
    try:
        session = make_session(api, history_turns=1)
        session.ask("a")
        session.ask("b")
        session.ask("c")
        messages = api.requests[-1]["json"]["messages"]
        check("roles", [m["role"] for m in messages],
              ["system", "user", "assistant", "user"])
        check("kept previous user", messages[1]["content"], "b")
        check("kept previous reply", messages[2]["content"], REPLY)
        check("current user", messages[3]["content"], "c")
        check("stored history bounded", len(session.messages), 3)

        no_history = make_session(api, history_turns=0)
        no_history.ask("x")
        no_history.ask("y")
        messages = api.requests[-1]["json"]["messages"]
        check("history_turns=0 roles", [m["role"] for m in messages],
              ["system", "user"])
        check("history_turns=0 current", messages[-1]["content"], "y")
        check("history_turns=0 stored", len(no_history.messages), 1)

        api.requests.clear()
        char_session = make_session(api, history_turns=6,
                                    max_context_chars=100)
        char_session.ask("甲" * 60)
        char_session.ask("乙" * 60)
        messages = api.requests[-1]["json"]["messages"]
        check("char budget drops old pair",
              [m["role"] for m in messages], ["system", "user"])
        check("char budget keeps current", messages[-1]["content"], "乙" * 60)
    finally:
        api.close()


def test_key_loading():
    print("API key loading and permissions")
    saved = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as temp:
            temp = pathlib.Path(temp)
            missing = temp / "missing_key"
            try:
                llm_client.load_api_key(missing)
                reason = None
            except llm_client.LLMError as exc:
                reason = exc.reason
            check("missing key reason", reason, "missing_api_key")

            short = temp / "short_key"
            short.write_text("sk-short\n", encoding="utf-8")
            try:
                llm_client.load_api_key(short)
                reason = None
            except llm_client.LLMError as exc:
                reason = exc.reason
            check("short key reason", reason, "invalid_api_key")

            good = temp / "good_key"
            good.write_text(FAKE_KEY + "\n", encoding="utf-8")
            good.chmod(0o644)
            info = llm_client.load_api_key(good)
            check("loaded from file", info.key == FAKE_KEY, True)
            check("loose permissions detected", info.loose_permissions, True)
            check("repr hides key", FAKE_KEY in repr(info), False)
            good.chmod(0o600)
            info = llm_client.load_api_key(good)
            check("tight permissions", info.loose_permissions, False)

            os.environ["DEEPSEEK_API_KEY"] = FAKE_KEY
            info = llm_client.load_api_key(good)
            check("environment wins", info.source,
                  "env:DEEPSEEK_API_KEY")
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        if saved is not None:
            os.environ["DEEPSEEK_API_KEY"] = saved


def test_http_errors():
    print("HTTP error handling")
    api = FakeAPI()
    try:
        api.status = 401
        api.body = {"error": {"message": "Authentication Fails"}}
        try:
            make_provider(api).complete([{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
            check("401 status", exc.http_status, 401)
            check("401 message excludes key", FAKE_KEY in exc.message, False)
        check("401 reason", reason, "http_401")

        api.status = 429
        api.body = {"error": {"message": "rate limited"}}
        api.retry_after = 7
        try:
            make_provider(api).complete([{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
            check("429 retry-after", exc.retry_after, "7")
        check("429 reason", reason, "http_429")

        api.status = 500
        api.body = b"upstream boom"
        try:
            make_provider(api).complete([{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
        check("5xx reason", reason, "http_5xx")
    finally:
        api.close()

    print("timeouts, malformed replies, network errors")
    api = FakeAPI()
    try:
        api.delay = 1.0
        try:
            make_provider(api, read_timeout=0.3).complete(
                [{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
        check("read timeout reason", reason, "timeout")
    finally:
        api.delay = 0.0
        api.close()

    api = FakeAPI()
    try:
        api.body = b"{not json"
        try:
            make_provider(api).complete([{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
        check("bad json reason", reason, "bad_response")

        api.body = {"choices": []}
        try:
            make_provider(api).complete([{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
        check("empty choices reason", reason, "bad_response")

        api.body = {"choices": [{"message": {"content": "",
                                             "reasoning_content": "思考"}}]}
        try:
            make_provider(api).complete([{"role": "user", "content": "hi"}])
            reason = None
        except llm_client.LLMError as exc:
            reason = exc.reason
        check("reasoning-only reason", reason, "empty_reply")
    finally:
        api.close()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    provider = llm_client.DeepSeekProvider(
        llm_client.LLMConfig(base_url=f"http://127.0.0.1:{port}",
                             connect_timeout=0.5), FAKE_KEY)
    try:
        provider.complete([{"role": "user", "content": "hi"}])
        reason = None
    except llm_client.LLMError as exc:
        reason = exc.reason
    check("connection refused reason", reason, "network_error")


def test_cost_estimation():
    print("cost estimation")
    usage = {"prompt_tokens": 3000, "completion_tokens": 500,
             "prompt_cache_hit_tokens": 1000,
             "prompt_cache_miss_tokens": 2000}
    peak_time = datetime.datetime(2026, 11, 9, 2, 0,
                                  tzinfo=datetime.timezone.utc)
    off_peak_time = datetime.datetime(2026, 11, 8, 12, 0,
                                      tzinfo=datetime.timezone.utc)
    cost, peak = llm_client.estimate_cost("deepseek-flash", usage, peak_time)
    check("peak flag", peak, True)
    check("peak cost", cost, 0.001206)
    cost, peak = llm_client.estimate_cost("deepseek-flash", usage,
                                          off_peak_time)
    check("off-peak flag", peak, False)
    check("off-peak cost", cost, 0.000603)
    cost, _ = llm_client.estimate_cost("unknown-model", usage, peak_time)
    check("unknown model cost", cost, None)
    cost, _ = llm_client.estimate_cost("deepseek-flash", {}, peak_time)
    check("empty usage cost", cost, None)
    check("Monday 02:00 UTC is peak",
          llm_client.is_peak_time(peak_time), True)
    check("Sunday noon UTC is off-peak",
          llm_client.is_peak_time(off_peak_time), False)
    check("weekday 05:00 UTC is off-peak",
          llm_client.is_peak_time(datetime.datetime(
              2026, 11, 9, 5, 0, tzinfo=datetime.timezone.utc)), False)


def test_text_validation():
    print("text validation")
    check("empty", llm_client.valid_user_text(""), False)
    check("spaces", llm_client.valid_user_text("   "), False)
    check("punctuation only", llm_client.valid_user_text("。。。！？"), False)
    check("short speech", llm_client.valid_user_text("嗯"), True)
    check("latin", llm_client.valid_user_text("hello"), True)
    check("too long", llm_client.valid_user_text("字" * 501), False)


def test_session_records():
    print("session record files")
    api = FakeAPI()
    try:
        with tempfile.TemporaryDirectory() as temp:
            temp = pathlib.Path(temp)
            session = make_session(api, session_dir=temp)
            record = session.ask("记录测试", meta={"wav": "mic-test.wav"})
            path = pathlib.Path(record["record_file"])
            check_true("record exists", path.is_file())
            check("record directory", path.parent, temp)
            saved = json.loads(path.read_text(encoding="utf-8"))
            check("record session id", saved["session_id"],
                  session.session_id)
            check("record turn", saved["turn"], 1)
            check("record wav meta", saved["wav"], "mic-test.wav")
            check("record status", saved["status"], "success")
            check("record usage", saved["usage"].get("total_tokens"), 138)
            check_true("record cost", saved["cost_usd"] is not None)
            check("record hides key", FAKE_KEY in path.read_text(
                encoding="utf-8"), False)

            api.status = 401
            api.body = {"error": {"message": "Authentication Fails"}}
            failed = session.ask("失败测试")
            check("failure status", failed["status"], "error")
            check("failure reason", failed["reason"], "http_401")
            check_true("failure record exists",
                       pathlib.Path(failed["record_file"]).is_file())
            check("failure turn increments", failed["turn"], 2)
    finally:
        api.close()


def test_cli_without_key():
    print("CLI without a key")
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory() as temp:
        missing = pathlib.Path(temp) / "no-such-key-file"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "llm_client.py"),
             "--key-file", str(missing), "--no-save", "你好"],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            timeout=30)
    check("missing key exit", result.returncode, 2)
    check("missing key reason in stderr",
          "missing_api_key" in result.stderr, True)
    check("stdout empty", result.stdout.strip(), "")


def main():
    test_request_and_success()
    test_history_is_bounded()
    test_key_loading()
    test_http_errors()
    test_cost_estimation()
    test_text_validation()
    test_session_records()
    test_cli_without_key()
    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
