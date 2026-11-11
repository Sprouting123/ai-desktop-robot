#!/usr/bin/env python3
"""Delete old recordings and session data from work/ (server housekeeping).

The robot's server keeps short-lived personal data: recordings, ASR text,
chat turns, TTS audio and reply PCM. This script applies a fixed retention
per directory, only to regular files directly inside the known directories,
and never touches credentials, models or configuration.

    .venv/bin/python scripts/cleanup_work.py --dry-run
    .venv/bin/python scripts/cleanup_work.py

Run it from a systemd timer (see experiments/017). `--dry-run` prints the
same decisions without deleting anything. Missing directories are skipped.
"""

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_WORK_DIR = ROOT / "work"

# (subdirectory, glob, default retention in days)
SPECS = (
    ("audio", "*.wav", 2),
    ("asr", "*.json", 7),
    ("sessions", "*.json", 30),
    ("replies", "reply-*", 2),
    ("tts", "*.pcm", 2),
    ("tts", "*.wav", 2),
)


def _safe_dir(work_dir, name):
    path = (work_dir / name).resolve()
    try:
        path.relative_to(work_dir.resolve())
    except ValueError:
        return None
    return path


def collect(work_dir, retention, now=None):
    """Return [(path, age_days)] for regular files past their retention."""
    now = time.time() if now is None else now
    expired = []
    seen = set()
    for name, pattern, default_days in SPECS:
        days = retention.get(name, default_days)
        if days <= 0:
            continue
        directory = _safe_dir(work_dir, name)
        if directory is None or not directory.is_dir():
            continue
        for path in sorted(directory.glob(pattern)):
            if path in seen or path.is_symlink() or not path.is_file():
                continue
            seen.add(path)
            age = (now - path.stat().st_mtime) / 86400.0
            if age >= days:
                expired.append((path, age))
    return expired


def latest_is_dangling(path):
    """True when replies/latest.json is unreadable or points at a missing PCM."""
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        pcm = record.get("pcm")
    except (OSError, ValueError):
        return True
    if not isinstance(pcm, str) or not pcm:
        return True
    return not (path.parent / pcm).is_file()


def reconcile_latest(path):
    """Remove replies/latest.json when it points at a deleted PCM."""
    if not latest_is_dangling(path):
        return False
    path.unlink(missing_ok=True)
    return True


def cleanup(work_dir, retention=None, dry_run=False, now=None, log=print):
    work_dir = pathlib.Path(work_dir)
    retention = retention or {}
    expired = collect(work_dir, retention, now=now)
    removed = 0
    for path, age in expired:
        rel = path.relative_to(work_dir)
        if dry_run:
            log(f"would remove {rel} age_days={age:.2f}")
            continue
        try:
            path.unlink()
        except OSError as error:
            log(f"skip {rel} error={error}")
            continue
        log(f"removed {rel} age_days={age:.2f}")
        removed += 1
    latest = work_dir / "replies" / "latest.json"
    if latest_is_dangling(latest):
        if dry_run:
            log("would remove replies/latest.json reason=dangling")
        else:
            reconcile_latest(latest)
            log("removed replies/latest.json reason=dangling")
            removed += 1
    return removed, len(expired)


def main():
    parser = argparse.ArgumentParser(
        description="Delete old recordings and chat data from work/")
    parser.add_argument("--work-dir", default=str(DEFAULT_WORK_DIR),
                        help=f"data directory (default: {DEFAULT_WORK_DIR})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be removed, delete nothing")
    for name in ("audio", "asr", "sessions", "replies", "tts"):
        parser.add_argument(f"--{name}-days", type=int, default=None,
                            help=f"retention in days (default: from SPECS)")
    args = parser.parse_args()

    retention = {}
    for name in ("audio", "asr", "sessions", "replies", "tts"):
        value = getattr(args, f"{name}_days")
        if value is not None:
            if value < 0:
                parser.error(f"--{name}-days must not be negative")
            retention[name] = value

    work_dir = pathlib.Path(args.work_dir)
    if not work_dir.is_dir():
        raise SystemExit(f"work directory not found: {work_dir}")
    removed, expired = cleanup(work_dir, retention, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    print(f"[cleanup] {verb}={expired if args.dry_run else removed} "
          f"expired={expired} dry_run={int(args.dry_run)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
