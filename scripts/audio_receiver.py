#!/usr/bin/env python3
"""Receive one ESP32 PCM upload over the trusted LAN, save it, then run ASR.

The ESP32 runs experiment 013 and sends a binary POST only after an explicit
`mic upload` command. This server validates the token, length, format headers
and CRC-32 before writing anything, so a rejected request never leaves a WAV
and never starts recognition.

After a valid WAV is written, a single background worker runs the existing
`scripts/asr_local.py --json` in a subprocess (one model at a time) and stores
the result under work/asr/. If a chat session is enabled, the recognized text
is then sent to DeepSeek through scripts/llm_client.py and the user/AI lines
plus a session record (ID, latency, tokens, cost, status) are written under
work/sessions/. The HTTP response is sent before either model runs, because
model loading takes seconds and the ESP32 response timeout is five seconds.

Run after generating the shared token (the file is ignored by Git):

    openssl rand -hex 16 > work/audio_upload_token
    chmod 600 work/audio_upload_token
    umask 077
    read -rsp 'DeepSeek API key: ' key; echo
    printf '%s\\n' "$key" > work/deepseek_api_key; unset key
    .venv/bin/python scripts/audio_receiver.py

The token must also be set as AUDIO_UPLOAD_TOKEN in the ignored src/secrets.h.
The DeepSeek key can also come from DEEPSEEK_API_KEY; use --no-llm to keep the
receiver ASR-only. Use this only on a trusted home LAN; never forward the port
from the internet.
"""

import argparse
import array
import datetime
import hmac
import json
import math
import os
import pathlib
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import wave
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

from llm_client import (ChatSession, DeepSeekProvider, LLMConfig, LLMError,
                        load_api_key, valid_user_text, DEFAULT_BASE_URL,
                        DEFAULT_KEY_FILE, DEFAULT_MAX_TOKENS, DEFAULT_MODEL)

SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES = 160000
EXPECTED_BYTES = FRAMES * 2
DEFAULT_TOKEN_FILE = "work/audio_upload_token"
DEFAULT_OUT_DIR = "work/audio"
DEFAULT_ASR_DIR = "work/asr"
DEFAULT_ASR_PYTHON = "work/asr-venv/bin/python"
DEFAULT_ASR_SCRIPT = "scripts/asr_local.py"
DEFAULT_SESSION_DIR = "work/sessions"
CRC_RE = re.compile(r"[0-9a-fA-F]{8}")
FORMAT_HEADERS = {
    "Content-Type": "application/octet-stream",
    "X-Audio-Format": "s16le",
    "X-Sample-Rate": str(SAMPLE_RATE),
    "X-Channels": str(CHANNELS),
    "X-Frames": str(FRAMES),
}

# Baseline silence gate. Formal VAD is left for a later experiment; these
# values only prevent an empty/very quiet recording from being reported as a
# successful recognition. The high-pass removes the INMP441 DC/low-frequency
# drift, which otherwise makes a silent recording look loud.
ASR_HP_HZ = 200.0
ASR_FRAME_MS = 10
ASR_ACTIVE_PCT = 0.3
ASR_ACTIVE_MIN_MS = 200
ASR_PEAK_MIN_PCT = 1.0


def load_token(path):
    try:
        token = pathlib.Path(path).read_text().strip()
    except OSError as error:
        raise SystemExit(f"cannot read token file {path}: {error}")
    if not 16 <= len(token) <= 64 or any(
        ord(ch) < 0x21 or ord(ch) > 0x7E for ch in token
    ):
        raise SystemExit(
            f"token file {path} must contain 16-64 printable ASCII characters"
        )
    return token


def analyze_pcm(data, config):
    """Return high-passed level metrics and a basic silence decision."""
    samples = array.array("h")
    usable = len(data) - (len(data) % 2)
    samples.frombytes(data[:usable])
    if sys.byteorder != "little":
        samples.byteswap()

    if not samples:
        return {"peak_pct": 0.0, "hp_rms_pct": 0.0, "active_ms": 0,
                "silent": True}

    total = len(samples)
    mean = sum(samples) / float(total)
    coeff = math.exp(-2.0 * math.pi * ASR_HP_HZ / SAMPLE_RATE)
    frame_len = SAMPLE_RATE * ASR_FRAME_MS // 1000
    threshold = config.active_pct / 100.0 * 32768.0

    prev = 0.0
    px = 0.0
    frame_acc = 0.0
    frame_count = 0
    total_acc = 0.0
    peak = 0.0
    active_frames = 0

    for raw in samples:
        value = raw - mean
        prev = coeff * (prev + value - px)
        px = value
        magnitude = abs(prev)
        if magnitude > peak:
            peak = magnitude
        square = prev * prev
        frame_acc += square
        total_acc += square
        frame_count += 1
        if frame_count == frame_len:
            if math.sqrt(frame_acc / frame_len) > threshold:
                active_frames += 1
            frame_acc = 0.0
            frame_count = 0

    if frame_count:
        if math.sqrt(frame_acc / frame_count) > threshold:
            active_frames += 1

    peak_pct = peak / 32768.0 * 100.0
    hp_rms_pct = math.sqrt(total_acc / total) / 32768.0 * 100.0
    active_ms = active_frames * ASR_FRAME_MS
    silent = (peak_pct < config.peak_pct
              or active_ms < config.min_active_ms)
    return {
        "peak_pct": round(peak_pct, 2),
        "hp_rms_pct": round(hp_rms_pct, 3),
        "active_ms": active_ms,
        "silent": silent,
    }


class AsrConfig:
    def __init__(self, python, script, out_dir, queue_max, timeout,
                 shutdown_timeout, min_active_ms, active_pct, peak_pct):
        self.python = pathlib.Path(python)
        self.script = pathlib.Path(script)
        self.out_dir = pathlib.Path(out_dir)
        self.queue_max = queue_max
        self.timeout = timeout
        self.shutdown_timeout = shutdown_timeout
        self.min_active_ms = min_active_ms
        self.active_pct = active_pct
        self.peak_pct = peak_pct


class AsrPipeline:
    """One worker, a bounded queue, and result JSON files next to the WAVs.

    When a ChatSession is attached, a successful recognition is followed by
    one LLM turn on the same worker. The HTTP reply was already sent, so a
    slow API answer never delays the ESP32.
    """

    def __init__(self, config, chat=None):
        self.config = config
        self.chat = chat
        self.root = pathlib.Path(__file__).resolve().parent.parent
        self.queue = queue.Queue(maxsize=config.queue_max)
        self.worker = None
        self.lock = threading.Lock()
        self.counts = {"success": 0, "error": 0, "skipped": 0}

    def start(self):
        self.worker = threading.Thread(target=self._run, name="asr-worker",
                                       daemon=True)
        self.worker.start()

    def submit(self, job):
        if self.worker is None:
            return False
        try:
            self.queue.put_nowait(job)
        except queue.Full:
            self._record_skip(job, "queue_full")
            return False
        return True

    def process_existing(self, path):
        job = {"name": path.name, "path": path}
        try:
            return self._process(job)
        except Exception as exc:  # keep the same failure contract as the worker
            name = path.name
            self._record(job, {
                "wav": name,
                "status": "error",
                "reason": f"worker_error:{type(exc).__name__}",
                "error": str(exc),
                "text": "",
            })
            print(f"[asr] status=error reason=worker_error file={name}",
                  flush=True)
            return "error"

    def stop(self):
        if self.worker is None:
            return
        # Put the sentinel after all queued jobs so a graceful shutdown drains
        # work that was already accepted. This can wait for the current model
        # load/inference; each subprocess also has a hard timeout.
        while True:
            try:
                self.queue.put(None, timeout=1.0)
                break
            except queue.Full:
                continue
        self.worker.join(timeout=self.config.shutdown_timeout)
        if self.worker.is_alive():
            print(f"[asr] shutdown_timeout pending={self.queue.qsize()}",
                  flush=True)
        print(f"[asr] stopped success={self.counts['success']} "
              f"error={self.counts['error']} "
              f"skipped={self.counts['skipped']}", flush=True)

    def _run(self):
        while True:
            job = self.queue.get()
            try:
                if job is None:
                    break
                self._process(job)
            except Exception as exc:
                name = job.get("name", "?") if isinstance(job, dict) else "?"
                print(f"[asr] status=error reason=worker_error "
                      f"detail={type(exc).__name__} file={name}", flush=True)
            finally:
                self.queue.task_done()

    def _process(self, job):
        path = pathlib.Path(job["path"])
        name = job["name"]
        started_wall = time.time()
        started = time.perf_counter()
        print(f"[asr] processing file={name}", flush=True)

        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            data = wav.readframes(frames)

        metrics = analyze_pcm(data, self.config)
        crc = job.get("crc") or f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"
        base = {
            "wav": name,
            "wav_path": self._relative(path),
            "wav_bytes": len(data),
            "wav_crc32": crc,
            "audio": {key: metrics[key] for key in
                      ("peak_pct", "hp_rms_pct", "active_ms")},
        }
        print(f"[asr] audio file={name} peak_pct={metrics['peak_pct']} "
              f"hp_rms_pct={metrics['hp_rms_pct']} "
              f"active_ms={metrics['active_ms']}", flush=True)

        if metrics["silent"]:
            self._record(job, {**base, "status": "skipped",
                               "reason": "silent", "text": ""},
                         started_wall, started)
            print(f"[asr] skipped file={name} reason=silent "
                  f"active_ms={metrics['active_ms']}", flush=True)
            return "skipped"

        command = [str(self.config.python), str(self.config.script),
                   "--json", str(path)]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)  # ROS may poison the ASR virtualenv
        try:
            result = subprocess.run(
                command, cwd=str(self.root), env=env,
                capture_output=True, text=True,
                timeout=self.config.timeout)
        except subprocess.TimeoutExpired:
            self._record(job, {**base, "status": "error",
                               "reason": "timeout", "text": ""},
                         started_wall, started)
            print(f"[asr] status=error reason=timeout file={name}", flush=True)
            return "error"
        except OSError as exc:
            self._record(job, {**base, "status": "error",
                               "reason": "asr_command_failed",
                               "error": str(exc), "text": ""},
                         started_wall, started)
            print(f"[asr] status=error reason=asr_command_failed file={name}",
                  flush=True)
            return "error"

        payload = self._parse_json(result.stdout)
        if (result.returncode == 0 and payload
                and payload.get("status") == "success"
                and str(payload.get("text", "")).strip()):
            record = {
                **base,
                "status": "success",
                "text": str(payload["text"]).strip(),
                "inference_ms": payload.get("inference_ms"),
                "model_load_ms": payload.get("model_load_ms"),
                "rtf": payload.get("rtf"),
                "peak_rss_mb": payload.get("peak_rss_mb"),
                "duration_s": payload.get("duration_s"),
            }
            self._record(job, record, started_wall, started)
            print(f"[asr] text={record['text']}", flush=True)
            print(f"[asr] inference_ms={record['inference_ms']} "
                  f"status=success file={name}", flush=True)
            self._chat(name, record["text"], path)
            return "success"

        if payload and payload.get("status") == "error":
            reason = payload.get("reason") or "asr_error"
            error = payload.get("error") or ""
        else:
            reason = f"exit_{result.returncode}"
            error = self._tail(result.stderr)
        record = {**base, "status": "error", "reason": reason,
                  "error": error, "text": ""}
        self._record(job, record, started_wall, started)
        print(f"[asr] status=error reason={reason} file={name}", flush=True)
        return "error"

    def _chat(self, name, text, path):
        if self.chat is None:
            return
        if not valid_user_text(text):
            print(f"[chat] skipped file={name} reason=invalid_text",
                  flush=True)
            return
        print(f"[chat] user={text}", flush=True)
        record = self.chat.ask(text, meta={
            "wav": name,
            "wav_path": self._relative(path),
        })
        if record["status"] == "success":
            print(f"[chat] ai={record['reply_text']}", flush=True)
            usage = record.get("usage") or {}
            cost = record.get("cost_usd")
            cost_text = "unknown" if cost is None else f"{cost:.6f}"
            print(f"[chat] status=success latency_ms={record['latency_ms']} "
                  f"prompt_tokens={usage.get('prompt_tokens', '?')} "
                  f"completion_tokens={usage.get('completion_tokens', '?')} "
                  f"total_tokens={usage.get('total_tokens', '?')} "
                  f"cost_usd={cost_text} "
                  f"session={record['session_id']} turn={record['turn']}",
                  flush=True)
        else:
            print(f"[chat] status=error reason={record['reason']} "
                  f"file={name}", flush=True)

    def _record_skip(self, job, reason):
        name = job.get("name", "?")
        path = pathlib.Path(job["path"])
        record = {
            "wav": name,
            "wav_path": self._relative(path),
            "status": "skipped",
            "reason": reason,
            "text": "",
        }
        self._record(job, record, time.time(), time.perf_counter())
        print(f"[asr] skipped file={name} reason={reason}", flush=True)

    def _record(self, job, record, started_wall, started):
        record.setdefault("wav", job.get("name", "?"))
        record.setdefault("wav_path", self._relative(job["path"]))
        record["started_at"] = datetime.datetime.fromtimestamp(
            started_wall).astimezone().isoformat(timespec="seconds")
        record["finished_at"] = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        record["elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000.0, 1)

        status = record.get("status", "error")
        with self.lock:
            if status in self.counts:
                self.counts[status] += 1

        stem = pathlib.Path(record["wav"]).stem
        final = self.config.out_dir / f"{stem}.json"
        temp = self.config.out_dir / f".{stem}.{os.getpid()}.tmp"
        try:
            self.config.out_dir.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(record, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
            os.replace(temp, final)
        except OSError as exc:
            print(f"[asr] result_write_failed file={final} "
                  f"error={type(exc).__name__}", flush=True)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _relative(self, path):
        try:
            return str(pathlib.Path(path).resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    @staticmethod
    def _parse_json(text):
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "status" in payload:
                return payload
        return None

    @staticmethod
    def _tail(text, limit=500):
        lines = [line for line in text.splitlines() if line.strip()]
        return "\n".join(lines)[-limit:]


class Receiver(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, token, out_dir, max_uploads, header_timeout,
                 asr):
        super().__init__(address, Handler)
        self.token = token
        self.out_dir = pathlib.Path(out_dir)
        self.max_uploads = max_uploads
        self.header_timeout = header_timeout
        self.asr = asr
        self.uploads = 0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DeskRobotAudio/1.1"

    def setup(self):
        super().setup()
        # Bound header parsing too: a client that connects and never sends a
        # request must not wedge this single-threaded receiver.
        self.connection.settimeout(self.server.header_timeout)

    # Never use the default logger: it writes a line for every request and is
    # not needed here. Our own messages never include the token.
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        return

    def _log(self, text):
        print(f"[receiver] {text}", flush=True)

    def _reply(self, code, text):
        body = text.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, "OK")
        elif self.path == "/upload":
            self._reply(405, "ERR method_not_allowed")
        else:
            self._reply(404, "ERR not_found")

    def do_POST(self):
        if self.path != "/upload":
            self._reply(404, "ERR not_found")
            return

        token = self.headers.get("X-Auth-Token", "")
        if not token:
            self._log("reject missing_token")
            self._reply(401, "ERR missing_token")
            return
        if not hmac.compare_digest(token, self.server.token):
            self._log(f"reject invalid_token remote={self.client_address[0]}")
            self._reply(403, "ERR invalid_token")
            return

        length_text = self.headers.get("Content-Length")
        try:
            length = int(length_text)
        except (TypeError, ValueError):
            self._log("reject bad_length")
            self._reply(400, "ERR bad_length")
            return
        if length != EXPECTED_BYTES:
            self._log(f"reject length={length} expected={EXPECTED_BYTES}")
            self._reply(413 if length > EXPECTED_BYTES else 400,
                        "ERR bad_length")
            return

        for name, expected in FORMAT_HEADERS.items():
            actual = (self.headers.get(name) or "").strip()
            if actual.lower() != expected.lower():
                self._log(f"reject header={name} value={actual!r}")
                self._reply(400, "ERR bad_format")
                return

        crc_text = (self.headers.get("X-Crc32") or "").strip()
        if not CRC_RE.fullmatch(crc_text):
            self._log("reject bad_crc_header")
            self._reply(400, "ERR bad_crc")
            return

        # Bound the body read so a stalled sender cannot hold the server open.
        self.connection.settimeout(10.0)
        try:
            data = self.rfile.read(length)
        except (socket.timeout, OSError) as error:
            self._log(f"reject body_read remote={self.client_address[0]} "
                      f"error={type(error).__name__}")
            self._reply(408, "ERR body_read")
            return
        if len(data) != length:
            self._log(f"reject short_body got={len(data)} expected={length}")
            self._reply(400, "ERR short_body")
            return

        crc = zlib.crc32(data) & 0xFFFFFFFF
        if f"{crc:08x}" != crc_text.lower():
            self._log(f"reject crc got={crc:08x} header={crc_text.lower()}")
            self._reply(422, "ERR bad_crc")
            return

        name = self._write_wav(data)
        if name is None:
            self._reply(500, "ERR write_failed")
            return

        self.server.uploads += 1
        self._log(f"ok remote={self.client_address[0]} bytes={length} "
                  f"crc32={crc:08x} file={name} count={self.server.uploads}")

        # Enqueue before replying so --once cannot shut down between the
        # response and the job hand-off. Recognition runs on the worker; the
        # reply itself never waits for the model.
        if self.server.asr is not None:
            self.server.asr.submit({
                "name": name,
                "path": self.server.out_dir / name,
                "crc": f"{crc:08x}",
            })

        self._reply(200, f"OK bytes={length} frames={FRAMES} crc32={crc:08x} "
                         f"file={name}")
        if (self.server.max_uploads
                and self.server.uploads >= self.server.max_uploads):
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _write_wav(self, data):
        out_dir = self.server.out_dir
        temp = None
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = out_dir / f"mic-{stamp}.wav"
            index = 1
            while path.exists():
                path = out_dir / f"mic-{stamp}-{index}.wav"
                index += 1
            temp = out_dir / f".upload-{os.getpid()}.tmp"
            with wave.open(str(temp), "wb") as wav:
                wav.setnchannels(CHANNELS)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(data)
            os.replace(temp, path)
            return path.name
        except OSError as error:
            print(f"[receiver] write failed: {error}", flush=True)
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
            return None


def parse_asr_config(args, parser):
    if args.asr_queue < 1:
        parser.error("--asr-queue must be at least 1")
    if args.asr_timeout <= 0 or args.asr_shutdown_timeout <= 0:
        parser.error("ASR timeouts must be positive")
    if args.asr_min_active_ms < 0 or args.asr_active_pct < 0 \
            or args.asr_peak_pct < 0:
        parser.error("ASR silence thresholds must not be negative")
    return AsrConfig(
        python=args.asr_python,
        script=args.asr_script,
        out_dir=args.asr_dir,
        queue_max=args.asr_queue,
        timeout=args.asr_timeout,
        shutdown_timeout=args.asr_shutdown_timeout,
        min_active_ms=args.asr_min_active_ms,
        active_pct=args.asr_active_pct,
        peak_pct=args.asr_peak_pct,
    )


def build_chat(args):
    """Return a ChatSession, or None with a clear reason when disabled."""
    if args.no_llm:
        return None
    try:
        key_info = load_api_key(args.llm_key_file)
    except LLMError as exc:
        print(f"[llm] disabled reason={exc.reason} detail={exc.message}",
              flush=True)
        return None
    if key_info.loose_permissions:
        print(f"[llm] warning key_source={key_info.source} is readable by "
              f"group/others", flush=True)
    try:
        provider = DeepSeekProvider(LLMConfig(
            model=args.llm_model,
            base_url=args.llm_base_url,
            max_tokens=args.llm_max_tokens,
            temperature=args.llm_temperature,
            connect_timeout=args.llm_connect_timeout,
            read_timeout=args.llm_read_timeout,
        ), key_info.key)
        chat = ChatSession(
            provider,
            max_turns=args.llm_history_turns,
            max_context_chars=args.llm_max_context_chars,
            session_dir=args.llm_session_dir,
        )
    except LLMError as exc:
        print(f"[llm] disabled reason={exc.reason} detail={exc.message}",
              flush=True)
        return None
    print(f"[llm] enabled provider=deepseek model={args.llm_model} "
          f"thinking=disabled max_tokens={args.llm_max_tokens} "
          f"history_turns={args.llm_history_turns} "
          f"key_source={key_info.source}", flush=True)
    return chat


def main():
    parser = argparse.ArgumentParser(
        description="Receive a 10 s PCM upload, save a WAV, then run local ASR "
                    "followed by a DeepSeek reply")
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address (default: 0.0.0.0, trusted LAN only)")
    parser.add_argument("--port", type=int, default=8080,
                        help="TCP port (default: 8080; the ESP32 web UI keeps 80)")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE,
                        help=f"shared token file (default: {DEFAULT_TOKEN_FILE})")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                        help=f"WAV output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--header-timeout", type=float, default=10.0,
                        help="seconds to wait for request headers (default: 10)")
    parser.add_argument("--max-uploads", type=int, default=0,
                        help="exit after N accepted uploads (0 = unlimited)")
    parser.add_argument("--once", action="store_true",
                        help="same as --max-uploads 1")
    parser.add_argument("--no-asr", action="store_true",
                        help="receive and save WAVs without starting recognition")
    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR,
                        help=f"ASR result directory (default: {DEFAULT_ASR_DIR})")
    parser.add_argument("--asr-python", default=DEFAULT_ASR_PYTHON,
                        help=f"ASR virtualenv Python (default: {DEFAULT_ASR_PYTHON})")
    parser.add_argument("--asr-script", default=DEFAULT_ASR_SCRIPT,
                        help=f"ASR script (default: {DEFAULT_ASR_SCRIPT})")
    parser.add_argument("--asr-queue", type=int, default=2,
                        help="maximum queued ASR jobs, excluding the running one "
                             "(default: 2)")
    parser.add_argument("--asr-timeout", type=float, default=120.0,
                        help="seconds allowed per ASR subprocess (default: 120)")
    parser.add_argument("--asr-shutdown-timeout", type=float, default=300.0,
                        help="seconds to wait for the worker on shutdown "
                             "(default: 300)")
    parser.add_argument("--asr-min-active-ms", type=int,
                        default=ASR_ACTIVE_MIN_MS,
                        help=f"minimum high-passed active audio to run ASR "
                             f"(default: {ASR_ACTIVE_MIN_MS} ms)")
    parser.add_argument("--asr-active-pct", type=float, default=ASR_ACTIVE_PCT,
                        help=f"high-passed 10 ms frame threshold "
                             f"(default: {ASR_ACTIVE_PCT}%% full scale)")
    parser.add_argument("--asr-peak-pct", type=float, default=ASR_PEAK_MIN_PCT,
                        help=f"minimum high-passed peak to run ASR "
                             f"(default: {ASR_PEAK_MIN_PCT}%% full scale)")
    parser.add_argument("--no-llm", action="store_true",
                        help="run ASR without calling the chat API")
    parser.add_argument("--llm-key-file", default=DEFAULT_KEY_FILE,
                        help=f"ignored API key file (default: {DEFAULT_KEY_FILE})")
    parser.add_argument("--llm-model", default=DEFAULT_MODEL,
                        help=f"chat model (default: {DEFAULT_MODEL})")
    parser.add_argument("--llm-base-url", default=DEFAULT_BASE_URL,
                        help=f"OpenAI-compatible base URL "
                             f"(default: {DEFAULT_BASE_URL})")
    parser.add_argument("--llm-max-tokens", type=int,
                        default=DEFAULT_MAX_TOKENS,
                        help=f"reply token limit (default: {DEFAULT_MAX_TOKENS})")
    parser.add_argument("--llm-temperature", type=float, default=0.7,
                        help="reply temperature (default: 0.7)")
    parser.add_argument("--llm-connect-timeout", type=float, default=5.0,
                        help="API connect timeout in seconds (default: 5)")
    parser.add_argument("--llm-read-timeout", type=float, default=30.0,
                        help="API read timeout in seconds (default: 30)")
    parser.add_argument("--llm-history-turns", type=int, default=6,
                        help="previous user/assistant pairs kept in context "
                             "(default: 6)")
    parser.add_argument("--llm-max-context-chars", type=int, default=4000,
                        help="maximum history characters sent to the API "
                             "(default: 4000)")
    parser.add_argument("--llm-session-dir", default=DEFAULT_SESSION_DIR,
                        help=f"chat turn records (default: {DEFAULT_SESSION_DIR})")
    parser.add_argument("--process-wav", type=pathlib.Path,
                        help="run the ASR pipeline on an existing WAV and exit "
                             "(offline test, no HTTP server)")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if args.header_timeout <= 0:
        raise SystemExit("header timeout must be positive")
    if not 1 <= args.llm_max_tokens <= 8192:
        parser.error("--llm-max-tokens must be between 1 and 8192")
    if args.llm_connect_timeout <= 0 or args.llm_read_timeout <= 0:
        parser.error("LLM timeouts must be positive")
    if args.llm_history_turns < 0:
        parser.error("--llm-history-turns must not be negative")
    if args.llm_max_context_chars < 100:
        parser.error("--llm-max-context-chars must be at least 100")
    asr_config = parse_asr_config(args, parser)
    chat = build_chat(args)

    if args.process_wav is not None:
        path = args.process_wav
        if not path.is_file():
            raise SystemExit(f"WAV not found: {path}")
        pipeline = AsrPipeline(asr_config, chat)
        status = pipeline.process_existing(path)
        print(f"[asr] stopped success={pipeline.counts['success']} "
              f"error={pipeline.counts['error']} "
              f"skipped={pipeline.counts['skipped']}", flush=True)
        return 0 if status == "success" else 1

    max_uploads = 1 if args.once else args.max_uploads
    token = load_token(args.token_file)

    asr = None
    if not args.no_asr:
        asr = AsrPipeline(asr_config, chat)
        asr.start()
    elif chat is not None:
        print("[llm] disabled reason=asr_off", flush=True)
        chat = None

    server = Receiver((args.host, args.port), token, args.out_dir, max_uploads,
                      args.header_timeout, asr)
    print(f"[receiver] listening host={args.host} port={args.port} "
          f"out={args.out_dir} max_uploads={max_uploads or 'unlimited'} "
          f"asr={'off' if asr is None else 'on'} "
          f"queue={0 if asr is None else asr_config.queue_max} "
          f"llm={'off' if chat is None else 'on'}; "
          f"trusted LAN only", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("[receiver] interrupted", flush=True)
    finally:
        if asr is not None:
            asr.stop()
        server.server_close()
        print(f"[receiver] stopped uploads={server.uploads}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
