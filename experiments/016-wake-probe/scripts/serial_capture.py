#!/usr/bin/env python3
"""读取探针串口并原样写到 stdout，供后台日志采集（work/ 下，不入库）。"""
import sys

import serial

PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5D4D001473-if00"

ser = serial.Serial(PORT, 115200, timeout=0.2)
ser.dtr = False
ser.rts = False
try:
    while True:
        data = ser.read(4096)
        if data:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
except KeyboardInterrupt:
    pass
finally:
    ser.close()
