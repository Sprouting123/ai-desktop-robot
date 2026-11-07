"""Live RGB regression check for experiment 003. Resets this board; leaves LED off.

Run with .venv/bin/python scripts/test_serial_led.py after closing all monitors.
It checks UART responses and recovery, not the physical LED color.
"""

import argparse
import os
import re
import time

import serial
from serial.tools import list_ports

DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00"
HELP = "HELP red | green | blue | off | status | help | i2cscan | oled_sh1106 | oled_ssd1306 | oled_status; max_line=32; endings=LF/CR/CRLF"
TOO_LONG = "ERR line_too_long; max=32; discarded"
INVALID = "ERR invalid_character; use ASCII commands; discarded"
UNKNOWN = "ERR unknown_command; use help"


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
        print(f"PASS {passed:02d} {name}: {actual!r}", flush=True)

    def expect(name, payload, expected, seconds=0.18):
        check(name, send(payload, seconds), expected)

    def status(name, state):
        lines = send(b"status\n")
        pattern = rf"STATUS state={state} pin=48 enabled=1 brightness=24 uptime_ms=\d+"
        check(name, len(lines) == 1 and re.fullmatch(pattern, lines[0]) is not None, True)
        print("  " + lines[0], flush=True)

    try:
        port.open()
        # A deliberate reset makes the initial-off check reproducible.
        port.rts = True
        time.sleep(0.1)
        port.rts = False
        startup = collect(2)
        print("STARTUP\n" + startup, flush=True)
        check("experiment 003 boot identity",
              "[experiment 003] OLED driver comparison / Arduino" in startup, True)
        check("physical memory configuration",
              "flash=16777216 psram_chip=8388608" in startup and "[warning]" not in startup, True)
        status("initial state is off", "off")
        expect("help", b"help\n", [HELP])
        expect("red with LF", b"red\n", ["OK state=red pin=48"])
        status("status after red", "red")
        check("idle produces no cycling output", collect(3.2), "")
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
        expect("33 bytes reject a valid-looking prefix", b"red" + b" " * 30 + b"\r\n", [TOO_LONG])
        status("oversize line preserves blue", "blue")
        expect("4096-byte line discards valid-looking suffix", b"x" * 4096 + b"green\n", [TOO_LONG], 0.3)
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
        check("I2C initialized", "I2C_INIT ready=1 sda=8 scl=9 frequency_hz=100000 timeout_ms=25" in startup, True)
        previous_addresses = None
        for payload in (b"i2cscan\n", b" \tI2CSCAN \r\n"):
            lines = send(payload, 5)
            print("SCAN\n" + "\n".join(lines), flush=True)
            check("scan configuration", lines[0] if lines else "",
                  "I2C_SCAN begin sda=8 scl=9 frequency_hz=100000 range=0x08-0x77")
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
        def oled_status(driver):
            return f"OLED_STATUS driver={driver} address=0x3C draw_called=1 visual=unverified frequency_hz=100000"

        check("boot draws SH1106", oled_status("SH1106") in startup, True)
        for driver, payload in (("SSD1306", b" OLED_SSD1306 \r\n"),
                                ("SH1106", b"oled_sh1106\n")):
            expect(f"switch and draw {driver}", payload,
                   [f"OLED_DRAW driver={driver} address=0x3C probe_after=0 visual=unverified",
                    oled_status(driver)], 1.5)
            expect(f"query {driver}", b"oled_status\n", [oled_status(driver)])
            status(f"{driver} preserves RGB", "red")
            expect(f"scan after {driver}", b"i2cscan\n",
                   ["I2C_SCAN begin sda=8 scl=9 frequency_hz=100000 range=0x08-0x77",
                    "I2C_FOUND address=0x3C",
                    "I2C_SCAN done devices=1 errors=0 result=ok"], 5)
        expect("invalid driver name", b"oled_ssd1306 extra\n", [UNKNOWN])
        expect("oversized display command", b"oled_ssd1306" + b" " * 22 + b"\n", [TOO_LONG])
        expect("invalid display command", b"oled_ssd1306\x00\n", [INVALID])
        expect("rejected commands preserve SH1106", b"oled_status\n", [oled_status("SH1106")])
        expect("finish off", b"off\n", ["OK state=off pin=48"])
        status("final state", "off")
        print(f"PASS: {passed} checks; physical LED colors and OLED display still require user confirmation.")
    finally:
        if port.is_open:
            # Terminate any partial/invalid line before requesting the safe final state.
            port.write(b"\noff\n")
            port.flush()
            collect(0.15)
            port.close()


if __name__ == "__main__":
    main()
