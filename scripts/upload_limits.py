#!/usr/bin/env python3
"""Upload rate/daily limits for the robot receiver.

The receiver is meant for a small number of trusted devices, but it is a
network-facing endpoint that can spend DeepSeek/TTS quota. This module keeps
two independent, optional limits:

* a sliding one-minute limit per source IP (burst/abuse control);
* a persistent daily limit across restarts (cost control).

Both default to disabled so local tests and the old LAN workflow are
unchanged. Callers must treat a ``UploadLimitError`` as "reject the upload"
and return 503 rather than silently allowing it.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from collections import deque


class UploadLimitError(Exception):
    """The limiter state could not be read or persisted."""


class UploadLimiter:
    def __init__(self, per_minute=0, daily_limit=0, state_file=None,
                 window_seconds=60.0):
        if per_minute < 0 or daily_limit < 0:
            raise ValueError("limits must not be negative")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.per_minute = per_minute
        self.daily_limit = daily_limit
        self.state_file = pathlib.Path(state_file) if state_file else None
        self.window_seconds = float(window_seconds)
        self._events = {}
        self._lock = threading.Lock()
        self._day = self._today()
        self._count = 0
        if self.daily_limit and self.state_file is not None:
            self._load()

    @staticmethod
    def _today():
        return time.strftime("%Y-%m-%d")

    @property
    def daily_count(self):
        with self._lock:
            return self._count if self._day == self._today() else 0

    def allow(self, ip, now=None):
        """Return (allowed, reason); increments counters only when allowed."""
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            self._roll_day()
            if self.per_minute:
                events = self._events.setdefault(ip or "?", deque())
                while events and now - events[0] >= self.window_seconds:
                    events.popleft()
                if len(events) >= self.per_minute:
                    return False, "rate_limited"
            if self.daily_limit and self._count >= self.daily_limit:
                return False, "daily_limit"

            if self.per_minute:
                self._events.setdefault(ip or "?", deque()).append(now)
            if self.daily_limit:
                self._count += 1
                self._save()
            return True, ""

    def _roll_day(self):
        today = self._today()
        if today != self._day:
            self._day = today
            self._count = 0
            self._save()

    def _load(self):
        path = self.state_file
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UploadLimitError(f"cannot read {path}: {exc}") from None
        if not isinstance(payload, dict):
            raise UploadLimitError(f"{path}: state is not an object")
        day = str(payload.get("date") or "")
        count = payload.get("count")
        if not day or not isinstance(count, int) or count < 0:
            raise UploadLimitError(f"{path}: invalid state")
        if day == self._day:
            self._count = count

    def _save(self):
        path = self.state_file
        if path is None:
            return
        payload = json.dumps({"date": self._day, "count": self._count},
                             separators=(",", ":"))
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload + "\n", encoding="utf-8")
            os.replace(temp, path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise UploadLimitError(f"cannot write {path}: {exc}") from None
