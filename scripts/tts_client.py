#!/usr/bin/env python3
"""Host-side text-to-speech adapter for the desktop robot.

The ESP32 never holds a TTS key and never calls a TTS service. This module
synthesizes one short AI reply on the Ubuntu host, converts it to
16 kHz / 16-bit / mono little-endian PCM (the format played by the robot),
saves a WAV for listening, and records latency, characters and estimated cost.

Providers:
  * edge        Edge TTS, free and unofficial. Good for development/fallback.
  * cosyvoice   Alibaba Cloud Bailian CosyVoice official HTTP API. Default
                model cosyvoice-v3-flash with the system voice longxiaochun_v3;
                returns raw PCM when format=pcm and sample_rate=16000.

The key is read from DASHSCOPE_API_KEY or an ignored file (default
work/dashscope_api_key, mode 600). It is never printed, saved in a record, or
included in an error message. Tests use a local fake server / fake command.

Examples:
    export DASHSCOPE_API_KEY=...       # run in the user's own terminal
    .venv/bin/python scripts/tts_client.py "你好，我是小桌。" --provider edge --play
    .venv/bin/python scripts/tts_client.py "你好，我是小桌。" --provider cosyvoice
"""

from __future__ import annotations

import argparse
import base64
import datetime
import http.client
import json
import os
import pathlib
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
MAX_PCM_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * 60  # 60 s upper bound
MAX_TEXT_CHARS = 300

DEFAULT_PROVIDER = "edge"
DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_EDGE_RATE = "-5%"
DEFAULT_EDGE_PYTHON = "work/tts-venv/bin/python"
DEFAULT_FFMPEG = "ffmpeg"
DEFAULT_COSY_MODEL = "cosyvoice-v3-flash"
DEFAULT_COSY_VOICE = "longxiaochun_v3"
DEFAULT_COSY_BASE_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/"
    "SpeechSynthesizer")
DEFAULT_KEY_FILE = "work/dashscope_api_key"
DEFAULT_OUT_DIR = "work/tts"
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_EDGE_TIMEOUT = 30.0
DEFAULT_FFMPEG_TIMEOUT = 20.0
PRICING_SNAPSHOT = "2026-11-10"
# CNY per 10,000 input characters, from the Bailian model pricing page on
# 2026-11-10. Output audio duration is not billed. These are estimates.
PRICING_CNY_PER_10K = {
    "cosyvoice-v3-flash": 1.0,
    "cosyvoice-v3.5-flash": 0.8,
    "cosyvoice-v3-plus": 2.0,
    "cosyvoice-v3.5-plus": 1.5,
    "cosyvoice-v2": 2.0,
}

# Same trim/fade chain used for the embedded hello_zh asset in experiment 009.
EDGE_FILTER = (
    "silenceremove=start_periods=1:start_duration=0.02:"
    "start_threshold=-50dB,areverse,"
    "silenceremove=start_periods=1:start_duration=0.02:"
    "start_threshold=-50dB,areverse,"
    "afade=t=in:st=0:d=0.01,areverse,afade=t=in:st=0:d=0.01,areverse"
)


class TTSError(Exception):
    """A sanitized failure that never contains the API key."""

    def __init__(self, reason, message="", http_status=None):
        self.reason = reason
        self.message = message
        self.http_status = http_status
        text = reason if not message else f"{reason}: {message}"
        super().__init__(text)


class KeyInfo:
    def __init__(self, key, source, loose_permissions=False):
        self.key = key
        self.source = source
        self.loose_permissions = loose_permissions

    def __repr__(self):
        return (f"KeyInfo(source={self.source!r}, "
                f"loose_permissions={self.loose_permissions})")

    __str__ = __repr__


class TTSConfig:
    def __init__(self, provider=DEFAULT_PROVIDER, voice=None,
                 model=DEFAULT_COSY_MODEL,
                 base_url=DEFAULT_COSY_BASE_URL,
                 key_file=DEFAULT_KEY_FILE,
                 edge_python=DEFAULT_EDGE_PYTHON,
                 edge_rate=DEFAULT_EDGE_RATE,
                 ffmpeg=DEFAULT_FFMPEG,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 read_timeout=DEFAULT_READ_TIMEOUT,
                 edge_timeout=DEFAULT_EDGE_TIMEOUT,
                 ffmpeg_timeout=DEFAULT_FFMPEG_TIMEOUT,
                 max_chars=MAX_TEXT_CHARS, out_dir=DEFAULT_OUT_DIR):
        self.provider = provider
        self.voice = voice or (
            DEFAULT_EDGE_VOICE if provider == "edge" else DEFAULT_COSY_VOICE)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.key_file = key_file
        self.edge_python = edge_python
        self.edge_rate = edge_rate
        self.ffmpeg = ffmpeg
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.edge_timeout = edge_timeout
        self.ffmpeg_timeout = ffmpeg_timeout
        self.max_chars = max_chars
        self.out_dir = pathlib.Path(out_dir)

    def validate(self):
        if self.provider not in ("edge", "cosyvoice"):
            raise TTSError("bad_config",
                           "provider must be edge or cosyvoice")
        if not self.voice:
            raise TTSError("bad_config", "voice must not be empty")
        if not 1 <= self.max_chars <= 1000:
            raise TTSError("bad_config",
                           "max_chars must be between 1 and 1000")
        for name in ("connect_timeout", "read_timeout", "edge_timeout",
                     "ffmpeg_timeout"):
            if getattr(self, name) <= 0:
                raise TTSError("bad_config", f"{name} must be positive")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise TTSError("bad_config", "base_url must be http(s)://host")


class ProviderAudio:
    def __init__(self, pcm, request_id="", characters=None,
                 http_status=None, model="", voice="", cost_cny=None):
        self.pcm = pcm
        self.request_id = request_id
        self.characters = characters
        self.http_status = http_status
        self.model = model
        self.voice = voice
        self.cost_cny = cost_cny


class TTSResult:
    def __init__(self, record, pcm):
        self.record = record
        self.pcm = pcm

    def __getattr__(self, name):
        try:
            return self.record[name]
        except KeyError:
            raise AttributeError(name) from None


def load_api_key(key_file=DEFAULT_KEY_FILE):
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    source = "env:DASHSCOPE_API_KEY"
    if not key:
        path = pathlib.Path(key_file)
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            raise TTSError(
                "missing_api_key",
                f"set DASHSCOPE_API_KEY or write the key to {path} "
                f"(chmod 600)") from None
        source = str(path)
    loose = False
    path = pathlib.Path(key_file)
    if path.exists():
        try:
            loose = bool(stat.S_IMODE(path.stat().st_mode) & 0o077)
        except OSError:
            loose = False
    if not 16 <= len(key) <= 200 or any(
            ord(ch) < 0x21 or ord(ch) > 0x7E for ch in key):
        raise TTSError(
            "invalid_api_key",
            f"key from {source} must be 16-200 printable ASCII characters")
    return KeyInfo(key, source, loose)


def valid_tts_text(text, max_chars=MAX_TEXT_CHARS):
    value = (text or "").strip()
    if not value or len(value) > max_chars:
        return False
    return any(ch.isalnum() for ch in value)


def estimate_cost_cny(model, characters):
    price = PRICING_CNY_PER_10K.get(model)
    if price is None or characters is None:
        return None
    return round(max(0, int(characters)) * price / 10000.0, 6)


def _validate_pcm(data):
    if not data:
        raise TTSError("empty_audio", "provider returned no audio")
    if len(data) % (SAMPLE_WIDTH * CHANNELS) != 0:
        raise TTSError("bad_audio", "PCM byte count is not sample-aligned")
    if len(data) > MAX_PCM_BYTES:
        raise TTSError("audio_too_large",
                       f"PCM is longer than {MAX_PCM_BYTES} bytes")
    return len(data) // (SAMPLE_WIDTH * CHANNELS)


def _pcm_duration_ms(frames):
    return round(frames * 1000.0 / SAMPLE_RATE, 1)


class EdgeTTSProvider:
    name = "edge"

    def __init__(self, config):
        self.config = config

    def synthesize(self, text):
        python = pathlib.Path(self.config.edge_python)
        if not python.exists():
            raise TTSError(
                "edge_unavailable",
                f"{python} not found; create work/tts-venv "
                f"and install edge-tts")
        self.config.out_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(
                prefix=".edge-", dir=str(self.config.out_dir)) as temp:
            temp = pathlib.Path(temp)
            mp3 = temp / "speech.mp3"
            pcm = temp / "speech.pcm"
            command = [
                str(python), "-m", "edge_tts",
                "--voice", self.config.voice,
                f"--rate={self.config.edge_rate}",
                "--text", text,
                "--write-media", str(mp3),
                "--no-progress",
            ]
            try:
                result = subprocess.run(
                    command, cwd=str(ROOT), capture_output=True, text=True,
                    timeout=self.config.edge_timeout)
            except subprocess.TimeoutExpired:
                raise TTSError("timeout", "Edge TTS timed out") from None
            except OSError as exc:
                raise TTSError("edge_unavailable",
                               type(exc).__name__) from None
            if result.returncode != 0 or not mp3.is_file():
                detail = " ".join(
                    (result.stderr or result.stdout or "").split())[:300]
                raise TTSError("edge_error",
                               f"exit={result.returncode} {detail}")

            convert = [
                self.config.ffmpeg, "-v", "error", "-nostdin", "-y",
                "-i", str(mp3), "-af", EDGE_FILTER,
                "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
                "-sample_fmt", "s16", "-f", "s16le", str(pcm),
            ]
            try:
                converted = subprocess.run(
                    convert, cwd=str(ROOT), capture_output=True, text=True,
                    timeout=self.config.ffmpeg_timeout)
            except subprocess.TimeoutExpired:
                raise TTSError("timeout", "ffmpeg timed out") from None
            except OSError as exc:
                raise TTSError("ffmpeg_unavailable",
                               type(exc).__name__) from None
            if converted.returncode != 0 or not pcm.is_file():
                detail = " ".join(
                    (converted.stderr or "").split())[:300]
                raise TTSError("audio_convert_failed",
                               f"exit={converted.returncode} {detail}")
            data = pcm.read_bytes()

        latency_ms = (time.perf_counter() - started) * 1000.0
        _validate_pcm(data)
        return ProviderAudio(
            pcm=data,
            request_id="",
            characters=len(text),
            http_status=None,
            model=f"edge:{self.config.voice}",
            voice=self.config.voice,
            cost_cny=0.0,
        ), latency_ms


class CosyVoiceProvider:
    name = "cosyvoice"

    def __init__(self, config, api_key):
        self.config = config
        self._api_key = api_key

    def synthesize(self, text):
        body = json.dumps({
            "model": self.config.model,
            "input": {
                "text": text,
                "voice": self.config.voice,
                "format": "pcm",
                "sample_rate": SAMPLE_RATE,
            },
        }, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-DashScope-SSE": "enable",
            "User-Agent": "ai-desktop-robot/0.1",
        }
        parsed = urllib.parse.urlsplit(self.config.base_url)
        path = parsed.path or "/"
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
                status = response.status
                if status != 200:
                    raw = response.read(4096)
                    detail = self._error_detail(raw)
                    reason = {
                        401: "http_401",
                        403: "http_403",
                        429: "http_429",
                    }.get(status, "http_5xx" if status >= 500
                          else "http_error")
                    raise TTSError(reason, f"HTTP {status}: {detail}",
                                   http_status=status)
                pcm, request_id, characters, audio_url = self._read_sse(
                    response)
            except socket.timeout:
                raise TTSError("timeout",
                               "CosyVoice request timed out") from None
            except (OSError, http.client.HTTPException) as exc:
                raise TTSError("network_error",
                               type(exc).__name__) from None
        finally:
            connection.close()

        if not pcm and audio_url:
            pcm = self._download(audio_url)
        latency_ms = (time.perf_counter() - started) * 1000.0
        _validate_pcm(pcm)
        return ProviderAudio(
            pcm=pcm,
            request_id=request_id,
            characters=characters if characters is not None else len(text),
            http_status=status,
            model=self.config.model,
            voice=self.config.voice,
            cost_cny=estimate_cost_cny(
                self.config.model,
                characters if characters is not None else len(text)),
        ), latency_ms

    def _read_sse(self, response):
        pcm = bytearray()
        request_id = ""
        characters = None
        audio_url = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                raise TTSError("bad_response",
                               "TTS stream is not valid JSON") from None
            if not isinstance(event, dict):
                continue
            request_id = str(event.get("request_id") or request_id)
            usage = event.get("usage")
            if isinstance(usage, dict) and usage.get("characters") is not None:
                try:
                    characters = int(usage["characters"])
                except (TypeError, ValueError):
                    characters = None
            output = event.get("output")
            if not isinstance(output, dict):
                continue
            audio = output.get("audio")
            if not isinstance(audio, dict):
                continue
            chunk = audio.get("data")
            if chunk:
                try:
                    pcm.extend(base64.b64decode(chunk, validate=True))
                except (ValueError, TypeError):
                    raise TTSError("bad_response",
                                   "TTS audio chunk is not valid base64") \
                        from None
                if len(pcm) > MAX_PCM_BYTES:
                    raise TTSError("audio_too_large",
                                   "TTS stream exceeded the size limit")
            if audio.get("url") and not audio_url:
                audio_url = str(audio["url"])
        return bytes(pcm), request_id, characters, audio_url

    def _download(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise TTSError("bad_response", "audio URL is not http(s)")
        request = urllib.request.Request(
            url, headers={"User-Agent": "ai-desktop-robot/0.1"})
        try:
            with urllib.request.urlopen(
                    request, timeout=self.config.read_timeout) as response:
                data = response.read(MAX_PCM_BYTES + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise TTSError("network_error",
                           f"audio download: {type(exc).__name__}") from None
        if len(data) > MAX_PCM_BYTES:
            raise TTSError("audio_too_large", "downloaded audio is too large")
        return data

    def _error_detail(self, raw, limit=300):
        text = ""
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                text = str(payload.get("message")
                           or payload.get("code") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        if not text:
            text = raw.decode("utf-8", "replace")
        text = " ".join(text.split())[:limit]
        return text.replace(self._api_key, "[redacted]")


def make_provider(config):
    config.validate()
    if config.provider == "edge":
        return EdgeTTSProvider(config)
    key_info = load_api_key(config.key_file)
    if key_info.loose_permissions:
        print(f"[tts] warning: {key_info.source} is readable by group/others",
              file=sys.stderr, flush=True)
    return CosyVoiceProvider(config, key_info.key)


def synthesize(text, config):
    config.validate()
    value = (text or "").strip()
    if not valid_tts_text(value, config.max_chars):
        raise TTSError("invalid_text",
                       "text is empty, punctuation-only, or too long")
    provider = make_provider(config)
    started_wall = time.time()
    audio, latency_ms = provider.synthesize(value)
    frames = _validate_pcm(audio.pcm)
    characters = (audio.characters if audio.characters is not None
                  else len(value))
    cost = audio.cost_cny
    if cost is None:
        cost = estimate_cost_cny(config.model, characters)
    record = {
        "status": "success",
        "provider": config.provider,
        "model": audio.model or config.model,
        "voice": audio.voice or config.voice,
        "text": value,
        "characters": characters,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "sample_width": SAMPLE_WIDTH,
        "pcm_bytes": len(audio.pcm),
        "frames": frames,
        "duration_ms": _pcm_duration_ms(frames),
        "latency_ms": round(latency_ms, 1),
        "http_status": audio.http_status,
        "request_id": audio.request_id,
        "cost_cny": cost,
        "pricing_snapshot": PRICING_SNAPSHOT,
        "started_at": datetime.datetime.fromtimestamp(
            started_wall).astimezone().isoformat(timespec="seconds"),
        "finished_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
    }
    record["total_ms"] = round(
        (time.time() - started_wall) * 1000.0, 1)
    return _save_result(audio.pcm, record, config)


def _save_result(pcm, record, config):
    out_dir = config.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "tts-" + time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()
    pcm_path = out_dir / f"{stem}.pcm"
    wav_path = out_dir / f"{stem}.wav"
    json_path = out_dir / f"{stem}.json"
    try:
        _atomic_write(pcm_path, pcm)
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)
        record["pcm_path"] = _relative(pcm_path)
        record["wav_path"] = _relative(wav_path)
        record["record_file"] = _relative(json_path)
        _atomic_write(
            json_path,
            (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"))
    except OSError as exc:
        raise TTSError("write_failed", type(exc).__name__) from None
    return TTSResult(record, pcm)


def _atomic_write(path, data):
    temp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _relative(path):
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def play_file(path, timeout=60.0):
    """Play a WAV with aplay; used by the CLI, never by the receiver."""
    try:
        result = subprocess.run(
            ["aplay", "-q", str(path)], capture_output=True, text=True,
            timeout=timeout)
    except FileNotFoundError:
        raise TTSError("aplay_unavailable", "aplay not found") from None
    except subprocess.TimeoutExpired:
        raise TTSError("aplay_timeout", "aplay timed out") from None
    if result.returncode != 0:
        detail = " ".join((result.stderr or "").split())[:200]
        raise TTSError("aplay_failed",
                       f"exit={result.returncode} {detail}")


def print_stats(record):
    cost = record.get("cost_cny")
    cost_text = "unknown" if cost is None else f"¥{cost:.6f}"
    print(
        f"[tts] status=success provider={record['provider']} "
        f"model={record['model']} voice={record['voice']} "
        f"chars={record['characters']} latency_ms={record['latency_ms']} "
        f"total_ms={record['total_ms']} audio_ms={record['duration_ms']} "
        f"pcm_bytes={record['pcm_bytes']} cost={cost_text} "
        f"wav={record['wav_path']}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Synthesize a short reply as 16 kHz mono PCM")
    parser.add_argument("text", nargs="*", help="text to speak")
    parser.add_argument("--provider", choices=("edge", "cosyvoice"),
                        default=DEFAULT_PROVIDER)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--model", default=DEFAULT_COSY_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_COSY_BASE_URL)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    parser.add_argument("--edge-python", default=DEFAULT_EDGE_PYTHON)
    parser.add_argument("--edge-rate", default=DEFAULT_EDGE_RATE)
    parser.add_argument("--ffmpeg", default=DEFAULT_FFMPEG)
    parser.add_argument("--connect-timeout", type=float,
                        default=DEFAULT_CONNECT_TIMEOUT)
    parser.add_argument("--read-timeout", type=float,
                        default=DEFAULT_READ_TIMEOUT)
    parser.add_argument("--max-chars", type=int, default=MAX_TEXT_CHARS)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--play", action="store_true",
                        help="play the result with aplay")
    parser.add_argument("--json", action="store_true",
                        help="print the full record as JSON")
    args = parser.parse_args()

    text = " ".join(args.text).strip()
    if not text:
        parser.error("provide text to synthesize")
    config = TTSConfig(
        provider=args.provider,
        voice=args.voice,
        model=args.model,
        base_url=args.base_url,
        key_file=args.key_file,
        edge_python=args.edge_python,
        edge_rate=args.edge_rate,
        ffmpeg=args.ffmpeg,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        max_chars=args.max_chars,
        out_dir=args.out_dir,
    )
    try:
        result = synthesize(text, config)
    except TTSError as exc:
        print(f"ERR reason={exc.reason} detail={exc.message}",
              file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.record, ensure_ascii=False), flush=True)
    else:
        print_stats(result.record)
    if args.play:
        try:
            play_file(result.record["wav_path"])
        except TTSError as exc:
            print(f"ERR reason={exc.reason} detail={exc.message}",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
