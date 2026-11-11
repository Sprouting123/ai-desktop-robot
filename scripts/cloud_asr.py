#!/usr/bin/env python3
"""Cloud Chinese ASR provider for the desktop robot (Alibaba Model Studio).

This module is the replaceable cloud counterpart of ``scripts/asr_local.py``.
It sends one 16 kHz/16 bit/mono WAV file to ``qwen3-asr-flash`` through the
OpenAI-compatible chat endpoint and returns the transcript. The JSON output
keeps the same top-level ``status``/``text``/``inference_ms`` fields used by
``scripts/audio_receiver.py`` so the receiver can switch providers by changing
one command.

The API key is read from ``DASHSCOPE_API_KEY`` or from an ignored file
(default ``work/dashscope_api_key``, mode 600). It is never printed, stored in
a result file, or included in an error message.

Official references checked on 2026-11-11:
- https://help.aliyun.com/zh/model-studio/qwen3-asr-flash
- https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference
- https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope

Pricing is a snapshot, not a bill: 0.00022 CNY/s in cn-beijing and
0.00026 CNY/s in ap-southeast-1 (output is not billed). Beijing has a free
quota (36,000 s / 90 days at the time of writing) that this estimate does not
subtract; check the Model Studio console for the real balance.

Examples:
    export DASHSCOPE_API_KEY=...          # or write work/dashscope_api_key
    .venv/bin/python scripts/cloud_asr.py work/audio/mic-*.wav
    .venv/bin/python scripts/cloud_asr.py --json work/audio/x.wav
    .venv/bin/python scripts/cloud_asr.py --context "小桌,桌宠" x.wav
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import pathlib
import socket
import stat
import sys
import time
import urllib.parse
import wave

DEFAULT_MODEL = "qwen3-asr-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_KEY_FILE = "work/dashscope_api_key"
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 1
MAX_AUDIO_SECONDS = 300.0          # official limit: 5 minutes
MAX_ENCODED_BYTES = 10 * 1024 * 1024  # official limit: 10 MB after base64
MAX_CONTEXT_CHARS = 200
PRICING_SNAPSHOT = "2026-11-11"
COST_CNY_PER_SECOND = {
    "cn-beijing": 0.00022,
    "ap-southeast-1": 0.00026,
    "us-east-1": 0.00026,
}
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
RETRY_DELAY_CAP = 5.0


class CloudASRError(Exception):
    """A sanitized failure that never contains the API key."""

    def __init__(self, reason, message="", http_status=None, retryable=False,
                 retry_after=None):
        self.reason = reason
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after = retry_after
        text = reason if not message else f"{reason}: {message}"
        super().__init__(text)


class KeyInfo:
    """Loaded key plus its source; the key itself is excluded from repr."""

    def __init__(self, key, source, key_file=None, loose_permissions=False):
        self.key = key
        self.source = source
        self.key_file = key_file
        self.loose_permissions = loose_permissions

    def __repr__(self):
        return (f"KeyInfo(source={self.source!r}, "
                f"loose_permissions={self.loose_permissions})")

    __str__ = __repr__


class ASRConfig:
    def __init__(self, model=DEFAULT_MODEL, base_url=DEFAULT_BASE_URL,
                 language="zh", enable_itn=False, context="",
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 read_timeout=DEFAULT_READ_TIMEOUT,
                 max_retries=DEFAULT_MAX_RETRIES):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.enable_itn = enable_itn
        self.context = context.strip()
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max_retries

    def validate(self):
        if not self.model:
            raise CloudASRError("bad_config", "model must not be empty")
        if not self.language:
            raise CloudASRError("bad_config", "language must not be empty")
        if len(self.context) > MAX_CONTEXT_CHARS:
            raise CloudASRError(
                "bad_config",
                f"context must be at most {MAX_CONTEXT_CHARS} characters")
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise CloudASRError("bad_config", "timeouts must be positive")
        if not 0 <= self.max_retries <= 3:
            raise CloudASRError("bad_config", "max_retries must be 0-3")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise CloudASRError("bad_config", "base_url must be http(s)://host")


class ASRResponse:
    def __init__(self, text, model, language, emotion, usage, request_id,
                 latency_ms, http_status, duration_s):
        self.text = text
        self.model = model
        self.language = language
        self.emotion = emotion
        self.usage = usage
        self.request_id = request_id
        self.latency_ms = latency_ms
        self.http_status = http_status
        self.duration_s = duration_s


def load_api_key(key_file=DEFAULT_KEY_FILE):
    """Load the key from the environment, then from an ignored file."""
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    source = "env:DASHSCOPE_API_KEY"
    path = None
    loose = False
    if not key:
        path = pathlib.Path(key_file)
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            raise CloudASRError(
                "missing_api_key",
                f"set DASHSCOPE_API_KEY or write the key to {path} "
                f"(chmod 600)") from None
        source = str(path)
        try:
            loose = bool(stat.S_IMODE(path.stat().st_mode) & 0o077)
        except OSError:
            loose = False
    if not 16 <= len(key) <= 200 or any(
            ord(ch) < 0x21 or ord(ch) > 0x7E for ch in key):
        raise CloudASRError(
            "invalid_api_key",
            f"key from {source} must be 16-200 printable ASCII characters")
    return KeyInfo(key, source, path, loose)


def inspect_wav(path):
    """Validate a WAV file and return (duration_s, sample_rate, frames)."""
    path = pathlib.Path(path)
    if not path.is_file():
        raise CloudASRError("bad_wav", f"file does not exist: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            frames = wav.getnframes()
            comptype = wav.getcomptype()
    except (wave.Error, OSError) as exc:
        raise CloudASRError("bad_wav",
                            f"cannot parse WAV {path}: {exc}") from None
    if comptype != "NONE":
        raise CloudASRError("bad_wav", f"unsupported compression: {comptype}")
    if rate != 16000:
        raise CloudASRError("bad_wav", f"expected 16000 Hz, got {rate}")
    if width != 2:
        raise CloudASRError("bad_wav", f"expected 16 bit, got {width * 8}")
    if channels != 1:
        raise CloudASRError("bad_wav", f"expected mono, got {channels}")
    if frames == 0:
        raise CloudASRError("bad_wav", "WAV has no audio frames")
    duration = frames / float(rate)
    if duration > MAX_AUDIO_SECONDS:
        raise CloudASRError(
            "audio_too_long",
            f"{duration:.1f} s exceeds the {MAX_AUDIO_SECONDS:.0f} s limit")
    data_bytes = frames * width
    encoded_bytes = 4 * ((data_bytes + 2) // 3) + 32
    if encoded_bytes > MAX_ENCODED_BYTES:
        raise CloudASRError(
            "audio_too_large",
            f"base64 payload would be {encoded_bytes} bytes, "
            f"limit {MAX_ENCODED_BYTES}")
    return duration, rate, frames


def audio_data_uri(path):
    data = pathlib.Path(path).read_bytes()
    return "data:audio/wav;base64," + base64.b64encode(data).decode("ascii")


def estimate_cost_cny(base_url, duration_s):
    """Estimate cost from the official per-second price; None if unknown."""
    url = base_url.lower()
    if ("ap-southeast-1" in url or "singapore" in url
            or "dashscope-intl" in url):
        region = "ap-southeast-1"
    elif "us-east-1" in url:
        region = "us-east-1"
    else:
        region = "cn-beijing"
    price = COST_CNY_PER_SECOND.get(region)
    if price is None:
        return None
    return round(price * max(0.0, float(duration_s)), 8)


def _error_detail(raw, api_key, limit=300):
    text = ""
    try:
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                text = str(error.get("message") or error.get("code") or "")
            elif error:
                text = str(error)
            elif payload.get("message"):
                text = str(payload["message"])
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    if not text:
        text = raw.decode("utf-8", "replace")
    text = " ".join(text.split())[:limit]
    return text.replace(api_key, "[redacted]") if api_key else text


class CloudASRProvider:
    """One-shot qwen3-asr-flash client with bounded retries."""

    name = "qwen3-asr-flash"

    def __init__(self, config, api_key):
        config.validate()
        self.config = config
        self._api_key = api_key

    def transcribe(self, wav_path):
        duration_s, _, _ = inspect_wav(wav_path)
        data_uri = audio_data_uri(wav_path)
        messages = []
        if self.config.context:
            messages.append({"role": "system",
                             "content": self.config.context})
        messages.append({
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": data_uri},
            }],
        })
        body = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "asr_options": {
                "language": self.config.language,
                "enable_itn": self.config.enable_itn,
            },
        }, ensure_ascii=False).encode("utf-8")

        attempts = self.config.max_retries + 1
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                return self._request(body, duration_s, attempt)
            except CloudASRError as exc:
                last_error = exc
                if not exc.retryable or attempt >= attempts:
                    raise
                delay = RETRY_DELAY_CAP
                if exc.retry_after:
                    try:
                        delay = min(RETRY_DELAY_CAP,
                                    max(0.0, float(exc.retry_after)))
                    except ValueError:
                        pass
                time.sleep(delay)
        raise last_error  # pragma: no cover - loop always returns/raises

    def _request(self, body, duration_s, attempt):
        parsed = urllib.parse.urlsplit(self.config.base_url)
        path = parsed.path.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "ai-desktop-robot/0.1",
        }
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
                raise CloudASRError(
                    "timeout", "qwen3-asr-flash request timed out") from None
            except (OSError, http.client.HTTPException) as exc:
                raise CloudASRError(
                    "network_error", type(exc).__name__,
                    retryable=True) from None
        finally:
            connection.close()

        latency_ms = (time.perf_counter() - started) * 1000.0
        status = response.status
        if status != 200:
            detail = _error_detail(raw, self._api_key)
            reason = {
                401: "http_401",
                403: "http_403",
                429: "http_429",
            }.get(status, "http_5xx" if status >= 500 else "http_error")
            raise CloudASRError(
                reason, f"HTTP {status}: {detail}", http_status=status,
                retryable=status in RETRY_STATUS,
                retry_after=response.getheader("Retry-After"))

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CloudASRError("bad_response", "response is not valid JSON",
                                http_status=status) from None
        if not isinstance(payload, dict):
            raise CloudASRError("bad_response", "response is not an object",
                                http_status=status)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise CloudASRError("bad_response", "response has no choices",
                                http_status=status)
        choice = choices[0] if isinstance(choices[0], dict) else None
        message = choice.get("message") if choice else None
        if not isinstance(message, dict):
            raise CloudASRError("bad_response", "choice has no message",
                                http_status=status)
        text = str(message.get("content") or "").strip()
        if not text:
            raise CloudASRError("empty_text",
                                "ASR returned an empty transcript",
                                http_status=status)

        annotations = message.get("annotations")
        language = ""
        emotion = ""
        if isinstance(annotations, list) and annotations:
            first = annotations[0] if isinstance(annotations[0], dict) else {}
            language = str(first.get("language") or "")
            emotion = str(first.get("emotion") or "")

        usage = payload.get("usage")
        clean_usage = {}
        if isinstance(usage, dict):
            for key in ("seconds", "prompt_tokens", "completion_tokens",
                        "total_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    clean_usage[key] = value
            details = usage.get("prompt_tokens_details")
            if isinstance(details, dict):
                audio_tokens = details.get("audio_tokens")
                if isinstance(audio_tokens, int) and audio_tokens >= 0:
                    clean_usage["audio_tokens"] = audio_tokens
        billed_seconds = clean_usage.get("seconds", duration_s)
        return ASRResponse(
            text=text,
            model=str(payload.get("model") or self.config.model),
            language=language,
            emotion=emotion,
            usage=clean_usage,
            request_id=str(payload.get("id") or ""),
            latency_ms=latency_ms,
            http_status=status,
            duration_s=float(billed_seconds),
        )


def transcribe_file(wav_path, config, key_info=None):
    """Convenience wrapper returning a JSON-serializable record."""
    key_info = key_info or load_api_key()
    provider = CloudASRProvider(config, key_info.key)
    started = time.perf_counter()
    response = provider.transcribe(wav_path)
    total_ms = (time.perf_counter() - started) * 1000.0
    cost = estimate_cost_cny(config.base_url, response.duration_s)
    return {
        "status": "success",
        "provider": "qwen3-asr-flash",
        "model": response.model,
        "wav": pathlib.Path(wav_path).name,
        "wav_path": str(wav_path),
        "text": response.text,
        "language": response.language,
        "emotion": response.emotion,
        "duration_s": round(response.duration_s, 3),
        "inference_ms": round(response.latency_ms, 1),
        "total_ms": round(total_ms, 1),
        "http_status": response.http_status,
        "request_id": response.request_id,
        "usage": response.usage,
        "cost_cny_estimate": cost,
        "pricing_snapshot": PRICING_SNAPSHOT,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="使用阿里云百炼 qwen3-asr-flash 识别 16kHz/16bit/单声道 WAV。")
    parser.add_argument("wav", type=pathlib.Path, nargs="+",
                        help="待识别 WAV（可多个，顺序发送，不并发）")
    parser.add_argument("--json", action="store_true",
                        help="每个文件输出一行 JSON 到 stdout")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"OpenAI 兼容 base URL（默认 {DEFAULT_BASE_URL}）")
    parser.add_argument("--language", default="zh",
                        help="语种代码（默认 zh；混语种时传空字符串）")
    parser.add_argument("--itn", action="store_true",
                        help="开启逆文本标准化（默认关闭）")
    parser.add_argument("--context", default="",
                        help=f"system 消息中的背景词表，最多 {MAX_CONTEXT_CHARS} 字")
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    parser.add_argument("--connect-timeout", type=float,
                        default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--read-timeout", type=float,
                        default=DEFAULT_READ_TIMEOUT)
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES,
                        help="429/5xx/网络错误的重试次数（0-3，默认 1）")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    def log(message):
        print(message, file=sys.stderr if args.json else sys.stdout,
              flush=True)

    def emit_error(wav, error):
        record = {
            "status": "error",
            "provider": "qwen3-asr-flash",
            "model": args.model,
            "wav": pathlib.Path(wav).name if wav else "",
            "wav_path": str(wav) if wav else "",
            "text": "",
            "reason": error.reason,
            "error": error.message,
            "http_status": error.http_status,
        }
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            print(f"ERR [{pathlib.Path(wav).name if wav else '-'}]: "
                  f"{error.reason}: {error.message}", file=sys.stderr,
                  flush=True)

    config = ASRConfig(
        model=args.model, base_url=args.base_url, language=args.language,
        enable_itn=args.itn, context=args.context,
        connect_timeout=args.connect_timeout, read_timeout=args.read_timeout,
        max_retries=args.retries)
    try:
        config.validate()
        key_info = load_api_key(args.key_file)
    except CloudASRError as exc:
        emit_error(None, exc)
        return 1
    if key_info.loose_permissions:
        log(f"warning: key file {key_info.source} is readable by others; "
            f"run chmod 600")

    failures = 0
    for wav in args.wav:
        try:
            record = transcribe_file(wav, config, key_info)
        except CloudASRError as exc:
            failures += 1
            emit_error(wav, exc)
            continue
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            cost = record["cost_cny_estimate"]
            cost_text = "unknown" if cost is None else f"{cost:.6f}"
            print(f"{record['wav']}: {record['text']}")
            print(f"  duration={record['duration_s']:.2f}s "
                  f"latency={record['inference_ms']:.1f}ms "
                  f"language={record['language'] or '?'} "
                  f"cost_cny~{cost_text}", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
