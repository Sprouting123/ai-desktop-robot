#!/usr/bin/env python3
"""Record 3 s from the INMP441 and write a 16 kHz / 16 bit / mono WAV.

Run with .venv/bin/python scripts/capture_mic_wav.py after closing the serial
monitor. The board must run the experiment 010 firmware. The script asks the
firmware for a fixed 3 s recording (`mic record`), pulls it back with the
non-blocking `mic dump` transfer, verifies every row offset and the firmware
CRC32, then writes a WAV file under work/ by default.

The microphone only needs 3V3. Keep the servos' external 5V disconnected while
capturing. Nothing is uploaded; the WAV stays on this computer.
"""

import argparse
import math
import pathlib
import re
import struct
import sys
import time
import wave
import zlib

import serial
from serial.tools import list_ports

DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00"
DEFAULT_OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "work"
RECORD_FRAMES = 48000
RECORD_BYTES = RECORD_FRAMES * 2
SAMPLE_RATE = 16000
DONE_RE = re.compile(
    r"MIC_RECORD_DONE frames=48000 bytes=96000 sample_rate_hz=16000 "
    r"sample_format=s16le channels=1 crc32=([0-9a-f]{8})")
BEGIN_RE = re.compile(
    r"PCM_BEGIN bytes=96000 frames=48000 sample_rate_hz=16000 format=s16le "
    r"channels=1 crc32=([0-9a-f]{8}) line_bytes=(\d+)")
LINE_RE = re.compile(r"PCM ([0-9a-f]{6}) ([0-9a-f]+)")
END_RE = re.compile(r"PCM_END lines=(\d+) bytes=96000 crc32=([0-9a-f]{8})")


def read_until(port, marker, timeout):
    """Read serial text until a line starts with marker, or time out."""
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        data.extend(port.read(port.in_waiting or 1))
        if marker.encode() in data:
            break
    return data.decode("utf-8", errors="replace")


def send(port, command):
    port.write((command + "\n").encode("ascii"))
    port.flush()


def dc_block(samples, cutoff_hz=30.0, sample_rate=16000):
    """Remove the microphone's DC offset and slow drift.

    The INMP441 in this build carries an offset of a few percent of full
    scale. A one-pole high-pass at 30 Hz centres the waveform without touching
    the speech band.
    """
    coefficient = math.exp(-2.0 * math.pi * cutoff_hz / sample_rate)
    out = []
    previous_x = 0.0
    previous_y = 0.0
    for value in samples:
        previous_y = value - previous_x + coefficient * previous_y
        previous_x = value
        out.append(previous_y)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument(
        "--out", default=None,
        help="WAV path (default: work/mic-YYYYmmdd-HHMMSS.wav)")
    parser.add_argument(
        "--no-normalize", action="store_true",
        help="keep the raw 16-bit level instead of peak-normalizing to 70 percent")
    parser.add_argument(
        "--gain", type=float, default=None,
        help="fixed linear gain instead of normalization (for example 8)")
    parser.add_argument(
        "--delay", type=float, default=5.0,
        help="countdown seconds before capture so you can get ready")
    args = parser.parse_args()

    identity = next((p for p in list_ports.comports()
                     if pathlib.Path(p.device).resolve()
                     == pathlib.Path(args.port).resolve()), None)
    if identity is None or (identity.vid, identity.pid, identity.serial_number) != (
            0x1A86, 0x55D3, "5D4D001473"):
        raise SystemExit(
            "Target does not match the verified ESP32-S3 COM bridge; refusing.")

    if args.out is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_path = DEFAULT_OUT_DIR / f"mic-{stamp}.wav"
    else:
        out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    port = serial.Serial(port=None, baudrate=115200, timeout=0.05,
                         write_timeout=2, exclusive=True)
    port.dtr = False
    port.rts = False
    port.port = args.port
    port.open()
    try:
        # Leave any previous recording/dump behind and start from idle.
        send(port, "mic stop")
        read_until(port, "OK mic=stopped", 1.0)

        if args.delay > 0:
            print(f"Countdown {args.delay:.0f} s. Start speaking out loud when "
                  f"the count reaches 3, and keep talking until "
                  f"'recording finished' appears.", flush=True)
            for remaining in range(int(args.delay), 0, -1):
                print(f"  {remaining} ...", flush=True)
                time.sleep(1.0)

        send(port, "mic record")
        print(">>> RECORDING 3 s — keep talking ...", flush=True)
        reply = read_until(port, "OK mic=recording", 2.0)
        if "OK mic=recording frames=48000 duration_ms=3000" not in reply:
            raise SystemExit(f"mic record was refused:\n{reply.strip()}")
        done_text = read_until(port, "MIC_RECORD_DONE", 8.0)
        done_lines = [line for line in done_text.splitlines()
                      if line.startswith("MIC_RECORD_DONE")]
        done = DONE_RE.fullmatch(done_lines[0]) if len(done_lines) == 1 else None
        if done is None:
            raise SystemExit(f"no valid recording completion line:\n"
                             f"{done_text.strip()}")
        firmware_crc = done.group(1)
        print("<<< recording finished; transferring ...", flush=True)

        print("transferring 96000 bytes (about 20 s at 115200) ...",
              flush=True)
        send(port, "mic dump")
        dump_text = read_until(port, "PCM_END", 60.0)
        lines = dump_text.splitlines()
        begin = next((BEGIN_RE.fullmatch(line) for line in lines
                      if line.startswith("PCM_BEGIN")), None)
        end = next((END_RE.fullmatch(line) for line in lines
                    if line.startswith("PCM_END")), None)
        if begin is None or end is None:
            raise SystemExit("transfer did not start or finish cleanly")
        if begin.group(1) != firmware_crc or end.group(2) != firmware_crc:
            raise SystemExit("firmware checksums disagree between messages")

        rows = []
        for line in lines:
            match = LINE_RE.fullmatch(line)
            if match:
                rows.append((int(match.group(1), 16),
                             bytes.fromhex(match.group(2))))
        expected_offsets = list(range(0, RECORD_BYTES, 48))
        if [offset for offset, _ in rows] != expected_offsets:
            raise SystemExit("transfer rows are missing, duplicated or out of order")
        payload = b"".join(data for _, data in rows)
        if len(payload) != RECORD_BYTES:
            raise SystemExit(f"got {len(payload)} bytes, expected {RECORD_BYTES}")
        actual_crc = f"{zlib.crc32(payload) & 0xffffffff:08x}"
        if actual_crc != firmware_crc:
            raise SystemExit(
                f"CRC mismatch: firmware {firmware_crc}, host {actual_crc}")

        raw_samples = list(struct.unpack(f"<{RECORD_FRAMES}h", payload))
        raw_peak = max((abs(value) for value in raw_samples), default=0)
        samples = dc_block(raw_samples)
        peak = max((abs(value) for value in samples), default=0.0)
        peak_pct = peak * 100 / 32767 if peak else 0
        if args.gain is not None:
            gain = args.gain
        elif args.no_normalize or peak == 0:
            gain = 1.0
        else:
            gain = min(32767 * 0.70 / peak, 64.0)
        scaled = [max(-32768, min(32767, int(round(value * gain))))
                  for value in samples]
        wav_bytes = struct.pack(f"<{RECORD_FRAMES}h", *scaled)

        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(wav_bytes)

        print(f"CRC32 verified: {firmware_crc}")
        print(f"raw peak: {raw_peak}, after 30 Hz DC block: {peak:.0f} "
              f"({peak_pct:.1f}% of 16-bit full scale), gain x{gain:.2f}")
        print(f"WAV written: {out_path} "
              f"(3.000 s, {SAMPLE_RATE} Hz, 16-bit mono)")
    finally:
        port.close()


if __name__ == "__main__":
    sys.exit(main())
