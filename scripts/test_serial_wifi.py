"""Live regression check for experiment 009 (MAX98357A I2S audio).

Run with .venv/bin/python scripts/test_serial_wifi.py after closing all
monitors and with the servos' external 5 V supply disconnected. It regresses
the experiment 002/003/004 commands, both servo channels, the motion/mood
engine, the Wi-Fi/web serial status commands and the audio commands, including the
embedded `hello_zh` PCM clip. When
the board is already connected to Wi-Fi and a token is available locally, it
also exercises the HTTP API and the embedded control page. It resets this
board and leaves the RGB LED off, both servo outputs disabled, audio silent and
the normal eye screen showing.

Every check here is a software/serial observation; it cannot prove the physical
OLED appearance, servo movement or audible sound. Do not use it as the physical
acceptance test, and never run it with the external 5 V supply connected.
"""

import argparse
import http.client
import json
import os
import pathlib
import re
import socket
import time

import serial
from serial.tools import list_ports

DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00"
BOOT = "[experiment 009] MAX98357A I2S audio / Arduino"
HELP = ("HELP red | green | blue | off | status | help | i2cscan | oled_sh1106 | "
        "oled_ssd1306 | oled_status | eyes <normal|happy|angry|sad|embarrassed|"
        "sympathy|comfort|melancholy|left|right> | eyes blink | eyes status | "
        "eyes dump | servo <60-120> | servo center | servo status | servo stop | "
        "servo1 <60-120> | servo1 center | servo1 status | servo1 stop | "
        "servo2 <60-120> | servo2 center | servo2 status | servo2 stop | "
        "servo both center | servo both stop | motion neutral | motion wiggle | "
        "motion together | motion alternate | motion stop | motion status | "
        "mood happy | mood sad | mood angry | mood normal | mood status | "
        "mood stop | wifi status | wifi reconnect | web status | audio beep | "
        "audio hello | audio stop | audio status; max_line=32; "
        "endings=LF/CR/CRLF")
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
MOTION_RE = re.compile(
    r"MOTION name=(none|neutral|wiggle|together|alternate) "
    r"state=(idle|running|stopped) "
    r"phase=(starting|moving|dwell|centering|done|stopped) "
    r"step=(\d+) total=(\d+) "
    r"angle1=(\d+) target1=(\d+) moving1=([01]) output1=(on|off) "
    r"angle2=(\d+) target2=(\d+) moving2=([01]) output2=(on|off)")
MOOD_RE = re.compile(
    r"MOOD mood=(none|normal|happy|sad|angry) expression=(\w+) "
    r"motion=(none|neutral|wiggle|together|alternate)")
WIFI_RE = re.compile(
    r"WIFI state=(disabled|connecting|connected|backoff) ssid_set=([01]) "
    r"ip=([0-9.]+) rssi=(-?\d+) attempts=(\d+) connects=(\d+) retry_in_ms=(-?\d+)")
WEB_RE = re.compile(
    r"WEB listening=([01]) port=80 requests=(\d+) writes=(\d+) "
    r"rejected=(\d+) rate_limited=(\d+) auth=(enabled|disabled)")
AUDIO_RE = re.compile(
    r"AUDIO state=(idle|playing|unavailable) ready=([01]) "
    r"source=(tone|clip|none) clip=(\S+) bytes=(\d+) frames=(\d+) "
    r"driver=i2s_std bclk=(\d+) lrck=(\d+) din=(\d+) rate_hz=(\d+) "
    r"bits=16 channels=2 tone_hz=(\d+) duration_ms=(\d+) amplitude_pct=(\d+) "
    r"plays=(\d+) stops=(\d+) errors=(\d+) last_error=(-?\d+)")
AUDIO_BEEP = ("OK audio=beep tone_hz=880 duration_ms=300 amplitude_pct=15 "
              "restarted={0}")
AUDIO_HELLO = ("OK audio=hello clip=hello_zh bytes=78828 frames=39414 "
               "duration_ms=2463 volume_pct=60 sample_rate_hz=16000 "
               "restarted={0}")
TOKEN_RE = re.compile(r'^\s*#define\s+API_TOKEN\s+"([^"]+)"', re.MULTILINE)
# Log lines the firmware prints on its own schedule. They may land inside any
# serial command window and are not a response to that command.
ASYNC_PREFIXES = ("WIFI_CONNECTING ", "WIFI_TIMEOUT ", "WIFI_RETRY ",
                  "WIFI_LOST ", "WIFI_CONNECTED ", "WIFI_RECONNECT ",
                  "WIFI_DISABLED ", "WEB_LISTEN ", "WEB_AUTH ")


def load_token(path):
    """Read the local untracked token without printing or logging it."""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    match = TOKEN_RE.search(text)
    return match.group(1) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument(
        "--token-file",
        default=str(pathlib.Path(__file__).resolve().parent.parent / "src" / "secrets.h"),
        help="local untracked file used to read API_TOKEN for HTTP checks")
    parser.add_argument("--no-http", action="store_true",
                        help="skip HTTP checks even when Wi-Fi is connected")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="skip the Wi-Fi reconnect check")
    parser.add_argument(
        "--no-audio-sound", action="store_true",
        help="skip the checks that make the speaker sound; the first tone and "
             "voice must be started by the user, so use this before the "
             "physical listening test")
    args = parser.parse_args()
    api_token = load_token(args.token_file)
    if api_token is not None and len(api_token) < 16:
        api_token = None
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
        return [line for line in collect(seconds).splitlines()
                if line and not line.startswith(ASYNC_PREFIXES)]

    def check(name, actual, expected):
        nonlocal passed
        if actual != expected:
            raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")
        passed += 1
        print(f"PASS {passed:03d} {name}: {actual!r}", flush=True)

    def expect(name, payload, expected, seconds=0.18):
        check(name, send(payload, seconds), expected)

    def status(name, state):
        lines = [line for line in send(b"status\n") if line.startswith("STATUS ")]
        pattern = rf"STATUS state={state} pin=48 enabled=1 brightness=24 uptime_ms=\d+"
        check(name, len(lines) == 1 and re.fullmatch(pattern, lines[0]) is not None, True)
        print("  " + lines[0], flush=True)

    def oled_status(name, driver, screen, draw_called):
        lines = [line for line in send(b"oled_status\n")
                 if line.startswith("OLED_STATUS ")]
        pattern = (rf"OLED_STATUS driver={driver} address=0x3C draw_called={draw_called} "
                   rf"visual=unverified frequency_hz=100000 screen={screen}")
        check(name, len(lines) == 1 and re.fullmatch(pattern, lines[0]) is not None, True)
        print("  " + lines[0], flush=True)

    def eyes_status(name, expression=None, mode="eyes"):
        lines = [line for line in send(b"eyes status\n") if line.startswith("EYES ")]
        match = STATUS_RE.fullmatch(lines[0]) if len(lines) == 1 else None
        check(name, match is not None, True)
        if expression is not None:
            check(f"{name} expression", match.group(1), expression)
        check(f"{name} mode", match.group(4), mode)
        print("  " + lines[0], flush=True)
        return match

    def servo_status(name, prefix="SERVO1", state=None, output=None):
        lines = [line for line in send(SERVO_STATUS_COMMAND[prefix])
                 if line.startswith(prefix + " ")]
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

    def motion_status(name):
        lines = [line for line in send(b"motion status\n")
                 if line.startswith("MOTION ")]
        match = MOTION_RE.fullmatch(lines[0]) if len(lines) == 1 else None
        check(name, match is not None, True)
        print("  " + lines[0], flush=True)
        return match

    def motion_wait(name, state, timeout=18.0):
        deadline = time.monotonic() + timeout
        match = motion_status(name)
        while match.group(2) != state and time.monotonic() < deadline:
            time.sleep(0.15)
            match = motion_status(name)
        check(f"{name} reaches {state}", match.group(2), state)
        return match

    def mood_status(name):
        lines = send(b"mood status\n")
        mood_lines = [line for line in lines if line.startswith("MOOD ")]
        motion_lines = [line for line in lines if line.startswith("MOTION ")]
        mood_match = MOOD_RE.fullmatch(mood_lines[0]) if len(mood_lines) == 1 else None
        motion_match = (MOTION_RE.fullmatch(motion_lines[0])
                        if len(motion_lines) == 1 else None)
        check(name, mood_match is not None and motion_match is not None, True)
        for line in lines:
            print("  " + line, flush=True)
        return mood_match, motion_match

    def check_motion_angles(name, match, low, high):
        angles = (int(match.group(6)), int(match.group(10)))
        targets = (int(match.group(7)), int(match.group(11)))
        check(f"{name} angles within {low}-{high}",
              all(low <= a <= high for a in angles), True)
        check(f"{name} targets within {low}-{high}",
              all(low <= t <= high for t in targets), True)

    def eyes_dump(name, expression):
        lines = send(b"eyes dump\n", 0.9)
        headers = [line for line in lines if DUMP_RE.fullmatch(line)]
        header = DUMP_RE.fullmatch(headers[0]) if len(headers) == 1 else None
        check(f"{name} dump header", header is not None, True)
        check(f"{name} dump expression", header.group(1), expression)
        grid = [line for line in lines if re.fullmatch(r"[.#]{64}", line)]
        check(f"{name} dump rows", len(grid), 32)
        check(f"{name} dump width", all(len(row) == 64 for row in grid), True)
        check(f"{name} dump uses only known glyphs",
              all(re.fullmatch(r"[.#]{64}", row) is not None for row in grid), True)
        check(f"{name} dump is not blank", any("#" in row for row in grid), True)
        print("  " + lines[0], flush=True)
        return header.group(4)

    board_ip = None

    def read_wifi():
        lines = [line for line in send(b"wifi status\n")
                 if line.startswith("WIFI ")]
        match = WIFI_RE.fullmatch(lines[0]) if len(lines) == 1 else None
        return match, lines

    def wifi_status(name):
        match, lines = read_wifi()
        check(name, match is not None, True)
        print("  " + (lines[0] if lines else "<no wifi status>"), flush=True)
        return match

    def web_status(name):
        lines = [line for line in send(b"web status\n")
                 if line.startswith("WEB ")]
        match = WEB_RE.fullmatch(lines[0]) if len(lines) == 1 else None
        check(name, match is not None, True)
        print("  " + lines[0], flush=True)
        return match

    def audio_status(name, state=None, seconds=0.18):
        lines = [line for line in send(b"audio status\n", seconds)
                 if line.startswith("AUDIO ")]
        match = AUDIO_RE.fullmatch(lines[0]) if len(lines) == 1 else None
        check(name, match is not None, True)
        if state is not None:
            check(f"{name} state", match.group(1), state)
        print("  " + lines[0], flush=True)
        return match

    def web_listening(name, timeout=10.0):
        deadline = time.monotonic() + timeout
        match = web_status(name)
        while match.group(1) != "1" and time.monotonic() < deadline:
            time.sleep(0.3)
            match = web_status(name)
        check(f"{name} listening", match.group(1), "1")
        return match

    def http_request(method, path, payload=None, token=None, headers=None,
                     timeout=4.0):
        connection = http.client.HTTPConnection(board_ip, 80, timeout=timeout)
        request_headers = {"Connection": "close"}
        if headers:
            request_headers.update(headers)
        if token is not None:
            request_headers["X-Auth-Token"] = token
        body = None
        if payload is not None:
            body = payload.encode("utf-8") if isinstance(payload, str) else payload
            request_headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            status = response.status
            text = response.read().decode("utf-8", "replace")
            response_headers = dict(response.getheaders())
            return status, text, response_headers
        finally:
            connection.close()

    def raw_http(payload, timeout=4.0):
        chunks = []
        with socket.create_connection((board_ip, 80), timeout=timeout) as sock:
            try:
                sock.sendall(payload)
            except OSError:
                pass
            sock.settimeout(timeout)
            while True:
                try:
                    chunk = sock.recv(4096)
                except (socket.timeout, ConnectionResetError, OSError):
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", "replace")

    def no_token(name, text):
        check(name, bool(api_token) and api_token in text, False)

    try:
        port.open()
        # A deliberate reset makes the initial state reproducible.
        port.rts = True
        time.sleep(0.1)
        port.rts = False
        startup = collect(2.5)
        print("STARTUP\n" + startup, flush=True)
        check("experiment 008 boot identity", BOOT in startup, True)
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

        # --- experiment 008 network boot state ----------------------------
        wifi_boot = wifi_status("boot Wi-Fi status")
        web_boot = web_status("boot web status")
        if wifi_boot.group(2) == "0":
            check("boot Wi-Fi is disabled without credentials",
                  wifi_boot.group(1), "disabled")
            check("boot web is not listening without Wi-Fi",
                  web_boot.group(1), "0")
            check("empty credentials produce WIFI_DISABLED",
                  "WIFI_DISABLED ssid_set=0 reason=no_credentials" in startup, True)
        else:
            check("boot build has an SSID configured", wifi_boot.group(2), "1")
        if api_token:
            check("boot web auth is enabled for the local token",
                  web_boot.group(6), "enabled")
        check("boot logs the web auth state", "WEB_AUTH state=" in startup, True)
        no_token("startup log", startup)
        no_token("web status line", " ".join(web_boot.groups()))
        expect("wifi command needs a subcommand", b"wifi\n",
               ["ERR wifi_usage; use help"])
        expect("wifi rejects unknown subcommands", b"wifi scan\n",
               ["ERR wifi_usage; use help"])
        expect("web command needs a subcommand", b"web\n",
               ["ERR web_usage; use help"])
        expect("web rejects unknown subcommands", b"web start\n",
               ["ERR web_usage; use help"])
        if wifi_boot.group(2) == "0":
            expect("wifi reconnect is rejected without credentials", b"wifi reconnect\n",
                   ["ERR wifi_disabled; fill in src/secrets.h and rebuild"])

        # --- experiment 009 audio -----------------------------------------
        check("audio I2S driver initializes silent",
              "AUDIO_INIT ready=1 driver=i2s_std port=0 bclk=7 lrck=15 din=6 "
              "rate_hz=16000 bits=16 channels=2 dma=4 x 240 frames "
              "tone_hz=880 duration_ms=300 amplitude_pct=15" in startup, True)
        check("embedded voice clip metadata",
              "AUDIO_CLIP name=hello_zh bytes=78828 frames=39414 "
              "sample_rate_hz=16000 volume_pct=60" in startup, True)
        audio_boot = audio_status("boot audio is idle", "idle")
        check("boot audio driver is ready", audio_boot.group(2), "1")
        check("boot audio has no active source",
              (audio_boot.group(3), audio_boot.group(4),
               audio_boot.group(5), audio_boot.group(6)),
              ("none", "-", "0", "0"))
        check("audio uses the documented pins",
              (audio_boot.group(7), audio_boot.group(8), audio_boot.group(9)),
              ("7", "15", "6"))
        check("audio uses the standard first-test format",
              (audio_boot.group(10), audio_boot.group(11),
               audio_boot.group(12), audio_boot.group(13)),
              ("16000", "880", "300", "15"))
        check("boot does not play a tone", audio_boot.group(14), "0")
        check("boot audio reports no error",
              (audio_boot.group(16), audio_boot.group(17)), ("0", "0"))
        expect("audio needs a subcommand", b"audio\n",
               ["ERR audio_usage; use help"])
        expect("audio rejects unknown subcommands", b"audio play\n",
               ["ERR audio_usage; use help"])
        expect("audio rejects extra arguments", b"audio beep now\n",
               ["ERR audio_usage; use help"])
        expect("audio hello rejects extra arguments", b"audio hello now\n",
               ["ERR audio_usage; use help"])
        expect("audio stop is safe while idle", b"audio stop\n",
               ["OK audio=stopped output=silent"])
        check("a rejected audio command does not start playback",
              audio_status("still idle after usage errors", "idle").group(14), "0")

        if args.no_audio_sound:
            print("SKIP audio playback checks (--no-audio-sound); the first "
                  "tone and voice must be started by the user", flush=True)
        else:
            # Short observation windows: the 300 ms tone must still be
            # streaming while these commands are answered, which also shows the
            # I2S writes do not block the command loop.
            expect("audio beep acknowledged", b"audio beep\n",
                   [AUDIO_BEEP.format("0")], 0.06)
            states = [audio_status(f"audio status during playback {index}",
                                   seconds=0.05).group(1) for index in range(3)]
            check("audio reports continuous playback", states,
                  ["playing", "playing", "playing"])
            motion_while_audio = [line for line in send(b"motion status\n", 0.06)
                                  if line.startswith("MOTION ")]
            check("motion answers while a tone plays", len(motion_while_audio), 1)
            check("a beep does not start a motion",
                  motion_while_audio[0].split()[1].split("=")[1], "none")
            time.sleep(0.4)
            audio_status("the tone finishes without a command", "idle")

            expect("audio beep after a finished tone", b"audio beep\n",
                   [AUDIO_BEEP.format("0")], 0.06)
            expect("audio beep restarts while playing", b"audio beep\n",
                   [AUDIO_BEEP.format("1")], 0.06)
            restarted = audio_status("restart keeps playing", "playing", 0.05)
            check("every trigger incremented the play counter",
                  int(restarted.group(14)) >= 3, True)
            expect("audio stop interrupts playback", b"audio stop\n",
                   ["OK audio=stopped output=silent"])
            stopped = audio_status("audio stop returns to idle", "idle")
            check("stop counter advanced", int(stopped.group(15)) >= 1, True)
            check("audio errors stay at zero after stop",
                  (stopped.group(16), stopped.group(17)), ("0", "0"))
            time.sleep(0.4)
            check("a stopped tone does not resume by itself",
                  audio_status("still idle after wait", "idle").group(14),
                  stopped.group(14))

            # --- embedded voice clip --------------------------------------
            # The clip is 2.463 s long, long enough for several commands to be
            # answered while it streams.
            expect("audio hello acknowledged", b"audio hello\n",
                   [AUDIO_HELLO.format("0")], 0.06)
            hello = audio_status("hello reports a clip source", "playing", 0.05)
            check("hello source is the embedded clip",
                  (hello.group(3), hello.group(4), hello.group(5),
                   hello.group(6)),
                  ("clip", "hello_zh", "78828", "39414"))
            eyes_status("OLED answers while the voice plays")
            motion_while_voice = [line for line in send(b"motion status\n", 0.06)
                                  if line.startswith("MOTION ")]
            check("motion answers while the voice plays",
                  len(motion_while_voice), 1)
            check("audio hello does not start a motion",
                  motion_while_voice[0].split()[1].split("=")[1], "none")
            expect("audio hello restarts while playing", b"audio hello\n",
                   [AUDIO_HELLO.format("1")], 0.06)
            check("repeated hello keeps the same clip length",
                  audio_status("hello restart keeps playing", "playing",
                               0.05).group(5), "78828")
            expect("audio stop interrupts the voice", b"audio stop\n",
                   ["OK audio=stopped output=silent"])
            voice_stopped = audio_status("voice stop returns to idle", "idle")
            check("stopping the voice clears the source",
                  (voice_stopped.group(3), voice_stopped.group(4)),
                  ("none", "-"))
            time.sleep(0.5)
            check("a stopped voice does not resume by itself",
                  audio_status("voice still idle after wait", "idle").group(14),
                  voice_stopped.group(14))

            # A fully natural finish must wait for the DMA tail and must not
            # count as an explicit stop.
            expect("audio hello replays from the start", b"audio hello\n",
                   [AUDIO_HELLO.format("0")], 0.06)
            time.sleep(2.7)
            finished = audio_status("hello finishes without a command", "idle")
            check("natural finish waits for the queued tail",
                  int(finished.group(14)), int(voice_stopped.group(14)) + 1)
            check("natural finish is not counted as a stop",
                  finished.group(15), voice_stopped.group(15))
            check("audio errors stay at zero after the voice",
                  (finished.group(16), finished.group(17)), ("0", "0"))
            check("voice playback did not leak heap",
                  int(eyes_status("heap after the voice").group(11)) > 50000,
                  True)

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
            raw = send(payload, 5)
            print("SCAN\n" + "\n".join(raw), flush=True)
            lines = [line for line in raw if line.startswith("I2C_")]
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

        # --- experiment 006 phase 2: motion parsing and initial state -----
        rest = motion_status("motion starts idle after manual moves")
        check("motion has no name at rest", rest.group(1), "none")
        check("motion is idle at rest", rest.group(2), "idle")
        check("motion has no pending steps",
              (rest.group(4), rest.group(5)), ("0", "0"))
        check("motion reports both outputs on after manual moves",
              (rest.group(9), rest.group(13)), ("on", "on"))
        check_motion_angles("resting poses", rest, 60, 120)
        expect("motion with no argument", b"motion\n",
               ["ERR motion_usage; use help"])
        expect("unknown motion", b"motion sway\n",
               ["ERR motion_usage; use help"])
        expect("motion extra argument", b"motion stop extra\n",
               ["ERR motion_usage; use help"])
        expect("near-miss motion name", b"motion alternates\n",
               ["ERR motion_usage; use help"])
        expect("oversized motion command",
               b"motion alternate" + b" " * 18 + b"\n", [TOO_LONG])
        expect("invalid motion command", b"motion wiggle\x00\n", [INVALID])
        after_bad = motion_status("rejected motion commands change nothing")
        check("rejected motion keeps the idle name", after_bad.group(1), "none")
        check("rejected motion keeps both outputs on",
              (after_bad.group(9), after_bad.group(13)), ("on", "on"))

        # --- experiment 006 phase 2: neutral ------------------------------
        expect("motion neutral", b"motion neutral\n",
               ["OK motion=neutral steps=1"])
        neutral = motion_wait("neutral", "idle", timeout=5)
        check("neutral clears the name", neutral.group(1), "none")
        check("neutral ends with no pending steps",
              (neutral.group(4), neutral.group(5)), ("0", "0"))
        check("neutral ends at 90/90",
              (neutral.group(6), neutral.group(10)), ("90", "90"))
        check("neutral leaves both outputs holding",
              (neutral.group(9), neutral.group(13)), ("on", "on"))

        # --- experiment 006 phase 2: wiggle, stop and OLED concurrency ----
        expect("motion wiggle", b"motion wiggle\n",
               ["OK motion=wiggle steps=24"])
        wiggle = motion_status("wiggle starts running")
        check("wiggle name", wiggle.group(1), "wiggle")
        check("wiggle state", wiggle.group(2), "running")
        check("wiggle total steps", wiggle.group(5), "24")
        check("wiggle step inside the sequence",
              1 <= int(wiggle.group(4)) <= 24, True)
        start_blinks = int(eyes_status("eyes stay active during motion",
                                       "normal").group(6))
        samples = [wiggle]
        for _ in range(16):
            time.sleep(0.35)
            samples.append(motion_status("wiggle polling"))
        check("wiggle stays running while polled",
              all(s.group(2) == "running" for s in samples), True)
        check("wiggle steps advance",
              len({s.group(4) for s in samples}) > 1, True)
        for sample in samples:
            check_motion_angles("wiggle safety", sample, 75, 105)
        during = eyes_status("eyes animation still runs during wiggle", "normal")
        check("auto blink occurs during motion",
              int(during.group(6)) >= start_blinks + 1, True)
        check("OLED transfer remains non-blocking during motion",
              int(during.group(10)) < 20000, True)
        expect("motion stop during wiggle", b"motion stop\n",
               ["OK motion=stopped output=off"])
        stopped = motion_status("motion stop clears the sequence")
        check("stopped motion has no name", stopped.group(1), "none")
        check("stopped motion state", stopped.group(2), "stopped")
        check("stopped motion phase", stopped.group(3), "stopped")
        check("stopped motion has no pending steps",
              (stopped.group(4), stopped.group(5)), ("0", "0"))
        check("stopped motion has both outputs off",
              (stopped.group(9), stopped.group(13)), ("off", "off"))
        check_motion_angles("motion stop leaves safe angles", stopped, 60, 120)
        servo_status("motion stop stopped servo 1", "SERVO1",
                     state="stopped", output="off")
        servo_status("motion stop stopped servo 2", "SERVO2",
                     state="stopped", output="off")
        time.sleep(1.0)
        still = motion_status("stopped motion does not resume")
        check("no old step is replayed", still.group(2), "stopped")
        check("no old name is restored", still.group(1), "none")

        # --- experiment 006 phase 2: switching and completion -------------
        expect("start alternate before switching", b"motion alternate\n",
               ["OK motion=alternate steps=10"])
        time.sleep(0.5)
        before = motion_status("alternate is running before the switch")
        check("alternate name", before.group(1), "alternate")
        expect("together replaces alternate", b"motion together\n",
               ["OK motion=together steps=10"])
        switched = motion_status("new motion resets the step counter")
        check("together name after switch", switched.group(1), "together")
        check("together restarts at step 1", switched.group(4), "1")
        check("together total steps", switched.group(5), "10")
        done = motion_wait("together completes", "idle", timeout=18)
        check("completed motion clears the name", done.group(1), "none")
        check("completed motion is idle", done.group(2), "idle")
        check("completed motion ends at center",
              (done.group(6), done.group(10)), ("90", "90"))
        check("completed motion holds both outputs",
              (done.group(9), done.group(13)), ("on", "on"))

        # --- experiment 006 phase 2: manual takeover ----------------------
        expect("start wiggle before manual takeover", b"motion wiggle\n",
               ["OK motion=wiggle steps=24"])
        time.sleep(0.5)
        expect("manual servo1 target during motion", b"servo1 80\n",
               ["OK servo1=target angle=80"])
        takeover = motion_status("manual command cancels the sequence")
        check("manual takeover clears the motion name", takeover.group(1), "none")
        check("manual takeover leaves the engine idle", takeover.group(2), "idle")
        check("manual takeover leaves the untouched servo enabled",
              takeover.group(13), "on")
        check("manual takeover keeps the untouched servo at center",
              takeover.group(10), "90")
        check("manual takeover enables the commanded servo",
              takeover.group(9), "on")
        check("manual takeover targets the requested angle", takeover.group(7), "80")
        servo_wait_idle("manual takeover reaches 80", "SERVO1")
        expect("both stop after takeover", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])

        # --- experiment 006 phase 2: servo both stop clears motion --------
        expect("start alternate before both stop", b"motion alternate\n",
               ["OK motion=alternate steps=10"])
        time.sleep(0.3)
        expect("servo both stop during motion", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])
        cleared = motion_status("servo both stop clears the motion engine")
        check("both stop clears the name", cleared.group(1), "none")
        check("both stop motion state", cleared.group(2), "stopped")
        check("both stop outputs",
              (cleared.group(9), cleared.group(13)), ("off", "off"))

        # --- experiment 006 phase 2: mood parsing -------------------------
        expect("center both before mood tests", b"servo both center\n",
               ["OK servo1=center angle=90", "OK servo2=center angle=90"])
        servo_wait_idle("mood setup servo 1", "SERVO1")
        servo_wait_idle("mood setup servo 2", "SERVO2")
        expect("mood with no argument", b"mood\n",
               ["ERR mood_usage; use help"])
        expect("unknown mood", b"mood excited\n",
               ["ERR mood_usage; use help"])
        expect("mood extra argument", b"mood happy extra\n",
               ["ERR mood_usage; use help"])
        expect("oversized mood command",
               b"mood happy" + b" " * 23 + b"\n", [TOO_LONG])
        expect("invalid mood command", b"mood sad\x00\n", [INVALID])
        quiet_mood, quiet_motion = mood_status("mood status at rest")
        check("no mood at rest", quiet_mood.group(1), "none")
        check("mood status still reports the expression",
              quiet_mood.group(2), "normal")
        check("mood status reports no motion", quiet_mood.group(3), "none")
        check("quiet mood motion is idle", quiet_motion.group(2), "idle")

        # --- experiment 006 phase 2: happy -------------------------------
        expect("mood happy", b"mood happy\n",
               ["OK mood=happy expression=happy motion=wiggle"])
        happy_mood, happy_motion = mood_status("mood happy status")
        check("happy mood label", happy_mood.group(1), "happy")
        check("happy expression", happy_mood.group(2), "happy")
        check("happy motion name", happy_mood.group(3), "wiggle")
        check("happy motion running", happy_motion.group(2), "running")
        check("happy total steps", happy_motion.group(5), "16")
        eyes_status("happy eyes are active", "happy")
        happy_samples = []
        for _ in range(6):
            time.sleep(0.3)
            happy_samples.append(motion_status("happy motion polling"))
        for sample in happy_samples:
            check_motion_angles("happy gentle range", sample, 80, 100)
        expect("mood stop from happy", b"mood stop\n",
               ["OK mood=stopped output=off screen=kept expression=happy"])
        happy_stop, happy_stop_motion = mood_status("mood stop keeps the face")
        check("mood stop clears the mood", happy_stop.group(1), "none")
        check("mood stop keeps the happy face", happy_stop.group(2), "happy")
        check("mood stop reports no motion", happy_stop.group(3), "none")
        check("mood stop motion state", happy_stop_motion.group(2), "stopped")
        check("mood stop outputs",
              (happy_stop_motion.group(9), happy_stop_motion.group(13)),
              ("off", "off"))
        eyes_status("face remains happy after mood stop", "happy")

        # --- experiment 006 phase 2: sad ---------------------------------
        expect("center before sad", b"servo both center\n",
               ["OK servo1=center angle=90", "OK servo2=center angle=90"])
        servo_wait_idle("sad setup servo 1", "SERVO1")
        servo_wait_idle("sad setup servo 2", "SERVO2")
        expect("mood sad", b"mood sad\n",
               ["OK mood=sad expression=sad motion=wiggle"])
        sad_mood, sad_motion = mood_status("mood sad status")
        check("sad mood label", sad_mood.group(1), "sad")
        check("sad expression", sad_mood.group(2), "sad")
        check("sad motion name", sad_mood.group(3), "wiggle")
        check("sad total steps", sad_motion.group(5), "12")
        eyes_status("sad eyes are active", "sad")
        sad_samples = []
        for _ in range(5):
            time.sleep(0.3)
            sad_samples.append(motion_status("sad motion polling"))
        for sample in sad_samples:
            check_motion_angles("sad small range", sample, 85, 95)
        expect("mood stop from sad", b"mood stop\n",
               ["OK mood=stopped output=off screen=kept expression=sad"])

        # --- experiment 006 phase 2: angry -------------------------------
        expect("center before angry", b"servo both center\n",
               ["OK servo1=center angle=90", "OK servo2=center angle=90"])
        servo_wait_idle("angry setup servo 1", "SERVO1")
        servo_wait_idle("angry setup servo 2", "SERVO2")
        expect("mood angry", b"mood angry\n",
               ["OK mood=angry expression=angry motion=alternate"])
        angry_mood, angry_motion = mood_status("mood angry status")
        check("angry mood label", angry_mood.group(1), "angry")
        check("angry expression", angry_mood.group(2), "angry")
        check("angry motion name", angry_mood.group(3), "alternate")
        check("angry total steps", angry_motion.group(5), "8")
        eyes_status("angry eyes are active", "angry")
        angry_samples = []
        for _ in range(5):
            time.sleep(0.3)
            angry_samples.append(motion_status("angry motion polling"))
        for sample in angry_samples:
            check_motion_angles("angry short range", sample, 82, 98)
        expect("mood stop from angry", b"mood stop\n",
               ["OK mood=stopped output=off screen=kept expression=angry"])

        # --- experiment 006 phase 2: normal ------------------------------
        expect("mood normal", b"mood normal\n",
               ["OK mood=normal expression=normal motion=neutral"])
        normal_mood, normal_motion = mood_status("mood normal status")
        check("normal mood label", normal_mood.group(1), "normal")
        check("normal expression", normal_mood.group(2), "normal")
        # Neutral can finish before the status reply is read; both the active
        # and the already-finished form are correct here.
        check("normal motion name", normal_mood.group(3) in ("neutral", "none"), True)
        settled = motion_wait("normal mood settles", "idle", timeout=5)
        normal_mood, normal_motion = mood_status("normal mood after settling")
        check("normal mood is retained", normal_mood.group(1), "normal")
        check("normal expression is retained", normal_mood.group(2), "normal")
        check("normal motion is finished", normal_mood.group(3), "none")
        check("normal returns to center",
              (settled.group(6), settled.group(10)), ("90", "90"))

        # --- experiment 006 phase 2: interruption rules -------------------
        expect("mood happy before an eyes override", b"mood happy\n",
               ["OK mood=happy expression=happy motion=wiggle"])
        expect("eyes command overrides only the face", b"eyes sad\n",
               ["OK expression=sad"])
        override_mood, override_motion = mood_status(
            "eyes command clears the mood label but not the motion")
        check("eyes override clears the mood", override_mood.group(1), "none")
        check("eyes override changes the expression", override_mood.group(2), "sad")
        check("eyes override leaves the motion running",
              override_mood.group(3), "wiggle")
        check("eyes override motion still runs", override_motion.group(2), "running")
        expect("stop after the eyes override", b"motion stop\n",
               ["OK motion=stopped output=off"])

        expect("mood happy before a motion override", b"mood happy\n",
               ["OK mood=happy expression=happy motion=wiggle"])
        expect("motion replaces the mood", b"motion alternate\n",
               ["OK motion=alternate steps=10"])
        motion_override, motion_override_state = mood_status(
            "motion command clears the mood label")
        check("motion override clears the mood", motion_override.group(1), "none")
        check("motion override keeps the happy face", motion_override.group(2), "happy")
        check("motion override reports alternate",
              motion_override.group(3), "alternate")
        check("motion override is running",
              motion_override_state.group(2), "running")
        expect("stop after the motion override", b"motion stop\n",
               ["OK motion=stopped output=off"])

        expect("mood happy before a manual servo", b"mood happy\n",
               ["OK mood=happy expression=happy motion=wiggle"])
        time.sleep(0.3)
        expect("manual servo2 during mood", b"servo2 80\n",
               ["OK servo2=target angle=80"])
        manual_mood, manual_motion = mood_status(
            "manual servo clears the mood and the sequence")
        check("manual servo clears the mood", manual_mood.group(1), "none")
        check("manual servo leaves no motion name", manual_mood.group(3), "none")
        check("manual servo leaves the engine idle", manual_motion.group(2), "idle")
        check("manual servo enables servo 2", manual_motion.group(13), "on")
        check("manual servo targets 80", manual_motion.group(11), "80")
        servo_wait_idle("manual servo settles after mood", "SERVO2")
        expect("both stop after the manual mood override", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])

        expect("mood sad before both stop", b"mood sad\n",
               ["OK mood=sad expression=sad motion=wiggle"])
        time.sleep(0.3)
        expect("servo both stop clears a mood", b"servo both stop\n",
               ["OK servo1=stopped output=off", "OK servo2=stopped output=off"])
        both_mood, both_motion = mood_status(
            "servo both stop clears the mood and motion")
        check("both stop clears the mood", both_mood.group(1), "none")
        check("both stop keeps the sad face", both_mood.group(2), "sad")
        check("both stop clears the motion name", both_mood.group(3), "none")
        check("both stop motion state", both_motion.group(2), "stopped")
        check("both stop outputs", (both_motion.group(9), both_motion.group(13)),
              ("off", "off"))

        expect("start together before invalid commands", b"motion together\n",
               ["OK motion=together steps=10"])
        time.sleep(0.3)
        expect("invalid motion does not cancel the sequence", b"motion sway\n",
               ["ERR motion_usage; use help"])
        running = motion_status("invalid motion leaves together running")
        check("invalid motion keeps the name", running.group(1), "together")
        check("invalid motion keeps the state", running.group(2), "running")
        expect("invalid servo does not cancel the sequence", b"servo1 abc\n",
               ["ERR servo_usage; use help"])
        running = motion_status("invalid servo leaves together running")
        check("invalid servo keeps the motion name", running.group(1), "together")
        check("invalid servo keeps the motion state", running.group(2), "running")
        expect("stop after the invalid commands", b"motion stop\n",
               ["OK motion=stopped output=off"])
        expect("restore normal eyes before final state", b"eyes normal\n",
               ["OK expression=normal"])

        # --- experiment 008: HTTP API and embedded page -------------------
        # The firmware never blocks its loop while Wi-Fi connects or retries;
        # the wait here only paces the test itself.
        wifi_now = wifi_boot
        if wifi_now.group(1) != "connected" and wifi_now.group(2) == "1":
            deadline = time.monotonic() + 25.0
            while time.monotonic() < deadline:
                time.sleep(0.5)
                candidate, _ = read_wifi()
                if candidate is not None and candidate.group(1) == "connected":
                    wifi_now = candidate
                    break
        wifi_ready = wifi_now.group(1) == "connected"
        if wifi_ready:
            board_ip = wifi_now.group(3)
            check("Wi-Fi reports a usable LAN address",
                  board_ip.count(".") == 3 and board_ip != "0.0.0.0", True)
            check("Wi-Fi reports a plausible RSSI",
                  -100 <= int(wifi_now.group(4)) <= -10, True)

        http_ready = wifi_ready and api_token is not None and not args.no_http
        if not http_ready:
            reason = ("--no-http" if args.no_http else
                      "no-credentials" if wifi_now.group(2) == "0" else
                      "wifi-not-connected" if not wifi_ready else "no-token")
            print(f"SKIP HTTP checks ({reason})", flush=True)
        else:
            http_bodies = []
            # The listener starts in the same loop that observes the new
            # connection, so confirm it before the first HTTP request.
            web_listening("web listens once Wi-Fi is up")

            # --- control page -------------------------------------------
            code, body, headers = http_request("GET", "/")
            http_bodies.append(body)
            check("control page HTTP status", code, 200)
            check("control page content type",
                  headers.get("Content-Type"), "text/html; charset=utf-8")
            check("control page sends a CSP",
                  "Content-Security-Policy" in headers, True)
            check("control page has no external resource",
                  "http://" not in body and "https://" not in body, True)
            check("control page has a stop button", 'id="stop"' in body, True)
            check("control page offers every mood",
                  all(f'data-mood="{name}"' in body
                      for name in ("happy", "sad", "angry", "normal")), True)
            check("control page offers every motion",
                  all(f'data-motion="{name}"' in body
                      for name in ("wiggle", "together", "alternate")), True)
            check("control page never embeds the token", api_token in body, False)
            check("control page stores no persistent token",
                  "localStorage" not in body and "sessionStorage" not in body, True)

            # --- status API ---------------------------------------------
            code, body, headers = http_request("GET", "/api/status")
            http_bodies.append(body)
            check("status API HTTP code", code, 200)
            check("status API content type",
                  headers.get("Content-Type"), "application/json")
            data = json.loads(body)
            check("status API ok", data.get("ok"), True)
            check("status API Wi-Fi state", data["wifi"]["state"], "connected")
            check("status API Wi-Fi address", data["wifi"]["ip"], board_ip)
            check("status API reports uptime",
                  isinstance(data["uptime_ms"], int) and data["uptime_ms"] > 0, True)
            check("status API reports an expression",
                  data["expression"] in EXPRESSIONS, True)
            check("status API reports a mood",
                  data["mood"] in ("none", "normal", "happy", "sad", "angry"), True)
            check("status API reports a motion name",
                  data["motion"]["name"] in
                  ("none", "neutral", "wiggle", "together", "alternate"), True)
            check("status API reports a motion state",
                  data["motion"]["state"] in ("idle", "running", "stopped"), True)
            for key, channel in (("servo1", 0), ("servo2", 1)):
                servo = data[key]
                check(f"status API {key} channel", servo["channel"], channel)
                check(f"status API {key} ready", servo["ready"], 1)
                check(f"status API {key} angle range",
                      60 <= servo["angle"] <= 120, True)
                check(f"status API {key} target range",
                      60 <= servo["target"] <= 120, True)
                check(f"status API {key} output flag",
                      servo["output"] in ("on", "off"), True)

            # --- authorization ------------------------------------------
            code, body, _ = http_request("POST", "/api/mood", '{"name":"happy"}')
            http_bodies.append(body)
            check("mood without a token is rejected", code, 401)
            check("missing token error", json.loads(body)["error"], "missing_token")
            code, body, _ = http_request("POST", "/api/mood", '{"name":"happy"}',
                                         token="0" * 32)
            http_bodies.append(body)
            check("mood with a wrong token is rejected", code, 403)
            check("wrong token error", json.loads(body)["error"], "invalid_token")
            mood_after, _ = mood_status("rejected writes change nothing")
            check("rejected writes keep the mood empty", mood_after.group(1), "none")
            check("rejected writes keep the normal face",
                  mood_after.group(2), "normal")

            # --- reusing the shared mood controller ----------------------
            code, body, _ = http_request("POST", "/api/mood",
                                         '{"name":"happy"}', token=api_token)
            http_bodies.append(body)
            check("HTTP mood HTTP code", code, 200)
            reply = json.loads(body)
            check("HTTP mood reply",
                  (reply["mood"], reply["expression"], reply["motion"]),
                  ("happy", "happy", "wiggle"))
            mood_after, motion_after = mood_status(
                "HTTP mood drives the existing controller")
            check("HTTP mood label", mood_after.group(1), "happy")
            check("HTTP mood face", mood_after.group(2), "happy")
            check("HTTP mood motion", mood_after.group(3), "wiggle")
            check("HTTP mood motion is running", motion_after.group(2), "running")

            code, body, _ = http_request("POST", "/api/mood",
                                         '{"name":"stop"}', token=api_token)
            http_bodies.append(body)
            check("HTTP mood stop HTTP code", code, 200)
            reply = json.loads(body)
            check("HTTP mood stop keeps the face", reply["expression"], "happy")
            check("HTTP mood stop reports screen kept", reply["screen"], "kept")
            stopped_mood, stopped_motion = mood_status(
                "HTTP mood stop reaches the existing controllers")
            check("HTTP mood stop clears the label", stopped_mood.group(1), "none")
            check("HTTP mood stop keeps the sad/happy face",
                  stopped_mood.group(2), "happy")
            check("HTTP mood stop stops the motion", stopped_motion.group(2), "stopped")
            check("HTTP mood stop disables both outputs",
                  (stopped_motion.group(9), stopped_motion.group(13)), ("off", "off"))

            # --- allow-lists and malformed input ------------------------
            code, body, _ = http_request("POST", "/api/mood",
                                         '{"name":"dance"}', token=api_token)
            http_bodies.append(body)
            check("unknown mood name is rejected", code, 400)
            check("unknown mood error", json.loads(body)["error"], "invalid_name")
            code, body, _ = http_request("POST", "/api/mood",
                                         '{"mood":"happy"}', token=api_token)
            http_bodies.append(body)
            check("malformed body is rejected", code, 400)
            check("malformed body error", json.loads(body)["error"], "invalid_body")
            oversized = (b"POST /api/mood HTTP/1.1\r\nHost: board\r\n"
                         b"Content-Type: application/json\r\n"
                         b"Content-Length: 200\r\n"
                         b"X-Auth-Token: " + api_token.encode() + b"\r\n"
                         b"Connection: close\r\n\r\n" + b"a" * 200)
            reply_text = raw_http(oversized)
            check("oversized body is rejected", " 413 " in reply_text, True)
            check("oversized body error", "request_too_large" in reply_text, True)

            code, body, headers = http_request("GET", "/api/mood")
            http_bodies.append(body)
            check("GET cannot trigger a mood", code, 405)
            check("GET rejection advertises POST",
                  "POST" in headers.get("Allow", ""), True)
            code, body, headers = http_request("POST", "/api/status", "{}",
                                               token=api_token)
            http_bodies.append(body)
            check("POST cannot read a page", code, 405)
            check("POST rejection advertises GET",
                  "GET" in headers.get("Allow", ""), True)
            code, body, _ = http_request("GET", "/nope")
            http_bodies.append(body)
            check("unknown path is rejected", code, 404)
            check("unknown path error", json.loads(body)["error"], "not_found")
            code, body, _ = http_request("GET", "/favicon.ico")
            check("favicon returns no content", code, 204)

            # A secret typed into the URL must be rejected and never logged.
            leak_probe = (f"GET /api/status?token={api_token} HTTP/1.1\r\n"
                          f"Host: board\r\nConnection: close\r\n\r\n").encode()
            reply_text = raw_http(leak_probe)
            check("token in the URL is rejected", " 400 " in reply_text, True)
            serial_probe = send(b"web status\n")
            check("a rejected URL never reaches the serial log",
                  any(api_token in line for line in serial_probe), False)

            # --- motion reuses the shared engine ------------------------
            code, body, _ = http_request("POST", "/api/motion",
                                         '{"name":"together"}', token=api_token)
            http_bodies.append(body)
            check("HTTP motion HTTP code", code, 200)
            reply = json.loads(body)
            check("HTTP motion reply", (reply["motion"], reply["steps"]),
                  ("together", 10))
            polls_running = 0
            uptimes = []
            for _ in range(5):
                code, polled, _ = http_request("GET", "/api/status")
                http_bodies.append(polled)
                check("status polling during motion returns 200", code, 200)
                snapshot = json.loads(polled)
                check("polling keeps Wi-Fi connected",
                      snapshot["wifi"]["state"], "connected")
                if (snapshot["motion"]["name"] == "together" and
                        snapshot["motion"]["state"] == "running"):
                    polls_running += 1
                uptimes.append(snapshot["uptime_ms"])
                time.sleep(0.25)
            check("HTTP polling observes the running sequence",
                  polls_running >= 1, True)
            check("uptime advances while HTTP and motion run",
                  uptimes[-1] > uptimes[0], True)
            eyes_status("OLED status stays responsive during HTTP", "happy", "eyes")
            running = motion_status("HTTP does not cancel the sequence")
            check("HTTP-polled sequence still runs together",
                  running.group(1), "together")

            code, body, _ = http_request("POST", "/api/motion",
                                         '{"name":"sway"}', token=api_token)
            http_bodies.append(body)
            check("unknown motion name is rejected", code, 400)
            check("unknown motion error", json.loads(body)["error"], "invalid_name")
            running = motion_status("invalid HTTP motion keeps the sequence")
            check("invalid HTTP motion keeps together", running.group(1), "together")
            code, body, _ = http_request("POST", "/api/motion",
                                         '{"name":"stop"}', token=api_token)
            http_bodies.append(body)
            check("HTTP motion stop HTTP code", code, 200)
            reply = json.loads(body)
            check("HTTP motion stop reply",
                  (reply["state"], reply["output"]), ("stopped", "off"))
            stopped_mood, stopped_motion = mood_status(
                "HTTP motion stop reaches the existing engine")
            check("HTTP motion stop is stopped",
                  stopped_motion.group(2), "stopped")

            # Ten writes are allowed per window; wait for the next window.
            time.sleep(10.3)

            # Every allow-listed name is exercised at least once.
            for mood_name in ("sad", "normal"):
                code, body, _ = http_request(
                    "POST", "/api/mood", json.dumps({"name": mood_name}),
                    token=api_token)
                http_bodies.append(body)
                check(f"HTTP mood {mood_name} HTTP code", code, 200)
                reply = json.loads(body)
                check(f"HTTP mood {mood_name} reply",
                      (reply["mood"], reply["expression"]),
                      (mood_name, mood_name))
            for motion_name, total in (("wiggle", 24), ("alternate", 10),
                                       ("neutral", 1)):
                code, body, _ = http_request(
                    "POST", "/api/motion", json.dumps({"name": motion_name}),
                    token=api_token)
                http_bodies.append(body)
                check(f"HTTP motion {motion_name} HTTP code", code, 200)
                reply = json.loads(body)
                check(f"HTTP motion {motion_name} reply",
                      (reply["motion"], reply["steps"]), (motion_name, total))
            mood_after, _ = mood_status("HTTP motion clears the mood label")
            check("HTTP motion clears the mood", mood_after.group(1), "none")
            check("HTTP motion keeps the normal face",
                  mood_after.group(2), "normal")
            check("HTTP motion is neutral or finished",
                  mood_after.group(3) in ("neutral", "none"), True)
            code, body, _ = http_request("POST", "/api/motion",
                                         '{"name":"stop"}', token=api_token)
            http_bodies.append(body)
            check("HTTP motion stop after name coverage", code, 200)

            # --- write rate limit ---------------------------------------
            time.sleep(10.3)
            burst_codes = []
            for _ in range(12):
                code, _, _ = http_request("POST", "/api/mood",
                                          '{"name":"stop"}', token=api_token)
                burst_codes.append(code)
            check("a write burst is rate limited", 429 in burst_codes, True)
            check("rate limit allows the first ten writes",
                  all(code == 200 for code in burst_codes[:10]), True)
            check("rate limit rejects only later writes",
                  burst_codes[10:] == [429, 429], True)
            time.sleep(10.3)
            code, body, _ = http_request("GET", "/api/status")
            http_bodies.append(body)
            check("HTTP recovers after the rate window", code, 200)

            web_after = web_status("web counters after the HTTP tests")
            check("web counted requests", int(web_after.group(2)) > 0, True)
            check("web counted writes", int(web_after.group(3)) > 0, True)
            check("web counted rejections", int(web_after.group(4)) > 0, True)
            check("web counted rate limiting", int(web_after.group(5)) > 0, True)
            check("web auth remains enabled", web_after.group(6), "enabled")
            check("no HTTP response contains the token",
                  any(api_token in text for text in http_bodies), False)

            # --- Wi-Fi reconnect ----------------------------------------
            if not args.no_reconnect:
                expect("wifi reconnect command", b"wifi reconnect\n",
                       ["OK wifi=reconnect"])
                deadline = time.monotonic() + 40.0
                reconnected = None
                while time.monotonic() < deadline:
                    time.sleep(0.5)
                    candidate, _ = read_wifi()
                    if candidate is not None and candidate.group(1) == "connected":
                        reconnected = candidate
                        break
                check("Wi-Fi reconnects after an explicit request",
                      reconnected is not None, True)
                board_ip = reconnected.group(3)
                web_listening("web listens again after reconnect")
                code, body, _ = http_request("GET", "/api/status")
                http_bodies.append(body)
                check("HTTP answers again after reconnect", code, 200)
                check("reconnected box reports the new address",
                      json.loads(body)["wifi"]["ip"], board_ip)

            expect("restore normal eyes after HTTP", b"eyes normal\n",
                   ["OK expression=normal"])
            expect("finish any HTTP-started motion", b"motion stop\n",
                   ["OK motion=stopped output=off"])

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
              f"flash-free display, actual dual-servo movement and audible sound "
              f"still require user confirmation.", flush=True)
    finally:
        if port.is_open:
            # Terminate any partial/invalid line, then leave a safe, visible state:
            # audio silent, both servo outputs off, RGB off, normal eye screen.
            port.write(b"\naudio stop\nservo both stop\noff\neyes normal\n")
            port.flush()
            collect(0.4)
            port.close()


if __name__ == "__main__":
    main()
