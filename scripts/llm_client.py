#!/usr/bin/env python3
"""Host-side chat client for the desktop robot (DeepSeek first).

The ESP32 never holds an API key and never calls the LLM directly. This module
talks to the DeepSeek OpenAI-compatible endpoint from the Ubuntu host, keeps a
small bounded history, and returns short replies suitable for later TTS.

The API key comes from the local environment variable DEEPSEEK_API_KEY or from
an ignored file (default work/deepseek_api_key, mode 600). It is never printed,
written to a session record, or put in an error message.

Examples:
    export DEEPSEEK_API_KEY=...        # run in the user's own terminal
    .venv/bin/python scripts/llm_client.py "你好，你是谁？"
    .venv/bin/python scripts/llm_client.py --interactive
    .venv/bin/python scripts/llm_client.py --json "今天适合出门吗？"

Only real user action sends a paid request; tests always point at a local fake
server. Pricing is a 2026-11-09 snapshot and is an estimate, not a bill.
"""

from __future__ import annotations

import argparse
import datetime
import http.client
import json
import os
import pathlib
import socket
import stat
import sys
import time
import urllib.parse

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_TOKENS = 200
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_HISTORY_TURNS = 6
DEFAULT_MAX_CONTEXT_CHARS = 4000
DEFAULT_KEY_FILE = "work/deepseek_api_key"
DEFAULT_SESSION_DIR = "work/sessions"
MAX_USER_CHARS = 500

SYSTEM_PROMPT = (
    "你是“小桌”，一只住在 ESP32 桌面机器人里的 AI 小伙伴。"
    "请用自然、温暖、简短的中文回答，像陪在主人身边的朋友。"
    "每次回答尽量不超过两句话或 50 个汉字，因为回答之后会被朗读出来。"
    "不要使用 Markdown、列表、代码块或表情符号；不确定的事情要坦率说明。"
)

# USD per 1 million tokens, fetched from api-docs.deepseek.com/quick_start/pricing
# on 2026-11-09. Peak windows are 01:00-04:00 and 06:00-10:00 UTC on weekdays;
# Chinese public holidays are not modelled, so holiday traffic may be
# overestimated. These numbers are for planning only and do not replace the
# official bill.
PRICING_SNAPSHOT = "2026-11-09"
PRICING = {
    "deepseek-flash": {
        "peak": {"cache_hit": 0.006, "cache_miss": 0.30, "output": 1.20},
        "off_peak": {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60},
    },
    "deepseek-v4-flash": {
        "peak": {"cache_hit": 0.006, "cache_miss": 0.30, "output": 1.20},
        "off_peak": {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.60},
    },
}


class LLMError(Exception):
    """A sanitized failure that never contains the API key."""

    def __init__(self, reason, message="", http_status=None, retry_after=None):
        self.reason = reason
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after
        text = reason if not message else f"{reason}: {message}"
        super().__init__(text)


class KeyInfo:
    """Loaded key plus its source. The key itself is excluded from repr."""

    def __init__(self, key, source, key_file=None, loose_permissions=False):
        self.key = key
        self.source = source
        self.key_file = key_file
        self.loose_permissions = loose_permissions

    def __repr__(self):
        return (f"KeyInfo(source={self.source!r}, "
                f"loose_permissions={self.loose_permissions})")

    __str__ = __repr__


class LLMConfig:
    def __init__(self, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL,
                 max_tokens=DEFAULT_MAX_TOKENS,
                 temperature=DEFAULT_TEMPERATURE,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 read_timeout=DEFAULT_READ_TIMEOUT):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

    def validate(self):
        if not self.model:
            raise LLMError("bad_config", "model must not be empty")
        if not 1 <= self.max_tokens <= 8192:
            raise LLMError("bad_config",
                           "max_tokens must be between 1 and 8192")
        if not 0.0 <= self.temperature <= 2.0:
            raise LLMError("bad_config",
                           "temperature must be between 0 and 2")
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise LLMError("bad_config", "timeouts must be positive")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise LLMError("bad_config", "base_url must be http(s)://host")


class LLMResponse:
    def __init__(self, text, model, usage, request_id, latency_ms,
                 http_status):
        self.text = text
        self.model = model
        self.usage = usage
        self.request_id = request_id
        self.latency_ms = latency_ms
        self.http_status = http_status


def load_api_key(key_file=DEFAULT_KEY_FILE):
    """Load the key from the environment, then from an ignored file."""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    source = "env:DEEPSEEK_API_KEY"
    path = None
    loose = False
    if not key:
        path = pathlib.Path(key_file)
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            raise LLMError(
                "missing_api_key",
                f"set DEEPSEEK_API_KEY or write the key to {path} "
                f"(chmod 600)") from None
        source = str(path)
        try:
            loose = bool(stat.S_IMODE(path.stat().st_mode) & 0o077)
        except OSError:
            loose = False
    if not 16 <= len(key) <= 200 or any(
            ord(ch) < 0x21 or ord(ch) > 0x7E for ch in key):
        raise LLMError(
            "invalid_api_key",
            f"key from {source} must be 16-200 printable ASCII characters")
    return KeyInfo(key, source, path, loose)


def valid_user_text(text):
    """Reject empty, punctuation-only or absurdly long ASR output."""
    value = (text or "").strip()
    if not value or len(value) > MAX_USER_CHARS:
        return False
    return any(ch.isalnum() for ch in value)


def is_peak_time(now_utc=None):
    now = now_utc or datetime.datetime.now(datetime.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    now = now.astimezone(datetime.timezone.utc)
    return now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)


def estimate_cost(model, usage, now_utc=None):
    """Return (usd, peak) or (None, peak) when the model/prices are unknown."""
    peak = is_peak_time(now_utc)
    prices = PRICING.get(model)
    if prices is None:
        return None, peak
    if not usage:
        return None, peak
    rate = prices["peak" if peak else "off_peak"]
    prompt = max(0, int(usage.get("prompt_tokens") or 0))
    hit = max(0, int(usage.get("prompt_cache_hit_tokens") or 0))
    miss = usage.get("prompt_cache_miss_tokens")
    miss = max(0, prompt - hit) if miss is None else max(0, int(miss))
    output = max(0, int(usage.get("completion_tokens") or 0))
    cost = (hit * rate["cache_hit"] + miss * rate["cache_miss"]
            + output * rate["output"]) / 1_000_000.0
    return round(cost, 8), peak


class DeepSeekProvider:
    """Minimal OpenAI-compatible chat client with thinking mode disabled."""

    name = "deepseek"

    def __init__(self, config, api_key):
        config.validate()
        self.config = config
        self._api_key = api_key

    def complete(self, messages):
        body = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "stream": False,
            "thinking": {"type": "disabled"},
        }, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "ai-desktop-robot/0.1",
        }

        parsed = urllib.parse.urlsplit(self.config.base_url)
        path = parsed.path.rstrip("/") + "/chat/completions"
        connection_class = (http.client.HTTPSConnection
                            if parsed.scheme == "https"
                            else http.client.HTTPConnection)
        connection = connection_class(parsed.hostname, parsed.port,
                                      timeout=self.config.connect_timeout)
        started = time.perf_counter()
        try:
            try:
                connection.connect()
                if connection.sock is not None:
                    connection.sock.settimeout(self.config.read_timeout)
                connection.request("POST", path, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read()
            except socket.timeout:
                raise LLMError("timeout",
                               "DeepSeek request timed out") from None
            except (OSError, http.client.HTTPException) as exc:
                raise LLMError("network_error",
                               type(exc).__name__) from None
        finally:
            connection.close()

        latency_ms = (time.perf_counter() - started) * 1000.0
        status = response.status
        if status != 200:
            detail = self._error_detail(raw)
            reason = {
                401: "http_401",
                402: "http_402",
                429: "http_429",
            }.get(status, "http_5xx" if status >= 500 else "http_error")
            raise LLMError(reason, f"HTTP {status}: {detail}",
                           http_status=status,
                           retry_after=response.getheader("Retry-After"))

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise LLMError("bad_response", "response is not valid JSON",
                           http_status=status) from None
        if not isinstance(payload, dict):
            raise LLMError("bad_response", "response is not an object",
                           http_status=status)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("bad_response", "response has no choices",
                           http_status=status)
        message = choices[0].get("message") if isinstance(choices[0], dict) \
            else None
        if not isinstance(message, dict):
            raise LLMError("bad_response", "choice has no message",
                           http_status=status)
        text = str(message.get("content") or "").strip()
        if not text:
            if message.get("reasoning_content"):
                raise LLMError(
                    "empty_reply",
                    "only reasoning_content returned; check thinking mode",
                    http_status=status)
            raise LLMError("empty_reply", "assistant content is empty",
                           http_status=status)

        usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        clean_usage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                    "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                clean_usage[key] = value
        return LLMResponse(
            text=text,
            model=str(payload.get("model") or self.config.model),
            usage=clean_usage,
            request_id=str(payload.get("id") or ""),
            latency_ms=latency_ms,
            http_status=status,
        )

    def _error_detail(self, raw, limit=300):
        text = ""
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    text = str(error.get("message") or error.get("code") or "")
                elif error:
                    text = str(error)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        if not text:
            text = raw.decode("utf-8", "replace")
        text = " ".join(text.split())[:limit]
        return text.replace(self._api_key, "[redacted]")


class ChatSession:
    """Bounded multi-turn history plus one JSON record per turn."""

    def __init__(self, provider, system_prompt=SYSTEM_PROMPT,
                 max_turns=DEFAULT_HISTORY_TURNS,
                 max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
                 session_dir=None, session_id=None):
        if max_turns < 0:
            raise LLMError("bad_config", "history turns must not be negative")
        if max_context_chars < 100:
            raise LLMError("bad_config",
                           "max context chars must be at least 100")
        self.provider = provider
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.max_context_chars = max_context_chars
        self.session_dir = (pathlib.Path(session_dir)
                            if session_dir else None)
        self.session_id = session_id or (
            "chat-" + time.strftime("%Y%m%d-%H%M%S") + "-"
            + os.urandom(2).hex())
        self.messages = [{"role": "system", "content": system_prompt}]
        self.turn = 0

    def ask(self, user_text, meta=None):
        """Send one user turn. Returns a record; provider errors are recorded."""
        text = (user_text or "").strip()
        if not valid_user_text(text):
            raise LLMError("invalid_text",
                           "empty, punctuation-only or too long")
        self.turn += 1
        number = self.turn
        meta = dict(meta or {})
        started_at = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        try:
            response = self.provider.complete(self._request_messages(text))
        except LLMError as exc:
            record = {
                **meta,
                "session_id": self.session_id,
                "turn": number,
                "status": "error",
                "reason": exc.reason,
                "error": exc.message,
                "http_status": exc.http_status,
                "user_text": text,
                "reply_text": "",
                "model": getattr(self.provider.config, "model",
                                 DEFAULT_MODEL),
                "thinking": "disabled",
                "started_at": started_at,
                "finished_at": datetime.datetime.now().astimezone().isoformat(
                    timespec="seconds"),
            }
            record["record_file"] = self._save(record)
            return record

        self.messages.append({"role": "user", "content": text})
        self.messages.append({"role": "assistant", "content": response.text})
        self._trim_history()
        cost, peak = estimate_cost(response.model, response.usage)
        record = {
            **meta,
            "session_id": self.session_id,
            "turn": number,
            "status": "success",
            "user_text": text,
            "reply_text": response.text,
            "model": response.model,
            "thinking": "disabled",
            "latency_ms": round(response.latency_ms, 1),
            "http_status": response.http_status,
            "request_id": response.request_id,
            "usage": response.usage,
            "cost_usd": cost,
            "pricing_peak": peak,
            "pricing_snapshot": PRICING_SNAPSHOT,
            "started_at": started_at,
            "finished_at": datetime.datetime.now().astimezone().isoformat(
                timespec="seconds"),
        }
        record["record_file"] = self._save(record)
        return record

    def _trim_history(self):
        """Keep in-memory history bounded even in a long-running receiver."""
        if self.max_turns == 0:
            del self.messages[1:]
            return
        keep = 2 * self.max_turns
        if len(self.messages) - 1 > keep:
            self.messages = self.messages[:1] + self.messages[-keep:]
            while len(self.messages) > 1 and \
                    self.messages[1]["role"] != "user":
                del self.messages[1]

    def _request_messages(self, next_user):
        history = self.messages[1:]
        if self.max_turns == 0:
            history = []
        else:
            history = history[-2 * self.max_turns:]
            while history and history[0]["role"] != "user":
                history.pop(0)
        messages = [self.messages[0], *history,
                    {"role": "user", "content": next_user}]
        while len(messages) > 3 and sum(
                len(item["content"]) for item in messages[1:]
        ) > self.max_context_chars:
            del messages[1:3]
        return messages

    def _save(self, record):
        if self.session_dir is None:
            return None
        self.session_dir.mkdir(parents=True, exist_ok=True)
        final = self.session_dir / (
            f"{self.session_id}-turn-{record['turn']:03d}.json")
        temp = self.session_dir / f".{final.name}.{os.getpid()}.tmp"
        try:
            temp.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            os.replace(temp, final)
        except OSError as exc:
            print(f"[llm] record_write_failed reason={type(exc).__name__}",
                  flush=True)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        return str(final)


def _build_session(args):
    config = LLMConfig(
        model=args.model,
        base_url=args.base_url,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
    )
    key_info = load_api_key(args.key_file)
    if key_info.loose_permissions:
        print(f"[llm] warning: {key_info.source} is readable by group/others",
              file=sys.stderr, flush=True)
    provider = DeepSeekProvider(config, key_info.key)
    session_dir = None if args.no_save else args.session_dir
    session = ChatSession(
        provider,
        max_turns=args.history_turns,
        max_context_chars=args.max_context_chars,
        session_dir=session_dir,
    )
    return session, key_info


def _print_stats(record):
    if record["status"] != "success":
        print(f"ERR reason={record['reason']} detail={record.get('error', '')}",
              file=sys.stderr)
        return
    usage = record.get("usage") or {}
    cost = record.get("cost_usd")
    cost_text = ("unknown" if cost is None
                 else f"${cost:.6f} ({'peak' if record.get('pricing_peak') else 'off-peak'})")
    print(f"[stats] model={record['model']} latency_ms={record['latency_ms']} "
          f"prompt_tokens={usage.get('prompt_tokens', '?')} "
          f"completion_tokens={usage.get('completion_tokens', '?')} "
          f"total_tokens={usage.get('total_tokens', '?')} cost={cost_text} "
          f"session={record['session_id']} turn={record['turn']}")


def main():
    parser = argparse.ArgumentParser(
        description="Talk to DeepSeek from the host; the ESP32 keeps no key")
    parser.add_argument("prompt", nargs="*", help="one-shot user message")
    parser.add_argument("--interactive", action="store_true",
                        help="read messages from stdin until exit/quit")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON record per turn")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--temperature", type=float,
                        default=DEFAULT_TEMPERATURE)
    parser.add_argument("--connect-timeout", type=float,
                        default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--read-timeout", type=float,
                        default=DEFAULT_READ_TIMEOUT)
    parser.add_argument("--history-turns", type=int,
                        default=DEFAULT_HISTORY_TURNS)
    parser.add_argument("--max-context-chars", type=int,
                        default=DEFAULT_MAX_CONTEXT_CHARS)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    parser.add_argument("--session-dir", default=DEFAULT_SESSION_DIR)
    parser.add_argument("--no-save", action="store_true",
                        help="do not write turn records under --session-dir")
    args = parser.parse_args()

    try:
        session, key_info = _build_session(args)
    except LLMError as exc:
        print(f"ERR reason={exc.reason} detail={exc.message}", file=sys.stderr)
        return 2

    print(f"[llm] provider=deepseek model={args.model} "
          f"thinking=disabled max_tokens={args.max_tokens} "
          f"history_turns={args.history_turns} key_source={key_info.source}",
          file=sys.stderr if args.json else sys.stdout, flush=True)

    def run_turn(text):
        try:
            record = session.ask(text)
        except LLMError as exc:
            print(f"ERR reason={exc.reason} detail={exc.message}",
                  file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            print(f"[user] {record['user_text']}", flush=True)
            if record["status"] == "success":
                print(f"[ai] {record['reply_text']}", flush=True)
            _print_stats(record)
        return 0 if record["status"] == "success" else 1

    if args.interactive:
        if args.json:
            print("ERR reason=bad_config detail=--json cannot be interactive",
                  file=sys.stderr)
            return 2
        while True:
            try:
                text = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text.lower() in ("exit", "quit", "q"):
                break
            if not text:
                continue
            run_turn(text)
        return 0

    text = " ".join(args.prompt).strip()
    if not text:
        parser.error("provide a message or use --interactive")
    return run_turn(text)


if __name__ == "__main__":
    sys.exit(main())
