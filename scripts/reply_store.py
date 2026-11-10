#!/usr/bin/env python3
"""Latest TTS reply storage for the ESP32 voice download endpoint.

One reply is a mono 16 kHz / 16-bit PCM file plus metadata. Files are written
to a temporary name and renamed, so an ESP32 GET never sees a partial PCM.
`latest.json` is the only pointer used by the HTTP handler; it is replaced
after the PCM file (and its own JSON) is complete.

Reply IDs come from the accepted upload turn, e.g. 20261110-213501-01. Only
[A-Za-z0-9_-] is accepted, so an ID can never escape the reply directory.
"""

import datetime
import json
import os
import pathlib
import re
import threading
import zlib

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
MAX_PCM_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * 60  # 60 s upper bound
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
KEEP_REPLIES = 20


class ReplyError(Exception):
    """A reply could not be stored; the message is safe to log."""

    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


def valid_id(reply_id):
    return bool(reply_id) and ID_RE.fullmatch(reply_id) is not None


def validate_pcm(pcm):
    if not pcm:
        raise ReplyError("empty_audio")
    if len(pcm) % SAMPLE_WIDTH != 0:
        raise ReplyError("odd_bytes")
    if len(pcm) > MAX_PCM_BYTES:
        raise ReplyError("too_long")


class ReplyStore:
    def __init__(self, out_dir):
        self.dir = pathlib.Path(out_dir)
        self.lock = threading.Lock()
        self.latest_path = self.dir / "latest.json"

    def publish(self, reply_id, pcm, text, tts_record, wav_bytes=None):
        """Store a reply and make it the latest one. Returns its metadata."""
        if not valid_id(reply_id):
            raise ReplyError("bad_id")
        validate_pcm(pcm)
        crc = zlib.crc32(pcm) & 0xFFFFFFFF
        frames = len(pcm) // SAMPLE_WIDTH
        record = {
            "status": "ready",
            "id": reply_id,
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "sample_width": SAMPLE_WIDTH,
            "pcm_bytes": len(pcm),
            "frames": frames,
            "duration_ms": round(frames * 1000.0 / SAMPLE_RATE, 1),
            "crc32": f"{crc:08x}",
            "text": text,
            "created_at": datetime.datetime.now().astimezone().isoformat(
                timespec="seconds"),
            "pcm": f"reply-{reply_id}.pcm",
            "wav": f"reply-{reply_id}.wav" if wav_bytes else None,
            "tts": tts_record,
        }
        pcm_name = self.dir / record["pcm"]
        json_name = self.dir / f"reply-{reply_id}.json"
        try:
            with self.lock:
                self.dir.mkdir(parents=True, exist_ok=True)
                self._atomic_write(pcm_name, pcm)
                if wav_bytes:
                    self._atomic_write(self.dir / record["wav"], wav_bytes)
                self._atomic_write(
                    json_name,
                    (json.dumps(record, ensure_ascii=False, indent=2)
                     + "\n").encode("utf-8"))
                self._atomic_write(
                    self.latest_path,
                    (json.dumps(record, ensure_ascii=False, indent=2)
                     + "\n").encode("utf-8"))
            self._prune()
        except OSError as exc:
            raise ReplyError("write_failed", f"{type(exc).__name__}: {exc}")
        return record

    def get(self, reply_id=None):
        """Return metadata for one reply, or the latest, if it is intact."""
        with self.lock:
            if reply_id is not None:
                if not valid_id(reply_id):
                    return None
                path = self.dir / f"reply-{reply_id}.json"
            else:
                path = self.latest_path
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(record, dict) or record.get("status") != "ready":
                return None
            if not valid_id(record.get("id")):
                return None
            pcm_path = self.dir / f"reply-{record['id']}.pcm"
            try:
                if pcm_path.stat().st_size != record.get("pcm_bytes"):
                    return None
            except OSError:
                return None
            result = dict(record)
            result["pcm_path"] = pcm_path
            return result

    def _atomic_write(self, path, data):
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temp.write_bytes(data)
            os.replace(temp, path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _prune(self):
        """Keep the newest replies; failures here must not fail the publish."""
        try:
            files = sorted(self.dir.glob("reply-*.pcm"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return
        for old in files[KEEP_REPLIES:]:
            stem = old.stem
            for suffix in (".pcm", ".wav", ".json"):
                try:
                    (self.dir / f"{stem}{suffix}").unlink(missing_ok=True)
                except OSError:
                    pass
