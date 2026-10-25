"""Real virtual USB HID devices through Android's shell `hid` command.

python tools/vhid.py --serial SERIAL
Then send one JSON object per line (omitted devices retain their state):
  {"key": [0, 26]}                  keyboard modifier byte, HID usages (W)
  {"mouse": [30, -10, 0, 0]}       relative X/Y, wheel, button bitmask
  {"pad": [128,128,255,128,0,0,0,8]}  LX/LY/RX/RY, LT/RT, buttons, hat
Keyboard: [] releases all. Mouse: [] stops/releases. Pad: [] centres/releases.
Pad bits: A B X Y LB RB LT RT Select Start L3 R3. Hat: 0 up, 2 right,
4 down, 6 left, 8 neutral. EOF removes all three devices.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

KEYBOARD = bytes.fromhex(
    "05 01 09 06 a1 01 05 07 19 e0 29 e7 15 00 25 01 75 01 95 08 81 02 "
    "75 08 95 01 81 01 19 00 29 65 15 00 25 65 75 08 95 06 81 00 c0")
MOUSE = bytes.fromhex(
    "05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 05 15 00 25 01 "
    "75 01 95 05 81 02 75 03 95 01 81 01 05 01 09 30 09 31 16 01 80 "
    "26 ff 7f 75 10 95 02 81 06 09 38 15 81 25 7f 75 08 95 01 81 06 c0 c0")
PAD = bytes.fromhex(
    "05 01 09 05 a1 01 05 09 09 01 09 02 09 04 09 05 09 07 09 08 "
    "09 09 09 0a 09 0b 09 0c 09 0e 09 0f 15 00 25 01 75 01 95 0c "
    "81 02 75 04 95 01 81 01 05 01 09 30 09 31 09 32 09 35 15 00 "
    "26 ff 00 75 08 95 04 81 02 05 02 09 c5 09 c4 95 02 81 02 "
    "05 01 09 39 15 00 25 07 35 00 46 3b 01 65 14 75 04 95 01 "
    "81 42 65 00 75 04 95 01 81 01 c0")


def report(kind, values):
    if not isinstance(values, list) or any(type(value) is not int for value in values):
        raise ValueError("HID values must be a list of integers")
    if kind == "key":
        if not values:
            return [0] * 8
        if not 1 <= len(values) <= 7 or any(not 0 <= v <= 255 for v in values):
            raise ValueError("keyboard: modifier byte and up to six HID usages")
        return [values[0], 0] + values[1:] + [0] * (7 - len(values))
    if kind == "mouse":
        x, y, wheel, buttons = values or [0, 0, 0, 0]
        if not (-32767 <= x <= 32767 and -32767 <= y <= 32767 and -127 <= wheel <= 127 and 0 <= buttons <= 31):
            raise ValueError("mouse value outside the HID descriptor's range")
        return [buttons, x & 255, (x >> 8) & 255, y & 255, (y >> 8) & 255, wheel & 255]
    if kind == "pad":
        x, y, rx, ry, lt, rt, buttons, hat = values or [128, 128, 128, 128, 0, 0, 0, 8]
        if not all(0 <= v <= 255 for v in (x, y, rx, ry, lt, rt)) or not 0 <= buttons <= 4095 or not 0 <= hat <= 8:
            raise ValueError("gamepad value outside the HID descriptor's range")
        return [buttons & 255, buttons >> 8, x, y, rx, ry, lt, rt, hat]
    raise ValueError("device must be key, mouse, or pad")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    adb = os.environ.get("ADB", "adb")
    out = Path(__file__).resolve().parents[1] / "build/hardware-input"
    out.mkdir(parents=True, exist_ok=True)
    devices = {"key": (1, KEYBOARD), "mouse": (2, MOUSE), "pad": (3, PAD)}
    with (out / "hid.log").open("wb") as log:
        process = subprocess.Popen([adb, "-s", args.serial, "shell", "hid -"], stdin=subprocess.PIPE, stdout=log, stderr=log)

        def send(command):
            process.stdin.write((json.dumps(command) + "\n").encode())
            process.stdin.flush()

        try:
            for kind, (identifier, descriptor) in devices.items():
                send(dict(id=identifier, command="register", name="Void QA " + kind,
                          vid=0x18d1, pid=0x2c50 + identifier, bus="usb", descriptor=list(descriptor)))
            # UHID_OPEN predates inputflinger readiness; confirm registration before sending reports.
            deadline = time.monotonic() + 15
            while True:
                inventory = subprocess.run([adb, "-s", args.serial, "shell", "dumpsys input"], capture_output=True, check=True).stdout
                if all(("Void QA " + kind).encode() in inventory for kind in devices):
                    break
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError("virtual HID registration failed; see " + str(out / "hid.log"))
                time.sleep(.2)
            (out / "hid-devices.txt").write_bytes(inventory)
            time.sleep(.3)
            for kind, (identifier, _) in devices.items():
                send(dict(id=identifier, command="report", report=report(kind, [])))
            print("HID ready: keyboard, mouse, gamepad", flush=True)
            for line in sys.stdin:
                try:
                    command = json.loads(line)
                    for kind, values in command.items():
                        send(dict(id=devices[kind][0], command="report", report=report(kind, values)))
                    time.sleep(.04)
                    print("sent " + line.strip(), flush=True)
                except (ValueError, KeyError, TypeError) as error:
                    print(str(error), flush=True)
        finally:
            if process.poll() is None:
                for kind, (identifier, _) in devices.items():
                    send(dict(id=identifier, command="report", report=report(kind, [])))
                time.sleep(.1)
                process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
