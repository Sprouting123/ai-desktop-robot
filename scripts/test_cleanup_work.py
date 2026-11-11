#!/usr/bin/env python3
"""Tests for scripts/cleanup_work.py (temporary directory, no network)."""

import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from cleanup_work import cleanup, collect, latest_is_dangling  # noqa: E402

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


def touch(path, age_days, now):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    stamp = now - age_days * 86400
    os.utime(path, (stamp, stamp))


def names(paths):
    return sorted(str(p).split("/work/", 1)[-1] for p in paths)


def main():
    now = time.time()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cleanup-test-"))
    work = tmp / "work"
    touch(work / "audio" / "old.wav", 3, now)
    touch(work / "audio" / "fresh.wav", 0.5, now)
    touch(work / "audio" / "keep.txt", 30, now)
    touch(work / "asr" / "old.json", 8, now)
    touch(work / "asr" / "fresh.json", 1, now)
    touch(work / "sessions" / "old.json", 31, now)
    touch(work / "sessions" / "fresh.json", 2, now)
    touch(work / "replies" / "reply-old.pcm", 3, now)
    touch(work / "replies" / "reply-old.json", 3, now)
    touch(work / "replies" / "reply-fresh.pcm", 0.5, now)
    touch(work / "tts" / "old.pcm", 3, now)
    touch(work / "tts" / "fresh.pcm", 0.1, now)
    touch(work / "models" / "sensevoice" / "model.int8.onnx", 99, now)
    (work / "replies" / "latest.json").write_text(json.dumps(
        {"id": "old", "pcm": "reply-old.pcm"}))
    os.utime(work / "replies" / "latest.json", (now, now))

    expired = collect(work, {}, now=now)
    check("defaults collect", names(p for p, _ in expired), [
        "asr/old.json", "audio/old.wav", "replies/reply-old.json",
        "replies/reply-old.pcm", "sessions/old.json", "tts/old.pcm"])

    print("[1] dry run deletes nothing")
    removed, count = cleanup(work, dry_run=True, now=now, log=lambda *_: None)
    check("dry removed count", (removed, count), (0, 6))
    check("dry old still there", (work / "audio" / "old.wav").is_file(), True)
    check("dry latest kept",
          (work / "replies" / "latest.json").is_file(), True)

    print("[2] real run")
    removed, count = cleanup(work, now=now, log=lambda *_: None)
    check("removed", removed, 7)  # six expired files + dangling latest.json
    check("expired", count, 6)
    check("old wav gone", (work / "audio" / "old.wav").exists(), False)
    check("fresh wav kept", (work / "audio" / "fresh.wav").is_file(), True)
    check("unknown extension kept",
          (work / "audio" / "keep.txt").is_file(), True)
    check("model kept",
          (work / "models" / "sensevoice" / "model.int8.onnx").is_file(), True)
    check("dangling latest removed",
          (work / "replies" / "latest.json").exists(), False)
    check("fresh reply kept",
          (work / "replies" / "reply-fresh.pcm").is_file(), True)

    print("[3] latest kept while target exists")
    (work / "replies" / "latest.json").write_text(json.dumps(
        {"id": "fresh", "pcm": "reply-fresh.pcm"}))
    check("not dangling", latest_is_dangling(work / "replies" / "latest.json"),
          False)
    removed, _ = cleanup(work, now=now, log=lambda *_: None)
    check("second run removed", removed, 0)
    check("latest kept",
          (work / "replies" / "latest.json").is_file(), True)

    print("[4] custom retention and disabled directory")
    touch(work / "sessions" / "mid.json", 10, now)
    removed, _ = cleanup(work, {"sessions": 7, "audio": 0}, now=now,
                         log=lambda *_: None)
    check("custom sessions", removed, 1)  # mid.json (10 d); fresh is 2 d
    check("audio disabled keeps fresh",
          (work / "audio" / "fresh.wav").is_file(), True)

    print("[5] missing directories and symlinks")
    empty = tmp / "empty"
    empty.mkdir()
    check("empty work dir", cleanup(empty, now=now, log=lambda *_: None),
          (0, 0))
    outside = tmp / "outside.wav"
    outside.write_bytes(b"x")
    os.utime(outside, (now - 30 * 86400,) * 2)
    (work / "audio" / "link.wav").symlink_to(outside)
    cleanup(work, now=now, log=lambda *_: None)
    check("symlink not followed", outside.is_file(), True)

    print()
    print(f"{'PASS' if failures == 0 else 'FAIL'}: {checks - failures}/"
          f"{checks} checks passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
