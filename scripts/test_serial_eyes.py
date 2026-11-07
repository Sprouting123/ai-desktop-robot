"""Live regression check for the experiment 004 firmware (historical).

The current experiment 005 firmware uses scripts/test_serial_servo.py, which
includes these checks with updated boot/help and servo expectations. This file
is kept as the experiment 004 acceptance record and will not match newer boot
or help text.

Run with .venv/bin/python scripts/test_serial_eyes.py after closing all monitors.
It resets this board and leaves the RGB LED off with the normal eye screen
showing. Every check here is a software/serial observation; it cannot prove
what the physical OLED looks like.
"""

import argparse
import os
import re
import time

import serial
from serial.tools import list_ports

DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00"
BOOT = "[experiment 004] OLED eyes V1.0 / Arduino"
HELP = ("HELP red | green | blue | off | status | help | i2cscan | oled_sh1106 | "
        "oled_ssd1306 | oled_status | eyes <normal|happy|angry|sad|embarrassed|"
        "sympathy|comfort|melancholy|left|right> | eyes blink | eyes status | "
        "eyes dump; max_line=32; endings=LF/CR/CRLF")
TOO_LONG = "ERR line_too_long; max=32; discarded"
INVALID = "ERR invalid_character; use ASCII commands; discarded"
UNKNOWN = "ERR unknown_command; use help"
SCAN_BEGIN = "I2C_SCAN begin sda=8 scl=9 frequency_hz=100000 range=0x08-0x77"
EXPRESSIONS = ["normal", "happy", "angry", "sad", "embarrassed",
               "sympathy", "comfort", "melancholy", "left", "right"]
INTERVALS = {"normal": (3000, 5000), "happy": (3000, 5000),
             "angry": (3000, 5000), "sad": (5000, 7000),
             "embarrassed": (3600, 5600), "sympathy": (3000, 5000),
             "comfort": (4500, 6500), "melancholy": (6000, 8000),
             "left": (3000, 5000), "right": (3000, 5000)}
DUMP_RE = re.compile(
    r"EYES_DUMP expression=(\w+) closure=([0-4]) accent=(\d) hash=([0-9A-F]{8})")
STATUS_RE = re.compile(
    r"EYES expression=(\w+) phase=(idle|closing|closed|opening|paused) auto_blink=(\d) "
    r"mode=(eyes|test) interval_ms=(\d+) blinks=(\d+) frames=(\d+) "
    r"transfers=(\d+) hash=([0-9A-F]{8}) max_tx_us=(\d+) heap=(\d+) "
    r"min_heap=(\d+) uptime_ms=(\d+)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    args = parser.parse_args()
    identity = next((p for p in list_ports.comports()
                     if os.path.realpath(p.device) == os.path.realpath(args.port)), None)
    if identity is None or (identity.vid, identity.pid, identity.serial_number) != (
            0x1A86, 0x55D3, "5D4D001473"):
        raise SystemExit("Target does not match the verified ESP32-S3 COM bridge; refusing to open.")

    port = serial.Serial(port=None, baudrate=115200, timeout=0.03,
                         write_timeout=2, exclusive=True)
    port.dtr = False
    port.rts = False
    port.port = args.port
    passed = 0

    def collect(seconds=0.18):
        end = time.monotonic() + seconds
        data = bytearray()
        while time.monotonic() < end:
            data.extend(port.read(port.in_waiting or 1))
        return data.decode("utf-8", errors="replace")

    def send(payload, seconds=0.18):
        port.write(payload)
        port.flush()
        return [line for line in collect(seconds).splitlines() if line]

    def check(name, actual, expected):
        nonlocal passed
        if actual != expected:
            raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")
        passed += 1
        print(f"PASS {passed:03d} {name}: {actual!r}", flush=True)

    def expect(name, payload, expected, seconds=0.18):
        check(name, send(payload, seconds), expected)

    def status(name, state):
        lines = send(b"status\n")
        pattern = rf"STATUS state={state} pin=48 enabled=1 brightness=24 uptime_ms=\d+"
        check(name, len(lines) == 1 and re.fullmatch(pattern, lines[0]) is not None, True)
        print("  " + lines[0], flush=True)

    def oled_status(name, driver, screen, draw_called):
        lines = send(b"oled_status\n")
        pattern = (rf"OLED_STATUS driver={driver} address=0x3C draw_called={draw_called} "
                   rf"visual=unverified frequency_hz=100000 screen={screen}")
        check(name, len(lines) == 1 and re.fullmatch(pattern, lines[0]) is not None, True)
        print("  " + lines[0], flush=True)

    def eyes_status(name, expression=None, mode="eyes"):
        lines = send(b"eyes status\n")
        match = STATUS_RE.fullmatch(lines[0]) if len(lines) == 1 else None
        check(name, match is not None, True)
        if expression is not None:
            check(f"{name} expression", match.group(1), expression)
        check(f"{name} mode", match.group(4), mode)
        print("  " + lines[0], flush=True)
        return match

    def eyes_dump(name, expression):
        lines = send(b"eyes dump\n", 0.9)
        header = DUMP_RE.fullmatch(lines[0]) if lines else None
        check(f"{name} dump header", header is not None, True)
        check(f"{name} dump expression", header.group(1), expression)
        grid = lines[1:]
        check(f"{name} dump rows", len(grid), 32)
        check(f"{name} dump width", all(len(row) == 64 for row in grid), True)
        check(f"{name} dump uses only known glyphs",
              all(re.fullmatch(r"[.#]{64}", row) is not None for row in grid), True)
        check(f"{name} dump is not blank", any("#" in row for row in grid), True)
        print("  " + lines[0], flush=True)
        return header.group(4)

    try:
        port.open()
        # A deliberate reset makes the initial state reproducible.
        port.rts = True
        time.sleep(0.1)
        port.rts = False
        startup = collect(2.5)
        print("STARTUP\n" + startup, flush=True)
        check("experiment 004 boot identity", BOOT in startup, True)
        check("physical memory configuration",
              "flash=16777216 psram_chip=8388608" in startup and "[warning]" not in startup, True)
        check("boot enters the eye screen",
              "EYES_MODE driver=SH1106 expression=normal auto_blink=1" in startup, True)
        oled_status("boot draws eyes on SH1106", "SH1106", "eyes", 0)
        status("initial state is off", "off")
        expect("help", b"help\n", [HELP])

        # --- experiment 002 regression ------------------------------------
        expect("red with LF", b"red\n", ["OK state=red pin=48"])
        status("status after red", "red")
        check("idle produces no logging", collect(3.2), "")
        status("red remains selected during idle", "red")
        expect("green with CR", b"green\r", ["OK state=green pin=48"])
        expect("blue with CRLF has one response", b"blue\r\n", ["OK state=blue pin=48"])
        expect("off", b"off\n", ["OK state=off pin=48"])
        status("status after off", "off")
        expect("empty and whitespace-only lines", b"\r\n\n\r \t\r\n", [])
        status("empty lines preserve off", "off")
        expect("case and surrounding whitespace", b" \tReD\t \r\n", ["OK state=red pin=48"])
        expect("partial command does not execute", b"gr", [])
        expect("complete fragmented command", b"een\n", ["OK state=green pin=48"])
        expect("unknown command", b"purple\n", [UNKNOWN])
        expect("arguments are not silently accepted", b"red blue\n", [UNKNOWN])
        status("unknown inputs preserve green", "green")
        expect("exactly 32 bytes accepted", b"blue" + b" " * 28 + b"\n", ["OK state=blue pin=48"])
        expect("33 bytes reject a valid-looking prefix",
               b"red" + b" " * 30 + b"\r\n", [TOO_LONG])
        status("oversize line preserves blue", "blue")
        expect("4096-byte line discards valid-looking suffix",
               b"x" * 4096 + b"green\n", [TOO_LONG], 0.3)
        status("large input preserves blue and parser recovers", "blue")
        expect("NUL rejects entire line", b"red\x00green\n", [INVALID])
        expect("UTF-8 rejects entire line", "红\n".encode("utf-8"), [INVALID])
        expect("terminal escape rejects entire line", b"red\x1b[31m\n", [INVALID])
        status("invalid input preserves blue", "blue")
        expect("Backspace edits buffered input", b"greeX\bn\n", ["OK state=green pin=48"])
        expect("Delete edits buffered input", b"bluX\x7fe\n", ["OK state=blue pin=48"])
        expect("multiple commands in one write", b"red\ngreen\rblue\r\noff\n",
               ["OK state=red pin=48", "OK state=green pin=48",
                "OK state=blue pin=48", "OK state=off pin=48"])
        expect("overflow recovery within one write", b"x" * 33 + b"\nred\n",
               [TOO_LONG, "OK state=red pin=48"])
        status("state after immediate recovery", "red")
        expect("help preserves state", b"help\r\n", [HELP])
        status("state after help", "red")

        # --- experiment 003 regression ------------------------------------
        check("I2C initialized",
              "I2C_INIT ready=1 sda=8 scl=9 frequency_hz=100000 timeout_ms=25" in startup, True)
        previous_addresses = None
        for payload in (b"i2cscan\n", b" \tI2CSCAN \r\n"):
            lines = send(payload, 5)
            print("SCAN\n" + "\n".join(lines), flush=True)
            check("scan configuration", lines[0] if lines else "", SCAN_BEGIN)
            addresses = [line for line in lines[1:-1]
                         if re.fullmatch(r"I2C_FOUND address=0x[0-9A-F]{2}", line)]
            check("scan reports only valid discovered addresses", len(addresses), len(lines) - 2)
            check("connected device responds", bool(addresses), True)
            check("scan completes without bus errors", lines[-1],
                  f"I2C_SCAN done devices={len(addresses)} errors=0 result=ok")
            if previous_addresses is not None:
                check("repeat scan is stable", addresses, previous_addresses)
            previous_addresses = addresses
            status("scan preserves red state", "red")
        expect("oversized scan is discarded", b"i2cscan" + b" " * 26 + b"\n", [TOO_LONG])
        expect("invalid scan is discarded", b"i2cscan\x00\n", [INVALID])

        for driver, payload in (("SSD1306", b" OLED_SSD1306 \r\n"),
                                ("SH1106", b"oled_sh1106\n")):
            expect(f"switch and draw {driver}", payload,
                   [f"OLED_DRAW driver={driver} address=0x3C probe_after=0 visual=unverified",
                    (f"OLED_STATUS driver={driver} address=0x3C draw_called=1 "
                     f"visual=unverified frequency_hz=100000 screen=test")], 1.5)
            oled_status(f"query {driver}", driver, "test", 1)
            status(f"{driver} preserves RGB", "red")
            expect(f"scan after {driver}", b"i2cscan\n",
                   [SCAN_BEGIN, "I2C_FOUND address=0x3C",
                    "I2C_SCAN done devices=1 errors=0 result=ok"], 5)
        expect("invalid driver name", b"oled_ssd1306 extra\n", [UNKNOWN])
        expect("oversized display command", b"oled_ssd1306" + b" " * 22 + b"\n", [TOO_LONG])
        expect("invalid display command", b"oled_ssd1306\x00\n", [INVALID])
        oled_status("rejected commands preserve SH1106", "SH1106", "test", 1)

        # --- experiment 004: expressions ---------------------------------
        eyes_status("test screen pauses the engine", mode="test")
        expect("eyes command with no argument", b"eyes\n", ["ERR eyes_usage; use help"])
        expect("unknown expression", b"eyes silly\n", ["ERR unknown_expression; use help"])
        expect("extra argument is rejected", b"eyes normal extra\n",
               ["ERR unknown_expression; use help"])
        expect("oversized eye command", b"eyes angry" + b" " * 26 + b"\n", [TOO_LONG])
        expect("invalid eye command", b"eyes normal\x00\n", [INVALID])

        expect("return from the test screen to the eyes", b"eyes normal\n",
               ["EYES_MODE driver=SH1106 expression=normal auto_blink=1",
                "OK expression=normal"])
        hashes = {}
        for name in EXPRESSIONS:
            expect(f"select {name}", f"eyes {name}\n".encode(), [f"OK expression={name}"])
            match = eyes_status(f"{name} status", name)
            low, high = INTERVALS[name]
            check(f"{name} blink interval in range", low <= int(match.group(5)) <= high, True)
            hashes[name] = eyes_dump(f"{name}", name)
        check("all ten expressions differ pixel-for-pixel", len(set(hashes.values())), 10)
        print("  hashes " + repr(hashes), flush=True)
        oled_status("eye screen is reported", "SH1106", "eyes", 1)

        # --- experiment 004: blink ---------------------------------------
        expect("manual blink starts", b"eyes blink\n",
               ["OK blink expression=right started=1"])
        expect("second blink is rejected mid-blink", b"eyes blink\n",
               ["OK blink expression=right started=0"])
        deadline = time.monotonic() + 2.5
        match = eyes_status("status during blink")
        while match.group(2) != "idle" and time.monotonic() < deadline:
            time.sleep(0.15)
            match = eyes_status("status during blink")
        check("manual blink completes", match.group(2), "idle")
        check("manual blink increments the counter", int(match.group(6)) >= 1, True)
        check("manual blink keeps the expression", match.group(1), "right")

        # --- experiment 004: expression switch cancels a blink -----------
        check("expression change cancels an unfinished blink",
              send(b"eyes blink\neyes sad\n", 0.4),
              ["OK blink expression=right started=1", "OK expression=sad"])
        match = eyes_status("cancelled blink leaves the engine idle", "sad")
        check("cancelled blink phase", match.group(2), "idle")
        expect("restore right before rapid switching", b"eyes right\n",
               ["OK expression=right"])

        # --- experiment 004: rapid switching -----------------------------
        payload = "".join(f"eyes {name}\n" for _ in range(3) for name in EXPRESSIONS)
        expected = [f"OK expression={name}"
                    for _ in range(3) for name in EXPRESSIONS]
        check("thirty rapid expression switches",
              send(payload.encode(), 2.0), expected)
        eyes_status("rapid switching ends on right", "right")

        # --- experiment 004: auto blink and responsiveness ---------------
        expect("return to normal", b"eyes normal\n", ["OK expression=normal"])
        start = eyes_status("auto blink starting point", "normal")
        start_blinks = int(start.group(6))
        blinks_seen = start_blinks
        max_transfer = 0
        heaps = []
        deadline = time.monotonic() + 10.0
        polls = 0
        while time.monotonic() < deadline:
            time.sleep(0.8)
            match = eyes_status("auto blink poll", "normal")
            blinks_seen = int(match.group(6))
            max_transfer = max(max_transfer, int(match.group(10)))
            heaps.append(int(match.group(11)))
            polls += 1
        check("automatic blinking runs while commands are served",
              blinks_seen >= start_blinks + 1, True)
        check("auto blink cycles are observed", polls >= 8, True)
        check("largest region transfer stays non-blocking", max_transfer < 20000, True)
        check("internal heap stays stable", max(heaps) - min(heaps) < 8192, True)
        print(f"  auto blinks {start_blinks}->{blinks_seen}, "
              f"max_transfer_us={max_transfer}, heap={min(heaps)}..{max(heaps)}", flush=True)

        # --- final state --------------------------------------------------
        expect("finish off", b"off\n", ["OK state=off pin=48"])
        status("final RGB state", "off")
        oled_status("final screen is the eye screen", "SH1106", "eyes", 1)
        print(f"PASS: {passed} checks; physical eye shapes, emotion readability, "
              f"and flash-free display still require user confirmation.", flush=True)
    finally:
        if port.is_open:
            # Terminate any partial/invalid line, then leave a safe, visible state.
            port.write(b"\noff\neyes normal\n")
            port.flush()
            collect(0.3)
            port.close()


if __name__ == "__main__":
    main()
