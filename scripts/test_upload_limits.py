#!/usr/bin/env python3
"""Tests for scripts/upload_limits.py (no network)."""

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from upload_limits import UploadLimiter, UploadLimitError  # noqa: E402

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


print("[1] disabled by default")
limiter = UploadLimiter()
check("allow_1", limiter.allow("a", now=1000), (True, ""))
check("allow_2", limiter.allow("a", now=1001), (True, ""))
check("count", limiter.daily_count, 0)

print("[2] per-minute sliding window")
limiter = UploadLimiter(per_minute=2)
check("first", limiter.allow("a", now=1000), (True, ""))
check("second", limiter.allow("a", now=1001), (True, ""))
check("third_limited", limiter.allow("a", now=1002),
      (False, "rate_limited"))
check("other_ip", limiter.allow("b", now=1002), (True, ""))
check("window_expired", limiter.allow("a", now=1060), (True, ""))
check("window_second", limiter.allow("a", now=1061), (True, ""))
check("window_still_limited", limiter.allow("a", now=1062),
      (False, "rate_limited"))

print("[3] daily limit and persistence")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="upload-limits-"))
state = tmp / "usage.json"
limiter = UploadLimiter(daily_limit=2, state_file=state)
check("day_first", limiter.allow("a", now=1000), (True, ""))
check("day_second", limiter.allow("b", now=1001), (True, ""))
check("day_third", limiter.allow("c", now=1002), (False, "daily_limit"))
check("day_count", limiter.daily_count, 2)
saved = json.loads(state.read_text())
check("state_count", saved["count"], 2)
check("state_date_len", len(saved["date"]), 10)
reloaded = UploadLimiter(daily_limit=2, state_file=state)
check("reload_count", reloaded.daily_count, 2)
check("reload_denied", reloaded.allow("d", now=1003), (False, "daily_limit"))

print("[4] date rollover")
state.write_text(json.dumps({"date": "2000-01-01", "count": 99}))
rolled = UploadLimiter(daily_limit=2, state_file=state)
check("old_date_ignored", rolled.daily_count, 0)
check("rollover_allows", rolled.allow("a", now=1004), (True, ""))
check("rollover_count", rolled.daily_count, 1)
saved = json.loads(state.read_text())
check("rollover_saved_count", saved["count"], 1)

print("[5] denied attempts do not consume daily quota")
limiter = UploadLimiter(per_minute=1, daily_limit=2, state_file=tmp / "b.json")
check("first", limiter.allow("a", now=1), (True, ""))
check("rate_denied", limiter.allow("a", now=2), (False, "rate_limited"))
check("daily_after_rate_denied", limiter.daily_count, 1)

print("[6] corrupt state fails closed")
bad = tmp / "bad.json"
bad.write_text("{not json")
try:
    UploadLimiter(daily_limit=1, state_file=bad)
    check("corrupt", "no-error", "error")
except UploadLimitError as exc:
    check("corrupt", True, True)

print("[7] invalid configuration")
for kwargs in ({"per_minute": -1}, {"daily_limit": -1},
               {"window_seconds": 0}):
    try:
        UploadLimiter(**kwargs)
        check("invalid", "no-error", "error")
    except ValueError:
        check("invalid", True, True)

print()
print(f"{'PASS' if failures == 0 else 'FAIL'}: {checks - failures}/"
      f"{checks} checks passed")
sys.exit(0 if failures == 0 else 1)
