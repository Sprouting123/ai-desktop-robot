"""Live regression check for experiment 006 (OLED eyes + dual SG90 servos).

Run with .venv/bin/python scripts/test_serial_dual_servo.py after closing all
monitors and with the servos' external 5 V supply disconnected. Covers the
experiment 002/003/004 commands plus two independent servo channels:
legacy `servo ...` aliases servo 1, `servo1`/`servo2` address either channel,
and `servo both center|stop` acts on both. It resets this board and leaves the
RGB LED off, both servo outputs disabled and the normal eye screen showing.

Every check here is a software/serial observation; it cannot prove the physical
OLED appearance or servo movement. Do not use it as the servo physical
acceptance test.
"""

import argparse
import os
import re
import time

import serial
from serial.tools import list_ports

DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00"
BOOT = "[experiment 006] OLED eyes + dual SG90 servo / Arduino"
HELP = ("HELP red | green | blue | off | status | help | i2cscan | oled_sh1106 | "
        "oled_ssd1306 | oled_status | eyes <normal|happy|angry|sad|embarrassed|"
        "sympathy|comfort|melancholy|left|right> | eyes blink | eyes status | "
        "eyes dump | servo <60-120> | servo center | servo status | servo stop | "
        "servo1 <60-120> | servo1 center | servo1 status | servo1 stop | "
        "servo2 <60-120> | servo2 center | servo2 status | servo2 stop | "
        "servo both center | servo both stop; max_line=32; endings=LF/CR/CRLF")
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
SERVO_RE = {
    prefix: re.compile(
        rf"{prefix} state=(idle|moving|stopped) ready=([01]) angle=(\d+) "
        r"target=(\d+) pulse_us=(\d+) output=(on|off) pin=(\d+) "
        r"frequency_hz=(\d+) min=(\d+) max=(\d+) speed_dps=(\d+) channel=(\d+)")
    for prefix in ("SERVO", "SERVO1", "SERVO2")
}
SERVO_STATUS_COMMAND = {
    "SERVO": b"servo status\n",
    "SERVO1": b"servo1 status\n",
    "SERVO2": b"servo2 status\n",
}


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

    def servo_status(name, prefix="SERVO1", state=None, output=None):
        lines = send(SERVO_STATUS_COMMAND[prefix])
        match = SERVO_RE[prefix].fullmatch(lines[0]) if len(lines) == 1 else None
        check(name, match is not None, True)
        if state is not None:
            check(f"{name} state", match.group(1), state)
        if output is not None:
            check(f"{name} output", match.group(6), output)
        print("  " + lines[0], flush=True)
        return match

    def servo_wait_idle(name, prefix="SERVO1", timeout=3.0):
        deadline = time.monotonic() + timeout
        match = servo_status(name, prefix)
        while match.group(1) == "moving" and time.monotonic() < deadline:
            time.sleep(0.08)
            match = servo_status(name, prefix)
        check(f"{name} settles", match.group(1), "idle")
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
        check("experiment 006 boot identity", BOOT in startup, True)
        check("physical memory configuration",
              "flash=16777216 psram_chip=8388608" in startup and "[warning]" not in startup, True)
        check("boot enters the eye screen",
              "EYES_MODE driver=SH1106 expression=normal auto_blink=1" in startup, True)
        check("servo 1 PWM is initialized with output off",
              "SERVO1_INIT ready=1 pin=4 channel=0 requested_hz=50" in startup and
              "output=off center=90" in startup, True)
        check("servo 2 PWM is initialized with output off",
              "SERVO2_INIT ready=1 pin=5 channel=1 requested_hz=50" in startup and
              startup.count("output=off center=90") >= 2, True)
        oled_status("boot draws eyes on SH1106", "SH1106", "eyes", 0)
        status("initial state is off", "off")
        expect("help", b"help\n", [HELP])
        boot_legacy = servo_status("legacy servo status leaves servo 1 stopped",
                                   "SERVO", state="stopped", output="off")
        boot_one = servo_status("boot leaves servo 1 stopped",
                                "SERVO1", state="stopped", output="off")
        boot_two = servo_status("boot leaves servo 2 stopped",
                                "SERVO2", state="stopped", output="off")
        check("boot servo 1 reference angle", boot_one.group(3), "90")
        check("boot servo 2 reference angle", boot_two.group(3), "90")
        check("boot legacy status reports channel 0", boot_legacy.group(12), "0")
        check("boot servo 1 uses pin 4 / channel 0",
              (boot_one.group(7), boot_one.group(12)), ("4", "0"))
        check("boot servo 2 uses pin 5 / channel 1",
              (boot_two.group(7), boot_two.group(12)), ("5", "1"))
        check("both servos keep the conservative range",
              (boot_one.group(9), boot_one.group(10),
               boot_two.group(9), boot_two.group(10)), ("60", "120", "60", "120"))
        check("both servos run near 50 Hz",
              all(49 <= int(m.group(8)) <= 51 for m in (boot_one, boot_two)), True)

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

        # --- experiment 006: parsing, limits and legacy compatibility ----
        expect("legacy servo with no argument", b"servo\n",
               ["ERR servo_usage; use help"])
        expect("legacy servo non-numeric angle", b"servo abc\n",
               ["ERR servo_usage; use help"])
        expect("legacy servo negative angle", b"servo -5\n",
               ["ERR servo_usage; use help"])
        expect("legacy servo extra argument", b"servo 75 extra\n",
               ["ERR servo_usage; use help"])
        expect("legacy servo angle below range", b"servo 59\n",
               ["ERR servo_range min=60 max=120"])
        expect("legacy servo angle above range", b"servo 121\n",
               ["ERR servo_range min=60 max=120"])
        expect("legacy servo absolute minimum is rejected", b"servo 0\n",
               ["ERR servo_range min=60 max=120"])
        expect("legacy servo absolute maximum is rejected", b"servo 180\n",
               ["ERR servo_range min=60 max=120"])
        expect("servo1 non-numeric angle", b"servo1 abc\n",
               ["ERR servo_usage; use help"])
        expect("servo1 angle below range", b"servo1 59\n",
               ["ERR servo_range min=60 max=120"])
        expect("servo2 with no argument", b"servo2\n",
               ["ERR servo_usage; use help"])
        expect("servo2 non-numeric angle", b"servo2 abc\n",
               ["ERR servo_usage; use help"])
        expect("servo2 negative angle", b"servo2 -5\n",
               ["ERR servo_usage; use help"])
        expect("servo2 extra argument", b"servo2 75 extra\n",
               ["ERR servo_usage; use help"])
        expect("servo2 angle below range", b"servo2 59\n",
               ["ERR servo_range min=60 max=120"])
        expect("servo2 angle above range", b"servo2 121\n",
               ["ERR servo_range min=60 max=120"])
        expect("servo both with no action", b"servo both\n",
               ["ERR servo_usage; use help"])
        expect("servo both rejects numeric targets", b"servo both 75\n",
               ["ERR servo_usage; use help"])
        expect("servo both rejects unknown actions", b"servo both wiggle\n",
               ["ERR servo_usage; use help"])
        expect("servo1 rejects the both keyword", b"servo1 both center\n",
               ["ERR servo_usage; use help"])
        expect("oversized legacy servo command",
               b"servo center" + b" " * 21 + b"\n", [TOO_LONG])
        expect("oversized servo2 command",
               b"servo2 center" + b" " * 20 + b"\n", [TOO_LONG])
        expect("invalid legacy servo command", b"servo 75\x00\n", [INVALID])
        expect("invalid servo2 command", b"servo2 75\x00\n", [INVALID])
        match1 = servo_status("rejected commands keep servo 1 stopped",
                              "SERVO1", state="stopped", output="off")
        match2 = servo_status("rejected commands keep servo 2 stopped",
                              "SERVO2", state="stopped", output="off")
        check("rejected commands keep both reference angles",
              (match1.group(3), match2.group(3)), ("90", "90"))
        check("both servos keep the conservative range",
              (match1.group(9), match1.group(10),
               match2.group(9), match2.group(10)), ("60", "120", "60", "120"))
        check("both servos refresh near 50 Hz",
              all(49 <= int(m.group(8)) <= 51 for m in (match1, match2)), True)

        # --- experiment 005 compatibility: legacy servo == servo 1 --------
        expect("legacy servo stop is explicit", b"servo stop\n",
               ["OK servo=stopped output=off"])
        match = servo_status("legacy stop keeps servo 1 output off",
                             "SERVO1", state="stopped", output="off")
        check("legacy stop reports zero pulse", match.group(5), "0")
        expect("legacy servo center", b"servo center\n",
               ["OK servo=center angle=90"])
        match = servo_status("legacy center enables servo 1",
                             "SERVO1", state="idle", output="on")
        check("legacy center angle", match.group(3), "90")
        check("legacy center pulse width", match.group(5), "1500")
        servo_status("legacy center leaves servo 2 stopped",
                     "SERVO2", state="stopped", output="off")

        # --- experiment 005 compatibility: gradual movement --------------
        expect("legacy servo 75", b"servo 75\n", ["OK servo=target angle=75"])
        match = servo_wait_idle("legacy servo 75 completes")
        check("legacy servo 75 final angle", match.group(3), "75")
        check("legacy servo 75 pulse width", match.group(5), "1350")
        expect("legacy servo 105", b"servo 105\n", ["OK servo=target angle=105"])
        match = servo_wait_idle("legacy servo 105 completes")
        check("legacy servo 105 final angle", match.group(3), "105")
        check("legacy servo 105 pulse width", match.group(5), "1650")
        expect("legacy servo 60 at the lower limit", b"servo 60\n",
               ["OK servo=target angle=60"])
        match = servo_wait_idle("legacy servo 60 completes")
        check("legacy servo 60 final angle", match.group(3), "60")
        check("legacy servo 60 pulse width", match.group(5), "1200")
        check("legacy servo 120 accepted", send(b"servo 120\n", 0.02),
              ["OK servo=target angle=120"])
        match = servo_status("legacy servo 120 starts moving", "SERVO1",
                             state="moving", output="on")
        check("legacy servo 120 has not jumped to its target",
              int(match.group(3)) < 120, True)
        match = servo_wait_idle("legacy servo 120 completes")
        check("legacy servo 120 final angle", match.group(3), "120")
        check("legacy servo 120 pulse width", match.group(5), "1800")

        # --- experiment 005 compatibility: stop during movement ----------
        check("legacy servo 60 accepted while moving", send(b"servo 60\n", 0.02),
              ["OK servo=target angle=60"])
        match = servo_status("legacy servo 60 is moving", "SERVO1", state="moving")
        check("legacy servo 60 starts above its target", int(match.group(3)) > 60, True)
        expect("legacy servo stop during movement", b"servo stop\n",
               ["OK servo=stopped output=off"])
        match = servo_status("legacy stop interrupts movement", "SERVO1",
                             state="stopped", output="off")
        check("legacy stop reports zero pulse", match.group(5), "0")
        check("legacy stop keeps an intermediate angle",
              60 < int(match.group(3)) < 120, True)
        expect("legacy servo center resumes from the stopped position",
               b"servo center\n", ["OK servo=center angle=90"])
        match = servo_wait_idle("legacy resumed center reaches 90")
        check("legacy resumed center angle", match.group(3), "90")
        check("legacy resumed output is on", match.group(6), "on")

        # --- experiment 006: explicit servo1 interface --------------------
        expect("servo1 stop", b"servo1 stop\n",
               ["OK servo1=stopped output=off"])
        servo_status("servo1 stop disables its output", "SERVO1",
                     state="stopped", output="off")
        expect("servo1 center", b"servo1 center\n",
               ["OK servo1=center angle=90"])
        match = servo_status("servo1 center enables output", "SERVO1",
                             state="idle", output="on")
        check("servo1 center angle", match.group(3), "90")
        check("servo1 center pulse width", match.group(5), "1500")
        expect("servo1 75", b"servo1 75\n", ["OK servo1=target angle=75"])
        match = servo_wait_idle("servo1 75 completes", "SERVO1")
        check("servo1 75 final angle", match.group(3), "75")
        check("servo1 75 pulse width", match.group(5), "1350")

        # --- experiment 006: servo2 independent movement -----------------
        expect("servo2 center", b"servo2 center\n",
               ["OK servo2=center angle=90"])
        match = servo_status("servo2 center enables output", "SERVO2",
                             state="idle", output="on")
        check("servo2 center angle", match.group(3), "90")
        check("servo2 center pulse width", match.group(5), "1500")
        check("servo2 center leaves servo 1 untouched",
              servo_status("servo 1 survives servo2 center", "SERVO1").group(3), "75")
        expect("servo2 75", b"servo2 75\n", ["OK servo2=target angle=75"])
        match = servo_wait_idle("servo2 75 completes", "SERVO2")
        check("servo2 75 final angle", match.group(3), "75")
        check("servo2 75 pulse width", match.group(5), "1350")
        expect("servo2 105", b"servo2 105\n", ["OK servo2=target angle=105"])
        match = servo_wait_idle("servo2 105 completes", "SERVO2")
        check("servo2 105 final angle", match.group(3), "105")
        check("servo2 105 pulse width", match.group(5), "1650")
        expect("servo2 60 at the lower limit", b"servo2 60\n",
               ["OK servo2=target angle=60"])
        match = servo_wait_idle("servo2 60 completes", "SERVO2")
        check("servo2 60 final angle", match.group(3), "60")
        check("servo2 60 pulse width", match.group(5), "1200")
        check("servo2 120 accepted", send(b"servo2 120\n", 0.02),
              ["OK servo2=target angle=120"])
        match = servo_status("servo2 120 starts moving", "SERVO2",
                             state="moving", output="on")
        check("servo2 120 has not jumped to its target",
              int(match.group(3)) < 120, True)
        match = servo_wait_idle("servo2 120 completes", "SERVO2")
        check("servo2 120 final angle", match.group(3), "120")
        check("servo2 120 pulse width", match.group(5), "1800")
        check("servo2 60 accepted while moving", send(b"servo2 60\n", 0.02),
              ["OK servo2=target angle=60"])
        match = servo_status("servo2 60 is moving", "SERVO2", state="moving")
        check("servo2 60 starts above its target", int(match.group(3)) > 60, True)
        expect("servo2 stop during movement", b"servo2 stop\n",
               ["OK servo2=stopped output=off"])
        match = servo_status("servo2 stop interrupts movement", "SERVO2",
                             state="stopped", output="off")
        check("servo2 stop reports zero pulse", match.group(5), "0")
        check("servo2 stop keeps an intermediate angle",
              60 < int(match.group(3)) < 120, True)
        expect("servo2 center resumes from the stopped position",
               b"servo2 center\n", ["OK servo2=center angle=90"])
        match = servo_wait_idle("servo2 resumed center reaches 90", "SERVO2")
        check("servo2 resumed center angle", match.group(3), "90")
        check("servo2 resumed output is on", match.group(6), "on")

        # --- experiment 006: independence ---------------------------------
        expect("stop both before independence checks", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])
        servo_status("servo 1 is stopped", "SERVO1", state="stopped", output="off")
        servo_status("servo 2 is stopped", "SERVO2", state="stopped", output="off")
        expect("servo1 center only", b"servo1 center\n",
               ["OK servo1=center angle=90"])
        match1 = servo_wait_idle("servo 1 reaches center alone", "SERVO1")
        check("servo 1 is enabled alone", match1.group(6), "on")
        match2 = servo_status("servo 2 stays stopped", "SERVO2",
                              state="stopped", output="off")
        check("servo1 center pulse width", match1.group(5), "1500")
        check("servo2 stop keeps zero pulse", match2.group(5), "0")
        expect("servo2 stop does not affect servo 1", b"servo2 stop\n",
               ["OK servo2=stopped output=off"])
        match = servo_status("servo 1 survives servo2 stop", "SERVO1",
                             state="idle", output="on")
        check("servo 1 keeps its pulse after servo2 stop", match.group(5), "1500")
        expect("servo1 60 setup for independence test", b"servo1 60\n",
               ["OK servo1=target angle=60"])
        servo_wait_idle("servo 1 setup completes", "SERVO1")
        check("servo1 120 starts a full-travel move",
              send(b"servo1 120\n", 0.02), ["OK servo1=target angle=120"])
        expect("servo2 stop while servo 1 moves", b"servo2 stop\n",
               ["OK servo2=stopped output=off"])
        match = servo_status("servo 1 keeps moving after servo2 stop", "SERVO1")
        check("servo2 stop leaves servo 1 moving", match.group(1), "moving")
        match = servo_wait_idle("servo 1 finishes its own move", "SERVO1")
        check("servo 1 final angle", match.group(3), "120")
        expect("servo2 120 setup for reverse independence test", b"servo2 120\n",
               ["OK servo2=target angle=120"])
        servo_wait_idle("servo 2 setup completes", "SERVO2")
        check("servo2 60 starts a full-travel move",
              send(b"servo2 60\n", 0.02), ["OK servo2=target angle=60"])
        expect("servo1 stop while servo 2 moves", b"servo1 stop\n",
               ["OK servo1=stopped output=off"])
        match = servo_status("servo 2 keeps moving after servo1 stop", "SERVO2")
        check("servo1 stop leaves servo 2 moving", match.group(1), "moving")
        match = servo_wait_idle("servo 2 finishes its own move", "SERVO2")
        check("servo 2 final angle", match.group(3), "60")
        servo_status("servo 1 remains stopped", "SERVO1",
                     state="stopped", output="off")

        # --- experiment 006: both center / stop ---------------------------
        expect("both center from stopped states", b"servo both center\n",
               ["OK servo1=center angle=90", "OK servo2=center angle=90"])
        match1 = servo_wait_idle("servo 1 reaches center", "SERVO1")
        match2 = servo_wait_idle("servo 2 reaches center", "SERVO2")
        check("servo 1 center angle", match1.group(3), "90")
        check("servo 2 center angle", match2.group(3), "90")
        check("both center pulses", (match1.group(5), match2.group(5)),
              ("1500", "1500"))
        check("both outputs are on", (match1.group(6), match2.group(6)),
              ("on", "on"))
        check("opposite extremes before the simultaneous move",
              send(b"servo1 60\nservo2 120\n", 0.05),
              ["OK servo1=target angle=60", "OK servo2=target angle=120"])
        servo_wait_idle("servo 1 reaches 60", "SERVO1")
        servo_wait_idle("servo 2 reaches 120", "SERVO2")
        check("simultaneous targets for both servos",
              send(b"servo1 120\nservo2 60\n", 0.05),
              ["OK servo1=target angle=120", "OK servo2=target angle=60"])
        match1 = servo_status("servo 1 is moving to 120", "SERVO1", state="moving")
        match2 = servo_status("servo 2 is moving to 60", "SERVO2", state="moving")
        check("servo 1 starts below its target", int(match1.group(3)) < 120, True)
        check("servo 2 starts above its target", int(match2.group(3)) > 60, True)
        expect("both stop during movement", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])
        match1 = servo_status("both stop interrupts servo 1", "SERVO1",
                              state="stopped", output="off")
        match2 = servo_status("both stop interrupts servo 2", "SERVO2",
                              state="stopped", output="off")
        check("both stop reports zero pulses",
              (match1.group(5), match2.group(5)), ("0", "0"))
        check("both stop keeps intermediate angles",
              (60 < int(match1.group(3)) < 120 and
               60 < int(match2.group(3)) < 120), True)
        expect("both center resumes both servos", b"servo both center\n",
               ["OK servo1=center angle=90", "OK servo2=center angle=90"])
        match1 = servo_wait_idle("servo 1 resumes to center", "SERVO1")
        match2 = servo_wait_idle("servo 2 resumes to center", "SERVO2")
        check("both resumed centers", (match1.group(3), match2.group(3)),
              ("90", "90"))

        # --- experiment 006: rapid targets and eye concurrency -----------
        check("rapid targets for both servos",
              send(b"servo1 75\nservo1 105\nservo1 center\n"
                   b"servo2 75\nservo2 105\nservo2 center\n", 1.2),
              ["OK servo1=target angle=75", "OK servo1=target angle=105",
               "OK servo1=center angle=90", "OK servo2=target angle=75",
               "OK servo2=target angle=105", "OK servo2=center angle=90"])
        match1 = servo_wait_idle("rapid servo 1 targets settle", "SERVO1")
        match2 = servo_wait_idle("rapid servo 2 targets settle", "SERVO2")
        check("rapid targets end at center",
              (match1.group(3), match2.group(3)), ("90", "90"))
        expect("eyes happy before dual concurrency check", b"eyes happy\n",
               ["OK expression=happy"])
        check("both servos move during eye animation",
              send(b"servo1 60\nservo2 120\n", 0.05),
              ["OK servo1=target angle=60", "OK servo2=target angle=120"])
        match = eyes_status("eyes responds during dual movement", "happy")
        check("eye screen stays active during dual movement",
              match.group(4), "eyes")
        match1 = servo_wait_idle("servo 1 completes during eye animation", "SERVO1")
        match2 = servo_wait_idle("servo 2 completes during eye animation", "SERVO2")
        check("servo 1 final angle during eyes", match1.group(3), "60")
        check("servo 2 final angle during eyes", match2.group(3), "120")
        eyes_status("eyes keeps its expression after dual movement", "happy")
        expect("eyes normal before final state", b"eyes normal\n",
               ["OK expression=normal"])

        # --- final state --------------------------------------------------
        expect("final stop for both servos", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])
        match1 = servo_status("final servo 1 output off", "SERVO1",
                              state="stopped", output="off")
        match2 = servo_status("final servo 2 output off", "SERVO2",
                              state="stopped", output="off")
        check("final servo pulses are zero",
              (match1.group(5), match2.group(5)), ("0", "0"))
        expect("finish off", b"off\n", ["OK state=off pin=48"])
        status("final RGB state", "off")
        oled_status("final screen is the eye screen", "SH1106", "eyes", 1)
        print(f"PASS: {passed} checks; physical eye shapes, emotion readability, "
              f"flash-free display and actual dual-servo movement still require "
              f"user confirmation.", flush=True)
    finally:
        if port.is_open:
            # Terminate any partial/invalid line, then leave a safe, visible state:
            # both servo outputs off, RGB off, normal eye screen.
            port.write(b"\nservo both stop\noff\neyes normal\n")
            port.flush()
            collect(0.4)
            port.close()


if __name__ == "__main__":
    main()
